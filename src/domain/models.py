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
