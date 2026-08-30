from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from core.config import Settings
from domain.models import NewsItem
from services.auth_service import AuthService


class IliasNewsError(RuntimeError):
    pass


class NewsService:
    def __init__(
        self, settings: Settings, session: requests.Session, auth_service: AuthService
    ) -> None:
        self.settings = settings
        self.session = session
        self.auth_service = auth_service

    def list_dashboard_news(self, limit: int = 30) -> list[NewsItem]:
        try:
            resp = self.auth_service.get(self.settings.dashboard_news_url)
        except requests.RequestException as exc:
            raise IliasNewsError(f"Failed to fetch dashboard news: {exc}") from exc

        return self._extract_news(resp.text)[: max(1, min(limit, 200))]

    def _extract_news(self, html: str) -> list[NewsItem]:
        soup = BeautifulSoup(html, "html.parser")
        items = self._extract_timeline_news(soup)
        if not items:
            items = self._extract_table_news(soup)
        return items

    def _extract_timeline_news(self, soup: BeautifulSoup) -> list[NewsItem]:
        items: list[NewsItem] = []
        for section in soup.select(".ilNewsTimelineContentSection"):
            title_node = section.select_one("h4.ilNewsTimelineTruncatedText, h4")
            title = (
                self._clean(title_node.get_text(" ", strip=True)) if title_node else ""
            )
            if not title:
                continue

            info_node = section.select_one(".ilNewsTimelineEditInfo")
            author = ""
            date_label = ""
            if info_node:
                info_text = self._clean(info_node.get_text(" ", strip=True))
                author, date_label = self._split_author_date(info_text)

            context_node = section.select_one(".ilNewsTimelineObjHead a[href]")
            context_title = ""
            context_url = ""
            ref_id = ""
            if context_node:
                context_title = self._clean(context_node.get_text(" ", strip=True))
                context_url = self._normalize_url(str(context_node.get("href", "")))
                ref_id = self._extract_ref_id(context_url)

            content_node = section.select_one(".dynamic-height-wrap")
            content = (
                self._clean(content_node.get_text(" ", strip=True))
                if content_node
                else ""
            )

            title_link = self._nearest_link(title_node)
            url = (
                self._normalize_url(str(title_link.get("href", "")))
                if title_link
                else context_url
            )
            items.append(
                NewsItem(
                    title=title,
                    content=content,
                    context_title=context_title,
                    context_url=context_url,
                    ref_id=ref_id,
                    author=author,
                    date_label=date_label,
                    url=url,
                )
            )
        return items

    def _extract_table_news(self, soup: BeautifulSoup) -> list[NewsItem]:
        items: list[NewsItem] = []
        for row in soup.select("td.il-news"):
            title_link = row.select_one("h4 a[href]")
            title = (
                self._clean(title_link.get_text(" ", strip=True)) if title_link else ""
            )
            if not title:
                continue

            context_link = row.select_one("h2 a[href]")
            context_title = (
                self._clean(context_link.get_text(" ", strip=True))
                if context_link
                else ""
            )
            context_url = (
                self._normalize_url(str(context_link.get("href", "")))
                if context_link
                else ""
            )

            content_node = row.select_one(".il-news-content")
            content = (
                self._clean(content_node.get_text(" ", strip=True))
                if content_node
                else ""
            )

            author = ""
            date_label = ""
            for info in row.select(".il_BlockInfo"):
                text = self._clean(info.get_text(" ", strip=True))
                lower = text.lower()
                if lower.startswith(("created", "erstellt", "angelegt")):
                    date_label = text.split(":", 1)[-1].strip()
                if lower.startswith(("author", "autor")):
                    author = text.split(":", 1)[-1].strip()

            url = self._normalize_url(str(title_link.get("href", "")))
            items.append(
                NewsItem(
                    title=title,
                    content=content,
                    context_title=context_title,
                    context_url=context_url,
                    ref_id=self._extract_ref_id(context_url or url),
                    author=author,
                    date_label=date_label,
                    url=url,
                )
            )
        return items

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
        if "_" in target:
            parts = target.split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                return parts[1]
        path = parsed.path.rstrip("/")
        match = re.search(r"/go/[a-z]+/(\d+)", path)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def _split_author_date(text: str) -> tuple[str, str]:
        parts = [part.strip() for part in text.split(" - ", 1)]
        if len(parts) == 2:
            return parts[0], parts[1]
        return "", text

    @staticmethod
    def _nearest_link(node: Tag | None) -> Tag | None:
        if node is None:
            return None
        if node.name == "a" and node.get("href"):
            return node
        link = node.find("a", href=True)
        return link if isinstance(link, Tag) else None

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(text.split())
