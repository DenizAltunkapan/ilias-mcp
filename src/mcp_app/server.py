from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

import requests
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from core.config import Settings, load_settings
from services.auth_service import AuthService, IliasAuthError
from services.calendar_service import CalendarService, IliasCalendarError
from services.course_service import CourseService, IliasCourseError
from services.news_service import IliasNewsError, NewsService
from services.repository_service import IliasRepositoryError, RepositoryService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AppContext:
    def __init__(
        self,
        settings: Settings,
        auth_service: AuthService,
        course_service: CourseService,
        calendar_service: CalendarService,
        news_service: NewsService,
        repository_service: RepositoryService,
    ) -> None:
        self.settings = settings
        self.auth_service = auth_service
        self.course_service = course_service
        self.calendar_service = calendar_service
        self.news_service = news_service
        self.repository_service = repository_service


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[AppContext]:
    settings = load_settings()
    logger.info(
        "Initializing ILIAS MCP server (base_url=%s, client_id=%s, lang=%s, timeout=%ss)",
        settings.ilias_base_url,
        settings.ilias_client_id,
        settings.lang,
        settings.timeout_seconds,
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "ilias-mcp/0.1 (+python-requests)",
            "Referer": settings.login_page,
        }
    )

    auth_service = AuthService(settings=settings, session=session)
    course_service = CourseService(
        settings=settings, session=session, auth_service=auth_service
    )
    calendar_service = CalendarService(
        settings=settings, session=session, auth_service=auth_service
    )
    news_service = NewsService(
        settings=settings, session=session, auth_service=auth_service
    )
    repository_service = RepositoryService(
        settings=settings, session=session, auth_service=auth_service
    )
    logger.info("ILIAS MCP server initialized and ready.")
    yield AppContext(
        settings=settings,
        auth_service=auth_service,
        course_service=course_service,
        calendar_service=calendar_service,
        news_service=news_service,
        repository_service=repository_service,
    )
    logger.info("Shutting down ILIAS MCP server.")


mcp = FastMCP(
    "ilias-mcp",
    lifespan=lifespan,
    instructions=(
        "Use this server for ILIAS operations. "
        "Call login first, then list_courses to retrieve enrolled courses."
    ),
)


def _app(ctx: Context[ServerSession, AppContext]) -> AppContext:
    app = ctx.request_context.lifespan_context
    if not app:
        raise RuntimeError("Lifespan context is not initialized.")
    return app


