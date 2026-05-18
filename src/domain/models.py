from dataclasses import dataclass


@dataclass(frozen=True)
class Course:
    title: str
    url: str
    ref_id: str


@dataclass(frozen=True)
class CalendarEvent:
    date_label: str
    time_label: str
    title: str
    action_url: str
    properties: dict[str, str]


@dataclass(frozen=True)
class RepositoryItem:
    title: str
    item_type: str
    url: str
    ref_id: str


@dataclass(frozen=True)
class FileContent:
    ref_id: str
    title: str
    file_url: str
    content_type: str
    text: str
    parsed_with: str


@dataclass(frozen=True)
class DownloadedFile:
    ref_id: str
    title: str
    file_url: str
    local_path: str
    content_type: str
    size_bytes: int
    status: str


@dataclass(frozen=True)
class NewsItem:
    title: str
    content: str
    context_title: str
    context_url: str
    ref_id: str
    author: str
    date_label: str
    url: str


@dataclass(frozen=True)
class ExerciseAssignment:
    ass_id: str
    title: str
    deadline: str
    status: str


@dataclass(frozen=True)
class SubmittedFile:
    filename: str
    size: str
    date: str


@dataclass(frozen=True)
class TeamMember:
    user_id: str
    name: str
