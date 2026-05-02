from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core.config import Settings


class IliasAuthError(RuntimeError):
    pass


class AuthService:
    def __init__(self, settings: Settings, session: requests.Session) -> None:
        self.settings = settings
        self.session = session
        self._logged_in = False

    def login(self) -> str:
        if self._logged_in:
            return "Already logged in."

        try:
            resp = self.session.get(self.settings.login_page, timeout=self.settings.timeout_seconds)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise IliasAuthError(f"Failed to load login page: {exc}") from exc

        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form")
        if not form:
            raise IliasAuthError("Login form not found on ILIAS login page.")

        payload: dict[str, Any] = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            payload[name] = inp.get("value", "")

        self._inject_credentials(form, payload, self.settings.ilias_user, self.settings.ilias_pass)
        payload["cmd[doStandardAuthentication]"] = "Anmelden"

        action = str(form.get("action", "")).strip()
        if not action:
            raise IliasAuthError("Login form action is missing.")
        action_url = urljoin(self.settings.ilias_base_url, action)

        try:
            login_resp = self.session.post(
                action_url,
                data=payload,
                timeout=self.settings.timeout_seconds,
                allow_redirects=True,
            )
            login_resp.raise_for_status()

            dashboard = self.session.get(self.settings.dashboard_url, timeout=self.settings.timeout_seconds)
            dashboard.raise_for_status()
        except requests.RequestException as exc:
            raise IliasAuthError(f"Failed during login request flow: {exc}") from exc

        if not self._is_logged_in(dashboard.text):
            raise IliasAuthError("Login failed: logout marker not found.")

        self._logged_in = True
        return "Login successful."

    def ensure_logged_in(self) -> None:
        if not self._logged_in:
            self.login()

    @staticmethod
    def _inject_credentials(form: Any, payload: dict[str, Any], user: str, password: str) -> None:
        for inp in form.find_all("input"):
            name = inp.get("name")
            input_type = (inp.get("type") or "").lower()
            if not name:
                continue
            if input_type == "text":
                payload[name] = user
            elif input_type == "password":
                payload[name] = password

    @staticmethod
    def _is_logged_in(html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        return soup.find("a", href=lambda h: h and "doLogout" in h) is not None
