from __future__ import annotations

from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core.config import Settings
from domain.models import CalendarEvent
from services.auth_service import AuthService


class IliasCalendarError(RuntimeError):
    pass


class CalendarService:
    def __init__(
        self, settings: Settings, session: requests.Session, auth_service: AuthService
    ) -> None:
        self.settings = settings
        self.session = session
        self.auth_service = auth_service

    def list_events(self, seed: str) -> list[CalendarEvent]:
        self.auth_service.ensure_logged_in()
        url = self.settings.calendar_url(seed)

        try:
            resp = self.session.get(url, timeout=self.settings.timeout_seconds)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise IliasCalendarError(f"Failed to fetch calendar page: {exc}") from exc

        return self._extract_events(resp.text)

    def _extract_events(self, html: str) -> list[CalendarEvent]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[CalendarEvent] = []

        for group in soup.select("div.il-item-group"):
            heading = group.find("h3")
            date_label = (
                self._clean(heading.get_text(" ", strip=True)) if heading else ""
            )

            for item in group.select("li.il-std-item-container"):
                time_el = item.select_one("div.col-sm-3")
                time_label = (
                    self._clean(time_el.get_text(" ", strip=True)) if time_el else ""
                )

                title_el = item.select_one("h4.il-item-title")
                title = (
                    self._clean(title_el.get_text(" ", strip=True)) if title_el else ""
                )
                if not title:
                    continue

                action_url = ""
                action_btn = (
                    title_el.find("button", attrs={"data-action": True})
                    if title_el
                    else None
                )
                if action_btn:
                    action_url = self._normalize_url(action_btn.get("data-action", ""))

                properties: dict[str, str] = {}
                for name_el in item.select("span.il-item-property-name"):
                    value_el = name_el.find_next_sibling(
                        "span", class_="il-item-property-value"
                    )
                    name = self._clean(name_el.get_text(" ", strip=True))
                    value = (
                        self._clean(value_el.get_text(" ", strip=True))
                        if value_el
                        else ""
                    )
                    if name:
                        properties[name] = value

                events.append(
                    CalendarEvent(
                        date_label=date_label,
                        time_label=time_label,
                        title=title,
                        action_url=action_url,
                        properties=properties,
                    )
                )

        return events

    def _normalize_url(self, maybe_url: str) -> str:
        maybe_url = maybe_url.strip()
        if not maybe_url:
            return ""
        if maybe_url.startswith("http"):
            return maybe_url
        return urljoin(self.settings.ilias_base_url, maybe_url)

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(text.split())
