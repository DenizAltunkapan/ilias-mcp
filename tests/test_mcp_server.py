import pytest
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.mark.anyio
async def test_mcp_lists_supported_tools(monkeypatch) -> None:
    monkeypatch.setenv("ILIAS_USER", "user")
    monkeypatch.setenv("ILIAS_PASS", "pass")
    monkeypatch.setenv("ILIAS_BASE_URL", "https://ilias3.uni-stuttgart.de")
    monkeypatch.setenv("ILIAS_CLIENT_ID", "Uni_Stuttgart")

    from mcp_app.server import mcp

    async with create_connected_server_and_client_session(mcp) as session:
        tools = await session.list_tools()

    names = {tool.name for tool in tools.tools}
    assert {
        "login",
        "list_courses",
        "list_calendar_events",
        "server_info",
        "list_dashboard_news",
        "list_repository_items",
        "get_repository_item_details",
        "get_file_content",
        "crawl_repository",
        "download_file",
        "download_repository_files",
    }.issubset(names)
