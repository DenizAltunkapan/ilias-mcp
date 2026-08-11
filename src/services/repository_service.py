from __future__ import annotations

import re
from email.message import Message
from io import BytesIO
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader

from core.config import Settings
from domain.models import DownloadedFile, FileContent, RepositoryItem
from services.auth_service import AuthService


class IliasRepositoryError(RuntimeError):
    pass


class RepositoryService:
    CONTAINER_TYPES: ClassVar[set[str]] = {
        "category",
        "course",
        "exercise",
        "folder",
        "group",
        "root",
        "item",
    }

    def __init__(
        self, settings: Settings, session: requests.Session, auth_service: AuthService
    ) -> None:
        self.settings = settings
        self.session = session
        self.auth_service = auth_service

    def list_items(self, ref_id: str) -> list[RepositoryItem]:
        self.auth_service.ensure_logged_in()
        resp = self._get(self._repository_url(ref_id), f"repository page {ref_id}")
        return self._extract_items(resp.text, current_ref_id=ref_id)

    def walk(
        self,
        ref_id: str,
        max_depth: int = 8,
        include_unknown_containers: bool = True,
    ) -> list[dict[str, object]]:
        """Return a flat, depth-first repository listing below a ref_id."""
        self.auth_service.ensure_logged_in()
        max_depth = max(0, min(max_depth, 25))
        results: list[dict[str, object]] = []
        visited: set[str] = set()
        self._walk(
            ref_id=ref_id,
            path=[],
            depth=0,
            max_depth=max_depth,
            visited=visited,
            results=results,
            include_unknown_containers=include_unknown_containers,
        )
        return results

    def fetch_file_content(
        self, ref_id: str, max_chars: int = 20000, max_pdf_pages: int = 20
    ) -> FileContent:
        self.auth_service.ensure_logged_in()

        details = self.get_item_details(ref_id)
        file_url = details.get("file_url") or details.get("url")
        title = details.get("title") or f"file-{ref_id}"
        if not file_url:
            raise IliasRepositoryError(f"No file URL found for ref_id={ref_id}.")

        resp = self._download_response(file_url, ref_id)
        content_type = (resp.headers.get("Content-Type") or "").lower()
        payload = resp.content

        if "pdf" in content_type or self._looks_like_pdf(payload):
            text = self._extract_pdf_text(payload, max_pdf_pages=max_pdf_pages)
            return FileContent(
                ref_id=ref_id,
                title=title,
                file_url=resp.url,
                content_type=content_type or "application/pdf",
                text=text[:max_chars],
                parsed_with="pypdf",
            )

        text = resp.text
        return FileContent(
            ref_id=ref_id,
            title=title,
            file_url=resp.url,
            content_type=content_type or "text/plain",
            text=text[:max_chars],
            parsed_with="requests-text",
        )

    def download_files(
        self,
        ref_id: str,
        output_dir: str | None = None,
        extensions: list[str] | None = None,
        max_depth: int = 8,
        overwrite: bool = False,
    ) -> list[DownloadedFile]:
        """Recursively download matching files below ref_id, preserving ILIAS folders."""
        self.auth_service.ensure_logged_in()
        root = Path(output_dir or self.settings.download_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        allowed = self._normalize_extensions(extensions or ["pdf"])

        root_details = self.get_item_details(ref_id)
        file_url = root_details.get("file_url", "")
        # Folder pages can expose download links for contained files.
        if file_url and self._extract_ref_id(file_url) == ref_id:
            file = self.download_file(
                ref_id=ref_id,
                output_dir=str(root),
                overwrite=overwrite,
            )
            if allowed and self._file_extension(file.local_path) not in allowed:
                return []
            return [file]

        downloaded: list[DownloadedFile] = []
        for entry in self.walk(ref_id=ref_id, max_depth=max_depth):
            if entry.get("type") != "file":
                continue
            item_ref_id = str(entry["ref_id"])
            details = self.get_item_details(item_ref_id)
            file_url = str(details.get("file_url") or entry.get("url") or "")
            if not file_url:
                continue

            resp = self._download_response(file_url, item_ref_id)
            filename = self._filename_from_response(resp, str(entry["title"]))
            if allowed and self._file_extension(filename) not in allowed:
                continue

            relative_parts = [
                self._safe_path_part(part) for part in entry.get("path", [])[:-1]
            ]
            target_dir = root.joinpath(*relative_parts)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / self._safe_path_part(filename)

            if target.exists() and not overwrite:
                downloaded.append(
                    DownloadedFile(
                        ref_id=item_ref_id,
                        title=str(entry["title"]),
                        file_url=resp.url,
                        local_path=str(target),
                        content_type=resp.headers.get("Content-Type", ""),
                        size_bytes=target.stat().st_size,
                        status="skipped",
                    )
                )
                continue

            target.write_bytes(resp.content)
            downloaded.append(
                DownloadedFile(
                    ref_id=item_ref_id,
                    title=str(entry["title"]),
                    file_url=resp.url,
                    local_path=str(target),
                    content_type=resp.headers.get("Content-Type", ""),
                    size_bytes=target.stat().st_size,
                    status="downloaded",
                )
            )

        return downloaded

    def download_file(
        self,
        ref_id: str,
        output_dir: str | None = None,
        filename: str = "",
        overwrite: bool = False,
    ) -> DownloadedFile:
        """Download a single ILIAS file object by ref_id."""
        self.auth_service.ensure_logged_in()
        root = Path(output_dir or self.settings.download_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)

        details = self.get_item_details(ref_id)
        file_url = str(details.get("file_url") or "")
        if not file_url:
            raise IliasRepositoryError(f"No file URL found for ref_id={ref_id}.")

        resp = self._download_response(file_url, ref_id)
        raw_name = filename.strip() or self._filename_from_response(
            resp, str(details.get("title") or f"ilias-file-{ref_id}")
        )
        target = root / self._safe_path_part(raw_name)

        if target.exists() and not overwrite:
            return DownloadedFile(
                ref_id=ref_id,
                title=str(details.get("title") or raw_name),
                file_url=resp.url,
                local_path=str(target),
                content_type=resp.headers.get("Content-Type", ""),
                size_bytes=target.stat().st_size,
                status="skipped",
            )

        target.write_bytes(resp.content)
        return DownloadedFile(
            ref_id=ref_id,
            title=str(details.get("title") or raw_name),
            file_url=resp.url,
            local_path=str(target),
            content_type=resp.headers.get("Content-Type", ""),
            size_bytes=target.stat().st_size,
            status="downloaded",
        )

    def get_item_details(self, ref_id: str) -> dict[str, str]:
        self.auth_service.ensure_logged_in()
        url = self._repository_url(ref_id)
        resp = self._get(url, f"item page {ref_id}")
        soup = BeautifulSoup(resp.text, "html.parser")
        title_node = (
            soup.select_one("h1")
            or soup.select_one(".ilHeader h1")
            or soup.select_one("title")
        )
        title = self._clean(title_node.get_text(" ", strip=True)) if title_node else ""

        file_url = self._detect_file_url(soup, ref_id)
        if (
            not file_url
            and self._page_looks_like_file_object(soup, ref_id)
            # A container page also links to ilObjFileGUI (for its children), so
            # only guess at a download URL when the page lists no child items.
            and not self._extract_items(resp.text, current_ref_id=ref_id)
        ):
            file_url = self._permanent_file_download_url(ref_id)

        return {
            "ref_id": ref_id,
            "title": title,
            "url": url,
            "file_url": file_url,
        }

    def _walk(
        self,
        ref_id: str,
        path: list[str],
        depth: int,
        max_depth: int,
        visited: set[str],
        results: list[dict[str, object]],
        include_unknown_containers: bool,
    ) -> None:
        if depth > max_depth or ref_id in visited:
            return
        visited.add(ref_id)

        for item in self.list_items(ref_id):
            item_path = [*path, item.title]
            row = {
                "title": item.title,
                "type": item.item_type,
                "url": item.url,
                "ref_id": item.ref_id,
                "depth": depth,
                "path": item_path,
            }
            results.append(row)

            should_recurse = item.item_type in self.CONTAINER_TYPES
            if item.item_type == "item":
                should_recurse = include_unknown_containers
            if should_recurse and item.ref_id not in visited:
                self._walk(
                    ref_id=item.ref_id,
                    path=item_path,
                    depth=depth + 1,
                    max_depth=max_depth,
                    visited=visited,
                    results=results,
                    include_unknown_containers=include_unknown_containers,
                )

    def _extract_items(
        self, html: str, current_ref_id: str = ""
    ) -> list[RepositoryItem]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[RepositoryItem] = []

        # Avoid sidebar and breadcrumb links outside the repository content.
        content_scope: BeautifulSoup | Tag = (
            soup.select_one("#ilContentContainer")
            or soup.select_one("#il_center_col")
            or soup.select_one(".ilContainerContent")
            or soup.select_one("#mainscrolldiv")
            or soup
        )

        containers = content_scope.select(
            ".ilObjListRow, .il_ContainerListItem, li.il-std-item, "
            "li.il-std-item-container, li.ilContainerListItemOuter, div.il-item, tr"
        )
        for container in containers:
            item = self._item_from_container(container, current_ref_id)
            if item:
                items.append(item)

        if not items:
            for link in content_scope.find_all(["a", "button"], href=True):
                item = self._item_from_linkish(link, current_ref_id)
                if item:
                    items.append(item)
            for button in content_scope.find_all(
                ["button", "a"], attrs={"data-action": True}
            ):
                item = self._item_from_linkish(button, current_ref_id)
                if item:
                    items.append(item)

        dedup: dict[str, RepositoryItem] = {}
        for item in items:
            key = item.ref_id or item.url
            if key and key != current_ref_id and item.title:
                dedup[key] = item

        return list(dedup.values())

    def _item_from_container(
        self, container: Tag, current_ref_id: str
    ) -> RepositoryItem | None:
        candidates = container.find_all(["a", "button"], href=True)
        candidates += container.find_all(["a", "button"], attrs={"data-action": True})
        for node in candidates:
            item = self._item_from_linkish(node, current_ref_id, container)
            if item:
                return item
        return None

    def _item_from_linkish(
        self, node: Tag, current_ref_id: str, container: Tag | None = None
    ) -> RepositoryItem | None:
        href = str(node.get("href") or node.get("data-action") or "").strip()
        if not self._is_repository_href(href):
            return None

        url = self._normalize_url(href)
        ref_id = self._extract_ref_id(url)
        if not ref_id or ref_id == current_ref_id:
            return None

        container = container or node.find_parent(["li", "div", "tr"])
        title = self._title_for_node(node, container)
        if len(title) < 2:
            return None

        icon_alt = ""
        if container:
            icon = container.find("img", alt=True)
            icon_alt = self._clean(icon.get("alt", "")) if icon else ""
        item_type = self._guess_item_type(url, icon_alt, title)

        return RepositoryItem(title=title, item_type=item_type, url=url, ref_id=ref_id)

    def _detect_file_url(self, soup: BeautifulSoup, ref_id: str) -> str:
        # A container page also lists download links for the files it contains,
        # so a match is only this object's download URL when the ref_id agrees.
        # Otherwise download_file(<folder>) would return the first child file.
        def matches(href: str) -> bool:
            if not self._is_download_href(href):
                return False
            return self._extract_ref_id(self._normalize_url(href)) == ref_id

        for link in soup.find_all(["a", "button"], href=True):
            href = str(link.get("href", "")).strip()
            if matches(href):
                return self._normalize_url(href)
        for node in soup.find_all(["a", "button"], attrs={"data-action": True}):
            href = str(node.get("data-action", "")).strip()
            if matches(href):
                return self._normalize_url(href)
        return ""

    def _page_looks_like_file_object(self, soup: BeautifulSoup, ref_id: str) -> bool:
        needles = (
            "ilobjfilegui",
            f"file_{ref_id}",
            f"/go/file/{ref_id}",
            "icon_file",
            "obj_file",
        )
        for node in soup.find_all(["a", "button", "img"], href=True):
            haystack = " ".join(
                str(node.get(attr, "")) for attr in ("href", "title", "alt")
            )
            if any(needle in haystack.lower() for needle in needles):
                return True
        for node in soup.find_all(["a", "button"], attrs={"data-action": True}):
            haystack = str(node.get("data-action", "")).lower()
            if any(needle in haystack for needle in needles):
                return True
        return False

    def _download_response(self, file_url: str, ref_id: str) -> requests.Response:
        candidates = [file_url]
        permanent = self._permanent_file_download_url(ref_id)
        if permanent not in candidates:
            candidates.append(permanent)
        fallback = self._sendfile_url(ref_id)
        if fallback not in candidates:
            candidates.append(fallback)

        last_error: Exception | None = None
        for url in candidates:
            try:
                resp = self.auth_service.get(url, allow_redirects=True)
            except requests.RequestException as exc:
                last_error = exc
                continue
            if not self._looks_like_html_page(resp):
                return resp
            last_error = IliasRepositoryError(
                f"{url} served an ILIAS page rather than a file download "
                f"(ref_id={ref_id} is probably a folder/course, not a file)"
            )

        raise IliasRepositoryError(
            f"Failed to download file for ref_id={ref_id}: {last_error}"
        )

    def _get(self, url: str, label: str) -> requests.Response:
        try:
            return self.auth_service.get(url)
        except requests.RequestException as exc:
            raise IliasRepositoryError(f"Failed to fetch {label}: {exc}") from exc

    def _repository_url(self, ref_id: str) -> str:
        return (
            f"{self.settings.ilias_base_url}/ilias.php?baseClass=ilrepositorygui"
            f"&cmd=view&ref_id={ref_id}"
        )

    def _permanent_file_download_url(self, ref_id: str) -> str:
        # ILIAS ilObjFileGUI::_goto supports file_<ref_id>_download.
        return f"{self.settings.ilias_base_url}/goto.php?target=file_{ref_id}_download"

    def _sendfile_url(self, ref_id: str) -> str:
        return (
            f"{self.settings.ilias_base_url}/ilias.php?baseClass=ilrepositorygui"
            f"&cmdClass=ilObjFileGUI&cmd=sendfile&ref_id={ref_id}"
        )

    def _normalize_url(self, maybe_url: str) -> str:
        maybe_url = maybe_url.strip()
        if not maybe_url:
            return ""
        if maybe_url.startswith("http"):
            return maybe_url
        return urljoin(f"{self.settings.ilias_base_url}/", maybe_url)

    @staticmethod
    def _extract_ref_id(url: str) -> str:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        ref = qs.get("ref_id", [""])[0]
        if ref:
            return ref

        target = qs.get("target", [""])[0]
        match = re.search(r"(?:file|fold|crs|grp|cat)_(\d+)", target)
        if match:
            return match.group(1)

        path = parsed.path.rstrip("/")
        match = re.search(r"/go/(?:file|fold|crs|grp|cat)/(\d+)", path)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def _is_repository_href(href: str) -> bool:
        lower = href.lower()
        if not href or href.startswith(("#", "javascript:")):
            return False
        return "ref_id=" in lower or "/go/" in lower or "goto.php?target=" in lower

    @staticmethod
    def _is_download_href(href: str) -> bool:
        lower = href.lower()
        return (
            "cmd=sendfile" in lower
            or "cmdclass=ilobjfilegui" in lower
            or re.search(r"target=file_\d+_download", lower) is not None
            or "/download" in lower
        )

    def _title_for_node(self, node: Tag, container: Tag | None) -> str:
        if container:
            title_node = (
                container.select_one(".il-item-title")
                or container.select_one(".il_ContainerItemTitle")
                or container.select_one("h4")
            )
            if title_node:
                title = self._clean(title_node.get_text(" ", strip=True))
                if title:
                    return title

        title = self._clean(node.get_text(" ", strip=True))
        if not title:
            title = self._clean(str(node.get("title") or node.get("aria-label") or ""))
        return title

    @staticmethod
    def _guess_item_type(url: str, icon_alt: str, title: str = "") -> str:
        text = f"{url} {icon_alt} {title}".lower()
        if "ilobjcoursegui" in text or "/go/crs/" in text or "kurs" in text:
            return "course"
        if "ilobjfoldergui" in text or "/go/fold/" in text or "ordner" in text:
            return "folder"
        if "ilobjfilegui" in text or "/go/file/" in text or "datei" in text:
            return "file"
        if "ilobjcategorygui" in text or "/go/cat/" in text or "kategorie" in text:
            return "category"
        if "ilobjgroupgui" in text or "/go/grp/" in text or "gruppe" in text:
            return "group"
        if "ilobjforumgui" in text or "forum" in text:
            return "forum"
        # Exercises drive the submission tools, so they deserve their own type
        # instead of the generic "item" bucket.
        if (
            "ilexercisehandlergui" in text
            or "ilobjexercisegui" in text
            or "/go/exc/" in text
        ):
            return "exercise"
        return "item"

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(text.split())

    @staticmethod
    def _looks_like_pdf(blob: bytes) -> bool:
        return blob[:5] == b"%PDF-"

    @classmethod
    def _looks_like_html_page(cls, resp: requests.Response) -> bool:
        # ILIAS serves every real file download with a Content-Disposition
        # filename, while its UI and error pages never set the header. Uploaded
        # .html files are therefore indistinguishable from error pages by
        # content type alone -- trust the header instead.
        disposition = resp.headers.get("Content-Disposition", "")
        if cls._filename_from_content_disposition(disposition):
            return False

        content_type = (resp.headers.get("Content-Type") or "").lower()
        head = resp.content[:200].lstrip().lower()
        return "text/html" in content_type or head.startswith(
            (b"<!doctype html", b"<html")
        )

    @staticmethod
    def _extract_pdf_text(payload: bytes, max_pdf_pages: int) -> str:
        reader = PdfReader(BytesIO(payload))
        parts: list[str] = []
        for page_idx, page in enumerate(reader.pages):
            if page_idx >= max_pdf_pages:
                break
            parts.append(page.extract_text() or "")
        return "\n\n".join(parts).strip()

    @staticmethod
    def _normalize_extensions(extensions: list[str]) -> set[str]:
        return {ext.lower().lstrip(".") for ext in extensions if ext.strip()}

    @staticmethod
    def _file_extension(filename: str) -> str:
        return Path(filename).suffix.lower().lstrip(".")

    @staticmethod
    def _safe_path_part(name: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().strip(".")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned[:160] or "untitled"

    def _filename_from_response(
        self, resp: requests.Response, fallback_title: str
    ) -> str:
        disposition = resp.headers.get("Content-Disposition", "")
        filename = self._filename_from_content_disposition(disposition)
        if filename:
            return self._fix_mojibake(filename)

        path_name = self._fix_mojibake(unquote(Path(urlparse(resp.url).path).name))
        if path_name and "." in path_name and path_name != "ilias.php":
            return path_name

        content_type = (resp.headers.get("Content-Type") or "").lower()
        extension = ""
        if "pdf" in content_type or self._looks_like_pdf(resp.content):
            extension = ".pdf"
        title = fallback_title.strip() or "ilias-file"
        if extension and not title.lower().endswith(extension):
            title = f"{title}{extension}"
        return title

    @staticmethod
    def _filename_from_content_disposition(disposition: str) -> str:
        if not disposition:
            return ""
        message = Message()
        message["Content-Disposition"] = disposition
        filename = message.get_filename()
        return unquote(filename) if filename else ""

    @staticmethod
    def _fix_mojibake(text: str) -> str:
        if not any(ord(ch) in (0xC2, 0xC3) for ch in text):
            return text
        try:
            fixed = text.encode("latin1").decode("utf-8")
        except UnicodeError:
            return text
        return fixed if fixed else text
