# ILIAS MCP

Production-oriented MCP server for ILIAS login, enrolled course listing, dashboard news, repository crawling, and file downloads.

## Tools

- [login](#login): authenticate against ILIAS
- [list_courses](#list_courses): list enrolled courses with title, URL, and ref ID
- [server_info](#server_info): show non-sensitive runtime config
- [list_calendar_events](#list_calendar_events): list agenda events for a day
- [list_dashboard_news](#list_dashboard_news): list personal dashboard news from ilPDNewsGUI
- [list_repository_items](#list_repository_items): list child objects below a ref ID
- [get_repository_item_details](#get_repository_item_details): fetch page details and detect download URLs
- [get_file_content](#get_file_content): download file content by ref ID; PDFs are parsed to text with pypdf
- [crawl_repository](#crawl_repository): recursively walk a course or folder and return a flat tree
- [download_file](#download_file): download one file object by ref ID
- [download_repository_files](#download_repository_files): recursively download matching files and preserve ILIAS folders

## Demo

![ILIAS MCP tools demo](assets/ilias-mcp-tools-demo.png)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edit `.env` and set your credentials.

Optional:

```bash
ILIAS_DOWNLOAD_DIR=~/Downloads/ilias-mcp
```

## Run

```bash
source .venv/bin/activate
ilias-mcp
```

## Notes

- Server keeps a session in memory while process is running.
- On process restart, login is re-established on demand.
- This server is intentionally read-only for safety.
- Downloads use the official ILIAS file routes used by the Stuttgart fork, including ilObjFileGUI sendfile and goto.php file download routes.
- Start with [list_courses](#list_courses), then call [crawl_repository](#crawl_repository) or [download_repository_files](#download_repository_files) with the course ref ID.
