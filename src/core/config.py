from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    ilias_user: str
    ilias_pass: str
    ilias_base_url: str
    ilias_client_id: str
    lang: str = "de"
    timeout_seconds: int = 20
    download_dir: str = str(Path.home() / "Downloads" / "ilias-mcp")

    @property
    def login_page(self) -> str:
        return (
            f"{self.ilias_base_url}/login.php?client_id={self.ilias_client_id}"
            f"&cmd=force_login&lang={self.lang}"
        )

    @property
    def dashboard_url(self) -> str:
        return (
            f"{self.ilias_base_url}/ilias.php?baseClass=ildashboardgui&cmd=show&view=2"
        )

    @property
    def memberships_url(self) -> str:
        return f"{self.ilias_base_url}/ilias.php?baseClass=ilmembershipoverviewgui"

    def calendar_url(self, seed: str) -> str:
        query = urlencode(
            {
                "baseClass": "ildashboardgui",
                "cmdNode": "ai:76:72",
                "cmdClass": "ilcalendarinboxgui",
                "seed": seed,
                "category_id": "0",
            }
        )
        return f"{self.ilias_base_url}/ilias.php?{query}"

    @property
    def dashboard_news_url(self) -> str:
        query = urlencode(
            {
                "baseClass": "ildashboardgui",
                "cmdNode": "ai:ve",
                "cmdClass": "ilPDNewsGUI",
            }
        )
        return f"{self.ilias_base_url}/ilias.php?{query}"


def load_settings() -> Settings:
    load_dotenv()

    ilias_user = os.getenv("ILIAS_USER", "").strip().strip('"')
    ilias_pass = os.getenv("ILIAS_PASS", "").strip().strip('"')
    ilias_base_url = (
        os.getenv("ILIAS_BASE_URL", "https://ilias3.uni-stuttgart.de")
        .strip()
        .rstrip("/")
    )
    ilias_client_id = os.getenv("ILIAS_CLIENT_ID", "Uni_Stuttgart").strip()
    lang = os.getenv("ILIAS_LANG", "de").strip() or "de"

    timeout_raw = os.getenv("ILIAS_TIMEOUT_SECONDS", "20").strip()
    try:
        timeout_seconds = max(5, int(timeout_raw))
    except ValueError:
        timeout_seconds = 20

    download_dir = (
        os.getenv("ILIAS_DOWNLOAD_DIR", str(Path.home() / "Downloads" / "ilias-mcp"))
        .strip()
        .strip('"')
    )

    if not ilias_user:
        raise ValueError("Missing ILIAS_USER in .env")
    if not ilias_pass:
        raise ValueError("Missing ILIAS_PASS in .env")

    return Settings(
        ilias_user=ilias_user,
        ilias_pass=ilias_pass,
        ilias_base_url=ilias_base_url,
        ilias_client_id=ilias_client_id,
        lang=lang,
        timeout_seconds=timeout_seconds,
        download_dir=download_dir,
    )
