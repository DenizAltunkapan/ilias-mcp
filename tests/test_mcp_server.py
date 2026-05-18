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


@pytest.mark.anyio
async def test_mcp_lists_course_summary_prompt(monkeypatch) -> None:
    monkeypatch.setenv("ILIAS_USER", "user")
    monkeypatch.setenv("ILIAS_PASS", "pass")
    monkeypatch.setenv("ILIAS_BASE_URL", "https://ilias3.uni-stuttgart.de")
    monkeypatch.setenv("ILIAS_CLIENT_ID", "Uni_Stuttgart")

    from mcp_app.server import mcp

    async with create_connected_server_and_client_session(mcp) as session:
        prompts = await session.list_prompts()

    names = {prompt.name for prompt in prompts.prompts}
    assert "summarize_latest_course_lecture" in names


@pytest.mark.anyio
async def test_mcp_renders_course_summary_prompt(monkeypatch) -> None:
    monkeypatch.setenv("ILIAS_USER", "user")
    monkeypatch.setenv("ILIAS_PASS", "pass")
    monkeypatch.setenv("ILIAS_BASE_URL", "https://ilias3.uni-stuttgart.de")
    monkeypatch.setenv("ILIAS_CLIENT_ID", "Uni_Stuttgart")

    from mcp_app.server import mcp

    async with create_connected_server_and_client_session(mcp) as session:
        prompt = await session.get_prompt(
            "summarize_latest_course_lecture",
            arguments={"course_name": "Analysis 1", "course_ref_id": "12345"},
        )

    assert prompt.messages
    message = prompt.messages[0]
    assert message.role == "user"
    assert message.content.type == "text"
    assert "Analysis 1" in message.content.text
    assert "12345" in message.content.text
    assert "Exam Relevance" in message.content.text
    assert "same language as the current conversation" in message.content.text
