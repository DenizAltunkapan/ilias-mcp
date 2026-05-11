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


def test_fix_mojibake_filename() -> None:
    assert RepositoryService._fix_mojibake("Ãbungsblatt03.pdf") == "Übungsblatt03.pdf"