@mcp.tool()
async def login(ctx: Context[ServerSession, AppContext]) -> dict[str, str]:
    """Authenticate to ILIAS using credentials from .env."""
    app = _app(ctx)
    try:
        message = app.auth_service.login()
        logger.info("Login succeeded.")
        return {"status": "ok", "message": message}
    except IliasAuthError as exc:
        logger.warning("Login failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def list_courses(ctx: Context[ServerSession, AppContext]) -> dict[str, object]:
    """Return all enrolled ILIAS courses with title, URL and ref_id."""
    app = _app(ctx)
    try:
        courses = app.course_service.list_courses()
    except (IliasAuthError, IliasCourseError) as exc:
        logger.warning("Course listing failed: %s", exc)
        return {"status": "error", "message": str(exc), "courses": []}

    return {
        "status": "ok",
        "count": len(courses),
        "courses": [
            {"title": c.title, "url": c.url, "ref_id": c.ref_id} for c in courses
        ],
    }


@mcp.tool()
async def list_calendar_events(
    ctx: Context[ServerSession, AppContext],
    seed: str = "",
) -> dict[str, object]:
    """List calendar agenda events for a given day (`YYYY-MM-DD`)."""
    app = _app(ctx)
    day = seed.strip() or date.today().isoformat()
    try:
        events = app.calendar_service.list_events(day)
    except (IliasAuthError, IliasCalendarError) as exc:
        logger.warning("Calendar listing failed: %s", exc)
        return {"status": "error", "message": str(exc), "seed": day, "events": []}

    return {
        "status": "ok",
        "seed": day,
        "count": len(events),
        "events": [
            {
                "date": event.date_label,
                "time": event.time_label,
                "title": event.title,
                "action_url": event.action_url,
                "properties": event.properties,
            }
            for event in events
        ],
    }


@mcp.tool()
async def server_info(ctx: Context[ServerSession, AppContext]) -> dict[str, str]:
    """Return non-sensitive runtime configuration metadata."""
    app = _app(ctx)
    return {
        "base_url": app.settings.ilias_base_url,
        "client_id": app.settings.ilias_client_id,
        "lang": app.settings.lang,
        "timeout_seconds": str(app.settings.timeout_seconds),
        "download_dir": app.settings.download_dir,
        "dashboard_news_url": app.settings.dashboard_news_url,
    }


@mcp.tool()
async def list_repository_items(
    ctx: Context[ServerSession, AppContext],
    ref_id: str,
) -> dict[str, object]:
    """List child items (course/folder/file/forum/...) under an ILIAS repository ref_id."""
    app = _app(ctx)
    try:
        items = app.repository_service.list_items(ref_id=ref_id)
    except (IliasAuthError, IliasRepositoryError) as exc:
        logger.warning("Repository listing failed for ref_id=%s: %s", ref_id, exc)
        return {"status": "error", "message": str(exc), "ref_id": ref_id, "items": []}

    return {
        "status": "ok",
        "ref_id": ref_id,
        "count": len(items),
        "items": [
            {
                "title": item.title,
                "type": item.item_type,
                "url": item.url,
                "ref_id": item.ref_id,
            }
            for item in items
        ],
    }


@mcp.tool()
async def get_repository_item_details(
    ctx: Context[ServerSession, AppContext],
    ref_id: str,
) -> dict[str, object]:
    """Get page-level details for a repository item, including detected file URL if available."""
    app = _app(ctx)
    try:
        details = app.repository_service.get_item_details(ref_id=ref_id)
    except (IliasAuthError, IliasRepositoryError) as exc:
        logger.warning("Repository details failed for ref_id=%s: %s", ref_id, exc)
        return {"status": "error", "message": str(exc), "ref_id": ref_id}

    return {"status": "ok", **details}


@mcp.tool()
async def get_file_content(
    ctx: Context[ServerSession, AppContext],
    ref_id: str,
    max_chars: int = 20000,
    max_pdf_pages: int = 20,
) -> dict[str, object]:
    """Download file content by ref_id. PDFs are parsed to text via pypdf."""
    app = _app(ctx)
    try:
        content = app.repository_service.fetch_file_content(
            ref_id=ref_id,
            max_chars=max_chars,
            max_pdf_pages=max_pdf_pages,
        )
    except (IliasAuthError, IliasRepositoryError) as exc:
        logger.warning("File retrieval failed for ref_id=%s: %s", ref_id, exc)
        return {"status": "error", "message": str(exc), "ref_id": ref_id}

    return {
        "status": "ok",
        "ref_id": content.ref_id,
        "title": content.title,
        "file_url": content.file_url,
        "content_type": content.content_type,
        "parsed_with": content.parsed_with,
        "text": content.text,
    }


@mcp.tool()
async def crawl_repository(
    ctx: Context[ServerSession, AppContext],
    ref_id: str,
    max_depth: int = 8,
) -> dict[str, object]:
    """Recursively crawl an ILIAS course/folder and return all discovered repository items."""
    app = _app(ctx)
    try:
        items = app.repository_service.walk(ref_id=ref_id, max_depth=max_depth)
    except (IliasAuthError, IliasRepositoryError) as exc:
        logger.warning("Repository crawl failed for ref_id=%s: %s", ref_id, exc)
        return {"status": "error", "message": str(exc), "ref_id": ref_id, "items": []}

    return {
        "status": "ok",
        "ref_id": ref_id,
        "max_depth": max_depth,
        "count": len(items),
        "items": items,
    }


@mcp.tool()
async def download_repository_files(
    ctx: Context[ServerSession, AppContext],
    ref_id: str,
    extensions: str = "pdf",
    max_depth: int = 8,
    output_dir: str = "",
    overwrite: bool = False,
) -> dict[str, object]:
    """Recursively download files below ref_id. Defaults to PDFs and preserves folders."""
    app = _app(ctx)
    ext_list = [part.strip() for part in extensions.split(",") if part.strip()]
    try:
        files = app.repository_service.download_files(
            ref_id=ref_id,
            output_dir=output_dir or None,
            extensions=ext_list,
            max_depth=max_depth,
            overwrite=overwrite,
        )
    except (IliasAuthError, IliasRepositoryError, OSError) as exc:
        logger.warning("Repository download failed for ref_id=%s: %s", ref_id, exc)
        return {
            "status": "error",
            "message": str(exc),
            "ref_id": ref_id,
            "files": [],
        }

    return {
        "status": "ok",
        "ref_id": ref_id,
        "extensions": ext_list,
        "output_dir": output_dir or app.settings.download_dir,
        "count": len(files),
        "files": [
            {
                "title": file.title,
                "ref_id": file.ref_id,
                "file_url": file.file_url,
                "local_path": file.local_path,
                "content_type": file.content_type,
                "size_bytes": file.size_bytes,
                "status": file.status,
            }
            for file in files
        ],
    }


@mcp.tool()
async def download_file(
    ctx: Context[ServerSession, AppContext],
    ref_id: str,
    output_dir: str = "",
    filename: str = "",
    overwrite: bool = False,
) -> dict[str, object]:
    """Download one ILIAS file object by ref_id."""
    app = _app(ctx)
    try:
        file = app.repository_service.download_file(
            ref_id=ref_id,
            output_dir=output_dir or None,
            filename=filename,
            overwrite=overwrite,
        )
    except (IliasAuthError, IliasRepositoryError, OSError) as exc:
        logger.warning("Single file download failed for ref_id=%s: %s", ref_id, exc)
        return {"status": "error", "message": str(exc), "ref_id": ref_id}

    return {
        "status": "ok",
        "file": {
            "title": file.title,
            "ref_id": file.ref_id,
            "file_url": file.file_url,
            "local_path": file.local_path,
            "content_type": file.content_type,
            "size_bytes": file.size_bytes,
            "status": file.status,
        },
    }


@mcp.tool()
async def list_dashboard_news(
    ctx: Context[ServerSession, AppContext],
    limit: int = 30,
) -> dict[str, object]:
    """List news from the personal ILIAS dashboard (`ilPDNewsGUI`)."""
    app = _app(ctx)
    try:
        news = app.news_service.list_dashboard_news(limit=limit)
    except (IliasAuthError, IliasNewsError) as exc:
        logger.warning("Dashboard news listing failed: %s", exc)
        return {"status": "error", "message": str(exc), "news": []}

    return {
        "status": "ok",
        "count": len(news),
        "news": [
            {
                "title": item.title,
                "content": item.content,
                "context_title": item.context_title,
                "context_url": item.context_url,
                "ref_id": item.ref_id,
                "author": item.author,
                "date": item.date_label,
                "url": item.url,
            }
            for item in news
        ],
    }


@mcp.resource("ilias://courses")
async def courses_resource(ctx: Context[ServerSession, AppContext]) -> str:
    """All enrolled ILIAS courses as a context document (read-only, no side-effects).

    Use this as background context when the user asks about their courses without
    needing a full tool call. Tools like list_repository_items still require a ref_id.
    """
    app = _app(ctx)
    try:
        app.auth_service.ensure_logged_in()
        courses = app.course_service.list_courses()
    except (IliasAuthError, IliasCourseError) as exc:
        return f"Error fetching courses: {exc}"

    if not courses:
        return "No enrolled courses found."

    lines = ["# Enrolled ILIAS Courses\n"]
    for c in courses:
        lines.append(f"- **{c.title}** (ref_id: `{c.ref_id}`, url: {c.url})")
    return "\n".join(lines)


@mcp.resource("ilias://calendar/{seed}")
async def calendar_resource(ctx: Context[ServerSession, AppContext], seed: str) -> str:
    """ILIAS calendar events for a given day as a context document (format: YYYY-MM-DD).

    Prefer this over list_calendar_events when you only need to read the schedule
    passively. The tool variant is better when you need structured data for follow-up
    tool calls.
    """
    app = _app(ctx)
    day = seed.strip() or date.today().isoformat()
    try:
        app.auth_service.ensure_logged_in()
        events = app.calendar_service.list_events(day)
    except (IliasAuthError, IliasCalendarError) as exc:
        return f"Error fetching calendar for {day}: {exc}"

    if not events:
        return f"No events found for {day}."

    lines = [f"# ILIAS Calendar — {day}\n"]
    for ev in events:
        time_info = f"{ev.date_label} {ev.time_label}".strip()
        lines.append(f"## {ev.title}")
        if time_info:
            lines.append(f"**When:** {time_info}")
        for key, val in ev.properties.items():
            lines.append(f"**{key}:** {val}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    logger.info("Starting ILIAS MCP server process...")
    mcp.run()


if __name__ == "__main__":
    main()
