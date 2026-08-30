import requests
from bs4 import BeautifulSoup

from core.config import Settings
from services.repository_service import RepositoryService


def _service() -> RepositoryService:
    service = RepositoryService.__new__(RepositoryService)
    service.settings = Settings(
        ilias_user="user",
        ilias_pass="pass",
        ilias_base_url="https://ilias3.uni-stuttgart.de",
        ilias_client_id="Uni_Stuttgart",
    )
    return service


def test_extract_ref_id_from_ilias_routes() -> None:
    assert (
        RepositoryService._extract_ref_id(
            "https://ilias3.uni-stuttgart.de/goto.php?target=file_12345_download"
        )
        == "12345"
    )
    assert (
        RepositoryService._extract_ref_id(
            "https://ilias3.uni-stuttgart.de/goto.php?target=fold_23456"
        )
        == "23456"
    )
    assert (
        RepositoryService._extract_ref_id(
            "https://ilias3.uni-stuttgart.de/ilias.php?baseClass=ilrepositorygui&ref_id=34567"
        )
        == "34567"
    )
    assert (
        RepositoryService._extract_ref_id(
            "https://ilias3.uni-stuttgart.de/go/crs/45678"
        )
        == "45678"
    )


def test_extract_items_from_ilias_container_html() -> None:
    html = """
    <div class="ilContainerBlock">
      <div class="ilObjListRow">
        <h4 class="il-item-title">
          <a href="/goto.php?target=fold_111">Material</a>
        </h4>
        <img alt="Ordner" />
      </div>
      <div class="ilObjListRow">
        <h4 class="il-item-title">
          <a href="/goto.php?target=file_222_download">Slides</a>
        </h4>
        <img alt="Datei" />
      </div>
      <div class="ilObjListRow">
        <h4 class="il-item-title">
          <button data-action="ilias.php?baseClass=ilrepositorygui&ref_id=333">
            Seminar
          </button>
        </h4>
        <img alt="Kurs" />
      </div>
    </div>
    """

    items = _service()._extract_items(html, current_ref_id="999")

    assert [(item.title, item.item_type, item.ref_id) for item in items] == [
        ("Material", "folder", "111"),
        ("Slides", "file", "222"),
        ("Seminar", "course", "333"),
    ]


def test_permanent_download_url_matches_ilias_file_goto_route() -> None:
    assert (
        _service()._permanent_file_download_url("222")
        == "https://ilias3.uni-stuttgart.de/goto.php?target=file_222_download"
    )


FOLDER_PAGE = """
<div id="ilContentContainer">
  <a href="/goto.php?target=file_222_download">Slides</a>
  <a href="/goto.php?target=file_333_download">Notes</a>
</div>
"""

FILE_PAGE = """
<div id="ilContentContainer">
  <a href="/ilias.php?cmdClass=ilObjFileGUI&cmd=sendfile&ref_id=222">Download</a>
</div>
"""


def test_detect_file_url_ignores_downloads_of_contained_files() -> None:
    # A folder page lists its children's download links; none belong to the
    # folder itself, so download_file(<folder>) must not grab the first child.
    soup = BeautifulSoup(FOLDER_PAGE, "html.parser")
    assert _service()._detect_file_url(soup, "111") == ""


def test_detect_file_url_returns_download_for_matching_ref_id() -> None:
    soup = BeautifulSoup(FILE_PAGE, "html.parser")
    assert _service()._detect_file_url(soup, "222").endswith("ref_id=222")


def test_detect_file_url_matches_goto_download_target() -> None:
    soup = BeautifulSoup(FOLDER_PAGE, "html.parser")
    assert _service()._detect_file_url(soup, "333").endswith("file_333_download")


def _response(content: bytes, **headers: str) -> requests.Response:
    resp = requests.Response()
    resp._content = content
    resp.headers.update(headers)
    return resp


def test_uploaded_html_file_is_not_treated_as_an_error_page() -> None:
    # ILIAS serves uploaded .html files as text/html, but with a filename.
    resp = _response(
        b"<!DOCTYPE html><html><head><title>Reaction test</title>",
        **{
            "Content-Type": "text/html;charset=UTF-8",
            "Content-Disposition": 'attachment; filename="A.1.html"',
        },
    )
    assert RepositoryService._looks_like_html_page(resp) is False


def test_inline_pdf_download_is_not_treated_as_an_error_page() -> None:
    resp = _response(
        b"%PDF-1.7\n",
        **{
            "Content-Type": "application/pdf",
            "Content-Disposition": 'inline; filename="fsub-01.pdf"',
        },
    )
    assert RepositoryService._looks_like_html_page(resp) is False


def test_ilias_ui_page_without_disposition_is_still_rejected() -> None:
    # Folder views and permission errors come back as HTML with no filename.
    resp = _response(
        b"<!DOCTYPE html><html><head><title>ILIAS</title>",
        **{"Content-Type": "text/html; charset=UTF-8"},
    )
    assert RepositoryService._looks_like_html_page(resp) is True


def test_html_body_without_content_type_is_still_rejected() -> None:
    resp = _response(b"  <html><body>error</body></html>")
    assert RepositoryService._looks_like_html_page(resp) is True


def test_fix_mojibake_filename() -> None:
    assert RepositoryService._fix_mojibake("Ãbungsblatt03.pdf") == "Übungsblatt03.pdf"
