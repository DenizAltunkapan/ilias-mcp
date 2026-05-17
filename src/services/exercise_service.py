from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from core.config import Settings
from domain.models import ExerciseAssignment, TeamMember
from services.auth_service import AuthService


class IliasExerciseError(RuntimeError):
    pass


class ExerciseService:
    def __init__(
        self, settings: Settings, session: requests.Session, auth_service: AuthService
    ) -> None:
        self.settings = settings
        self.session = session
        self.auth_service = auth_service

    # Assignments

    def list_assignments(self, ref_id: str) -> list[ExerciseAssignment]:
        self.auth_service.ensure_logged_in()
        url = self._overview_url(ref_id)
        resp = self._get(url, f"exercise overview {ref_id}")
        return self._extract_assignments(resp.text, ref_id)

    def _extract_assignments(self, html: str, ref_id: str) -> list[ExerciseAssignment]:
        soup = BeautifulSoup(html, "html.parser")
        assignments: list[ExerciseAssignment] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = str(a.get("href", ""))
            qs = parse_qs(urlparse(href).query)
            ass_id = qs.get("ass_id", [""])[0]
            if not ass_id or ass_id in seen:
                continue
            if "AssignmentPresentationGUI" not in href and "showOverview" not in href:
                continue
            seen.add(ass_id)
            title = " ".join(a.get_text(" ", strip=True).split())
            row = a.find_parent(["tr", "li", "div"])
            deadline = ""
            status = ""
            if row:
                text = row.get_text(" ", strip=True)
                m = re.search(r"\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?", text)
                if m:
                    deadline = m.group(0)
                for word in ("abgegeben", "nicht abgegeben", "bewertet", "submitted"):
                    if word.lower() in text.lower():
                        status = word
                        break
            assignments.append(
                ExerciseAssignment(
                    ass_id=ass_id, title=title, deadline=deadline, status=status
                )
            )
        return assignments

    # File submission

    def submit_file(self, ref_id: str, ass_id: str, local_path: str) -> dict[str, str]:
        """Upload a local file as an exercise submission."""
        self.auth_service.ensure_logged_in()
        path = Path(local_path).expanduser().resolve()
        if not path.exists():
            raise IliasExerciseError(f"Local file not found: {path}")

        # Step 1: GET upload form to discover cmdNode + rtoken
        form_url = self._upload_form_url(ref_id, ass_id)
        form_resp = self._get(form_url, "upload form")
        upload_handler_url, submit_url, input_name = self._parse_upload_form(
            form_resp.text, ref_id, ass_id
        )

        # Step 2: POST file to Dropzone handler → get file identifier
        file_id = self._dropzone_upload(upload_handler_url, path)

        # Step 3: POST form with the returned identifier
        payload = {input_name: file_id}
        post_resp = self.session.post(
            urljoin(self.settings.ilias_base_url + "/", submit_url),
            data=payload,
            timeout=self.settings.timeout_seconds,
            allow_redirects=True,
        )
        post_resp.raise_for_status()

        return {
            "status": "submitted",
            "filename": path.name,
            "file_id": file_id,
            "ref_id": ref_id,
            "ass_id": ass_id,
        }

    def _parse_upload_form(
        self, html: str, ref_id: str, ass_id: str
    ) -> tuple[str, str, str]:
        """Return (dropzone_upload_url, form_action_url, hidden_input_name)."""
        soup = BeautifulSoup(html, "html.parser")

        # Find the multipart form (not the search form)
        submit_url = ""
        input_name = "form/input_0/input_1[input_0][]"
        for form in soup.find_all("form", enctype="multipart/form-data"):
            action = str(form.get("action", "")).strip()
            if "ExSubmissionFileGUI" in action or "addUpload" in action:
                submit_url = action
                hidden = form.find("input", type="hidden")
                if hidden and hidden.get("name"):
                    input_name = str(hidden["name"])
                break

        # Dropzone handler URL from JS (capture full URL including ilias.php prefix)
        upload_handler_url = ""
        m = re.search(
            r"['\"]?(ilias\.php\?[^'\"]*ilRepoStandardUploadHandlerGUI&cmd=upload[^'\"]*)['\"]?",
            html,
        )
        if m:
            upload_handler_url = urljoin(self.settings.ilias_base_url + "/", m.group(1))

        if not upload_handler_url:
            raise IliasExerciseError(
                f"Could not locate Dropzone upload URL for ref_id={ref_id}, ass_id={ass_id}"
            )
        if not submit_url:
            raise IliasExerciseError(
                f"Could not locate submission form action for ref_id={ref_id}, ass_id={ass_id}"
            )

        return upload_handler_url, submit_url, input_name

    def _dropzone_upload(self, upload_url: str, path: Path) -> str:
        """POST file to ILIAS Dropzone handler; return the identifier string."""
        with path.open("rb") as fh:
            resp = self.session.post(
                upload_url,
                files={"file": (path.name, fh)},
                timeout=self.settings.timeout_seconds,
                allow_redirects=True,
            )
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception as exc:
            raise IliasExerciseError(
                f"Dropzone upload did not return JSON: {resp.text[:200]}"
            ) from exc

        # ILIAS returns {"identifier": "...", ...} or {"status":1,"":"filename"}
        file_id = (
            data.get("identifier")
            or data.get("file_id")
            or data.get("id")
            or data.get("")  # ILIAS quirk: identifier stored under empty-string key
            or ""
        )
        if not file_id or not data.get("status", 1):
            raise IliasExerciseError(
                f"Dropzone upload failed or missing identifier: {data}"
            )
        return str(file_id)

    def list_submitted_files(self, ref_id: str, ass_id: str) -> list[dict[str, str]]:
        """Return submitted files with their delivery IDs, names, and dates."""
        self.auth_service.ensure_logged_in()
        url = self._submission_screen_url(ref_id, ass_id)
        resp = self._get(url, f"submission screen {ref_id}/{ass_id}")
        return self._extract_submitted_files(resp.text)

    def delete_submitted_files(
        self, ref_id: str, ass_id: str, delivery_ids: list[str]
    ) -> dict[str, object]:
        """Delete submitted files by their delivery IDs (two-step: confirm then delete)."""
        self.auth_service.ensure_logged_in()
        url = self._submission_screen_url(ref_id, ass_id)
        page_resp = self._get(url, f"submission screen {ref_id}/{ass_id}")

        form_action = self._extract_submission_form_action(
            page_resp.text, ref_id, ass_id
        )

        # Step 1: confirmDeleteDelivered → shows confirmation page
        payload: list[tuple[str, str]] = [("delivered[]", did) for did in delivery_ids]
        payload.append(("cmd[confirmDeleteDelivered]", "Löschen"))
        confirm_resp = self.session.post(
            urljoin(self.settings.ilias_base_url + "/", form_action),
            data=payload,
            timeout=self.settings.timeout_seconds,
            allow_redirects=True,
        )
        confirm_resp.raise_for_status()

        # Step 2: deleteDelivered → actual deletion
        confirm_action = self._extract_submission_form_action(
            confirm_resp.text, ref_id, ass_id
        )
        delete_payload: list[tuple[str, str]] = [
            ("delivered[]", did) for did in delivery_ids
        ]
        delete_payload.append(("cmd[deleteDelivered]", "Löschen"))
        final_resp = self.session.post(
            urljoin(self.settings.ilias_base_url + "/", confirm_action),
            data=delete_payload,
            timeout=self.settings.timeout_seconds,
            allow_redirects=True,
        )
        final_resp.raise_for_status()

        remaining = self._extract_submitted_files(final_resp.text)
        return {
            "status": "deleted",
            "deleted_ids": delivery_ids,
            "remaining_count": len(remaining),
            "remaining": remaining,
        }

    def _extract_submission_form_action(
        self, html: str, ref_id: str, ass_id: str
    ) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for form in soup.find_all("form"):
            action = str(form.get("action", ""))
            if "ExSubmissionFileGUI" in action and "search" not in action.lower():
                return action
        raise IliasExerciseError(
            f"Submission form not found for ref_id={ref_id}, ass_id={ass_id}"
        )

    def _extract_submitted_files(self, html: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        files: list[dict[str, str]] = []
        for inp in soup.find_all("input", {"name": "delivered[]"}):
            delivery_id = str(inp.get("value", "")).strip()
            if not delivery_id:
                continue
            row = inp.find_parent("tr")
            name, date, submitter = "", "", ""
            if row:
                cells = row.find_all("td")
                texts = [c.get_text(strip=True) for c in cells]
                # typically: [checkbox, filename, submitter, date]
                if len(texts) >= 4:
                    name, submitter, date = texts[1], texts[2], texts[3]
                elif len(texts) == 3:
                    name, submitter, date = texts[0], texts[1], texts[2]
            files.append(
                {
                    "delivery_id": delivery_id,
                    "filename": name,
                    "submitter": submitter,
                    "date": date,
                }
            )
        return files

    def _submission_screen_url(self, ref_id: str, ass_id: str) -> str:
        assign_url = (
            f"{self.settings.ilias_base_url}/ilias.php"
            f"?baseClass=ilrepositorygui&cmdClass=ilAssignmentPresentationGUI"
            f"&cmd=showOverview&ref_id={ref_id}&ass_id={ass_id}&from_overview=1"
        )
        resp = self._get(assign_url, f"assignment page {ref_id}/{ass_id}")
        screen_raw = self._find_url_with_ass_id(
            resp.text,
            r"ilias\.php\?[^'\"]*cmdClass=ilExSubmissionFileGUI&cmd=submissionScreen[^'\"]*",
            ass_id,
        )
        if screen_raw:
            return urljoin(self.settings.ilias_base_url + "/", screen_raw)
        return (
            f"{self.settings.ilias_base_url}/ilias.php"
            f"?baseClass=ilrepositorygui&cmdClass=ilExSubmissionFileGUI"
            f"&cmd=submissionScreen&ref_id={ref_id}&ass_id={ass_id}"
        )

    # User search

    def search_users(self, ref_id: str, ass_id: str, term: str) -> list[dict[str, str]]:
        """Search ILIAS users by name fragment; returns login name + display label."""
        self.auth_service.ensure_logged_in()
        ac_url = self._autocomplete_url(ref_id, ass_id)
        resp = self._get(ac_url + f"&term={term}", "user autocomplete")
        try:
            data = resp.json()
        except Exception as exc:
            raise IliasExerciseError(
                f"Autocomplete response not JSON: {resp.text[:200]}"
            ) from exc
        results = []
        for item in data.get("items", {}).values():
            results.append(
                {
                    "login": str(item.get("value", "")),
                    "label": str(item.get("label", "")),
                    "user_id": str(item.get("id", "")),
                }
            )
        return results

    def _autocomplete_url(self, ref_id: str, ass_id: str) -> str:
        team_url = self._team_url(ref_id, ass_id)
        team_resp = self._get(team_url, f"team page {ref_id}/{ass_id}")
        m = re.search(
            r"ilias\.php\?[^'\"]*cmdClass=ilRepositorySearchGUI&cmd=doUserAutoComplete[^'\"]*",
            team_resp.text,
        )
        if m:
            return urljoin(self.settings.ilias_base_url + "/", m.group(0))
        # Fallback using known pattern
        return (
            f"{self.settings.ilias_base_url}/ilias.php"
            f"?baseClass=ilrepositorygui&cmdClass=ilRepositorySearchGUI"
            f"&cmd=doUserAutoComplete&ref_id={ref_id}&ass_id={ass_id}"
        )

    # Team management

    def list_team_members(self, ref_id: str, ass_id: str) -> list[TeamMember]:
        self.auth_service.ensure_logged_in()
        url = self._team_url(ref_id, ass_id)
        resp = self._get(url, f"team screen {ref_id}/{ass_id}")
        return self._extract_team_members(resp.text)

    def add_team_member(
        self, ref_id: str, ass_id: str, username: str
    ) -> dict[str, str]:
        self.auth_service.ensure_logged_in()
        team_url = self._team_url(ref_id, ass_id)
        page_resp = self._get(team_url, f"team page {ref_id}/{ass_id}")
        post_url, rtoken = self._team_post_url_and_rtoken(
            page_resp.text, ref_id, ass_id
        )

        payload = {
            "user_login": username,
            "cmd[addUserFromAutoComplete]": "Hinzufügen",
            "rtoken": rtoken,
        }
        resp = self.session.post(
            urljoin(self.settings.ilias_base_url + "/", post_url),
            data=payload,
            timeout=self.settings.timeout_seconds,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Verify the member now appears on the team page
        updated_members = self._extract_team_members(resp.text)
        names = [m.name for m in updated_members]
        return {
            "status": "ok",
            "username_added": username,
            "current_team": ", ".join(names) if names else "(no members listed)",
        }

    def remove_team_member(
        self, ref_id: str, ass_id: str, user_id: str
    ) -> dict[str, str]:
        self.auth_service.ensure_logged_in()
        team_url = self._team_url(ref_id, ass_id)
        page_resp = self._get(team_url, f"team page {ref_id}/{ass_id}")
        post_url, rtoken = self._team_post_url_and_rtoken(
            page_resp.text, ref_id, ass_id
        )

        payload = {
            "id[]": user_id,
            "cmd[confirmRemoveTeamMember]": "Entfernen",
            "rtoken": rtoken,
        }
        resp = self.session.post(
            urljoin(self.settings.ilias_base_url + "/", post_url),
            data=payload,
            timeout=self.settings.timeout_seconds,
            allow_redirects=True,
        )
        resp.raise_for_status()

        updated_members = self._extract_team_members(resp.text)
        names = [m.name for m in updated_members]
        return {
            "status": "ok",
            "user_id_removed": user_id,
            "current_team": ", ".join(names) if names else "(no members listed)",
        }

    def _extract_team_members(self, html: str) -> list[TeamMember]:
        soup = BeautifulSoup(html, "html.parser")
        members: list[TeamMember] = []
        for inp in soup.find_all("input", {"name": "id[]"}):
            user_id = str(inp.get("value", "")).strip()
            if not user_id:
                continue
            name = ""
            # Name is in the next <td> sibling of the checkbox cell
            td = inp.find_parent("td")
            if td:
                next_td = td.find_next_sibling("td")
                if next_td:
                    name = " ".join(next_td.get_text(" ", strip=True).split())
            if not name:
                row = inp.find_parent(["tr", "li", "div"])
                if row:
                    name = " ".join(row.get_text(" ", strip=True).split())
                    name = re.sub(r"\s*Entfernen\s*", "", name).strip()
            members.append(TeamMember(user_id=user_id, name=name))
        return members

    def _team_post_url_and_rtoken(
        self, html: str, ref_id: str, ass_id: str
    ) -> tuple[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        for form in soup.find_all("form"):
            action = str(form.get("action", ""))
            if "TeamGUI" in action or "addUserFromAutoComplete" in str(form):
                rtoken = self._extract_rtoken(action)
                return action, rtoken
        raise IliasExerciseError(
            f"Team form not found for ref_id={ref_id}, ass_id={ass_id}"
        )

    # Helpers

    def _overview_url(self, ref_id: str) -> str:
        return (
            f"{self.settings.ilias_base_url}/ilias.php"
            f"?baseClass=ilrepositorygui&cmdClass=ilObjExerciseGUI"
            f"&cmd=showOverview&ref_id={ref_id}"
        )

    def _upload_form_url(self, ref_id: str, ass_id: str) -> str:
        # Navigate via assignment overview → submission screen → upload form
        # to discover the dynamic cmdNode at each step.
        assign_url = (
            f"{self.settings.ilias_base_url}/ilias.php"
            f"?baseClass=ilrepositorygui&cmdClass=ilAssignmentPresentationGUI"
            f"&cmd=showOverview&ref_id={ref_id}&ass_id={ass_id}&from_overview=1"
        )
        assign_resp = self._get(assign_url, f"assignment page {ref_id}/{ass_id}")

        # Find submission screen URL matching the correct ass_id (the page may
        # contain links to other assignments' screens — pick the right one).
        screen_raw = self._find_url_with_ass_id(
            assign_resp.text,
            r"ilias\.php\?[^'\"]*cmdClass=ilExSubmissionFileGUI&cmd=submissionScreen[^'\"]*",
            ass_id,
        )
        if not screen_raw:
            raise IliasExerciseError(
                f"Could not find submissionScreen URL for ref_id={ref_id}, ass_id={ass_id}"
            )
        screen_url = urljoin(self.settings.ilias_base_url + "/", screen_raw)
        screen_resp = self._get(screen_url, f"submission screen {ref_id}/{ass_id}")

        m2 = re.search(
            r"ilias\.php\?[^'\"]*cmdClass=ilExSubmissionFileGUI&cmd=uploadForm[^'\"]*",
            screen_resp.text,
        )
        if m2:
            return urljoin(self.settings.ilias_base_url + "/", m2.group(0))
        # Fallback: replace cmd in the screen URL
        return screen_url.replace("cmd=submissionScreen", "cmd=uploadForm")

    def _team_url(self, ref_id: str, ass_id: str) -> str:
        # Load assignment presentation to discover the dynamic cmdNode for TeamGUI
        assign_url = (
            f"{self.settings.ilias_base_url}/ilias.php"
            f"?baseClass=ilrepositorygui&cmdClass=ilAssignmentPresentationGUI"
            f"&cmd=showOverview&ref_id={ref_id}&ass_id={ass_id}&from_overview=1"
        )
        resp = self._get(assign_url, f"assignment page {ref_id}/{ass_id}")
        team_raw = self._find_url_with_ass_id(
            resp.text,
            r"ilias\.php\?[^'\"]*cmdClass=ilExSubmissionTeamGUI&cmd=submissionScreenTeam[^'\"]*",
            ass_id,
        )
        if team_raw:
            return urljoin(self.settings.ilias_base_url + "/", team_raw)
        return (
            f"{self.settings.ilias_base_url}/ilias.php"
            f"?baseClass=ilrepositorygui&cmdClass=ilExSubmissionTeamGUI"
            f"&cmd=submissionScreenTeam&ref_id={ref_id}&ass_id={ass_id}"
        )

    @staticmethod
    def _find_url_with_ass_id(html: str, pattern: str, ass_id: str) -> str:
        """Return first regex match with the requested ass_id, else first match."""
        matches = [unescape(match) for match in re.findall(pattern, html)]
        for url in matches:
            qs = parse_qs(urlparse(url).query)
            if qs.get("ass_id", [""])[0] == ass_id:
                return url
        return matches[0] if matches else ""

    @staticmethod
    def _extract_rtoken(url: str) -> str:
        qs = parse_qs(urlparse(url).query)
        return qs.get("rtoken", [""])[0]

    def _get(self, url: str, label: str) -> requests.Response:
        try:
            resp = self.session.get(url, timeout=self.settings.timeout_seconds)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise IliasExerciseError(f"Failed to fetch {label}: {exc}") from exc
