"""Service layer."""

from services.auth_service import AuthService, IliasAuthError
from services.calendar_service import CalendarService, IliasCalendarError
from services.course_service import CourseService, IliasCourseError
from services.news_service import IliasNewsError, NewsService
from services.repository_service import IliasRepositoryError, RepositoryService

__all__ = [
    "AuthService",
    "CalendarService",
    "CourseService",
    "IliasAuthError",
    "IliasCalendarError",
    "IliasCourseError",
    "IliasNewsError",
    "IliasRepositoryError",
    "NewsService",
    "RepositoryService",
]
