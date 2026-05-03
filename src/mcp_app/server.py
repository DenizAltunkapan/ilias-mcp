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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AppContext:
    def __init__(
        self,
        settings: Settings,
        auth_service: AuthService,
        course_service: CourseService,
        calendar_service: CalendarService,
    ) -> None:
        self.settings = settings
        self.auth_service = auth_service
        self.course_service = course_service
        self.calendar_service = calendar_service


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
    course_service = CourseService(settings=settings, session=session, auth_service=auth_service)
    calendar_service = CalendarService(settings=settings, session=session, auth_service=auth_service)
    logger.info("ILIAS MCP server initialized and ready.")
    yield AppContext(
        settings=settings,
        auth_service=auth_service,
        course_service=course_service,
        calendar_service=calendar_service,
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
        "courses": [{"title": c.title, "url": c.url, "ref_id": c.ref_id} for c in courses],
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
    }


def main() -> None:
    logger.info("Starting ILIAS MCP server process...")
    mcp.run()


if __name__ == "__main__":
    main()
