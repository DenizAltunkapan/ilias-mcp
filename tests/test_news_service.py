from core.config import Settings
from services.news_service import NewsService


def _service() -> NewsService:
    service = NewsService.__new__(NewsService)
    service.settings = Settings(
        ilias_user="user",
        ilias_pass="pass",
        ilias_base_url="https://ilias3.uni-stuttgart.de",
        ilias_client_id="Uni_Stuttgart",
    )
    return service


def test_extract_timeline_news() -> None:
    html = """
    <div class="ilNewsTimelineContentSection">
      <div class="light small ilNewsTimelineEditInfo">dozent - 10.05.2026</div>
      <h4 class="ilNewsTimelineTruncatedText">Neue Folien</h4>
      <p class="ilNewsTimelineObjHead">
        <a href="./goto.php?client_id=Uni_Stuttgart&target=crs_12345">
          Seminar
        </a>
      </p>
      <div class="dynamic-height-wrap">Bitte Kapitel 3 lesen.</div>
    </div>
    """

    news = _service()._extract_news(html)

    assert len(news) == 1
    assert news[0].title == "Neue Folien"
    assert news[0].content == "Bitte Kapitel 3 lesen."
    assert news[0].context_title == "Seminar"
    assert news[0].ref_id == "12345"
    assert news[0].author == "dozent"
    assert news[0].date_label == "10.05.2026"


def test_extract_forum_ref_id_from_news_context_url() -> None:
    assert (
        NewsService._extract_ref_id(
            "https://ilias3.uni-stuttgart.de/go/frm/4453498/_214101_732420"
        )
        == "4453498"
    )


def test_extract_table_news() -> None:
    html = """
    <table>
      <tr>
        <td class="il-news">
          <h2><a href="./goto.php?client_id=Uni_Stuttgart&target=file_222">PDF</a></h2>
          <h4><a href="./goto.php?client_id=Uni_Stuttgart&target=file_222_download">Datei aktualisiert</a></h4>
          <div class="il-news-content">
            <p>Eine Datei wurde aktualisiert.</p>
            <p class="il_BlockInfo">Erstellt: 10.05.2026</p>
            <p class="il_BlockInfo">Autor: dozent</p>
          </div>
        </td>
      </tr>
    </table>
    """

    news = _service()._extract_news(html)

    assert len(news) == 1
    assert news[0].title == "Datei aktualisiert"
    assert news[0].context_title == "PDF"
    assert news[0].ref_id == "222"
    assert news[0].author == "dozent"
    assert news[0].date_label == "10.05.2026"
