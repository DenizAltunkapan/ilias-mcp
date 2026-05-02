from dataclasses import dataclass


@dataclass(frozen=True)
class Course:
    title: str
    url: str
    ref_id: str
