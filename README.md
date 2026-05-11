# ILIAS MCP

Production-oriented MCP server for ILIAS login and enrolled course listing.

## Tools

- `login`: authenticate against ILIAS
- `list_courses`: list enrolled courses (`title`, `url`, `ref_id`)
- `server_info`: non-sensitive runtime config
- `list_calendar_events`: list agenda events for a day (`seed` in `YYYY-MM-DD`)
- `list_dashboard_news`: list personal dashboard news from `ilPDNewsGUI`
- `list_repository_items`: list child objects below a `ref_id` (course/folder/file/forum)
- `get_repository_item_details`: fetch page details and detect download URL for an object
- `get_file_content`: download file by `ref_id`; PDFs are parsed to text (`pypdf`)
- `crawl_repository`: recursively walk a course/folder and return a flat tree (`path`, `type`, `ref_id`)
- `download_file`: download one file object by `ref_id`
- `download_repository_files`: recursively download matching files; defaults to PDFs and preserves ILIAS folders

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
- Downloads use the official ILIAS file routes used by the Stuttgart fork (`ilObjFileGUI` `sendfile` and `goto.php?target=file_<ref_id>_download`).
- Start with `list_courses`, then call `crawl_repository` or `download_repository_files` with the course `ref_id`.
