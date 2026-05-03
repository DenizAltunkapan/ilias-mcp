# ILIAS MCP

Production-oriented MCP server for ILIAS login and enrolled course listing.

## Tools

- `login`: authenticate against ILIAS
- `list_courses`: list enrolled courses (`title`, `url`, `ref_id`)
- `server_info`: non-sensitive runtime config
- `list_calendar_events`: list agenda events for a day (`seed` in `YYYY-MM-DD`)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edit `.env` and set your credentials.

## Run

```bash
source .venv/bin/activate
ilias-mcp
```

## Notes

- Server keeps a session in memory while process is running.
- On process restart, login is re-established on demand.
- This server is intentionally read-only for safety.
