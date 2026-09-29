# x-bookmarks-mcp

Local-first, privacy-focused MCP server that turns exported X/Twitter bookmarks into a searchable, enriched knowledge base for Claude Desktop, Claude Code, and other MCP clients.

The bookmark database, notes, tags, and search index stay local. Optional enrichment makes outbound requests to public links contained in the export so their readable text can be indexed.

[![CI](https://github.com/p0ki/x-bookmarks-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/p0ki/x-bookmarks-mcp/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Why I Built This

X bookmarks are easy to save and difficult to reuse. This project turns an exported bookmark collection into a local knowledge base that can be searched, tagged, annotated, enriched, and exposed through MCP.

The project is intentionally small: SQLite is the source of the local index, FTS5 provides search, Python handles import/enrichment, and the MCP server exposes a bounded tool surface.

## Highlights

- **Local-first storage** — SQLite database and bookmark data stay on your machine.
- **No X API dependency** — import from JSON exports instead of requiring X API credentials.
- **MCP integration** — eight tools for search, browsing, notes, tags, stats, and topic synthesis.
- **Full-text search** — tweet text, exported thread/article text, notes, tags, and enriched linked content.
- **Incremental imports** — unchanged bookmarks are skipped; changed exports update existing records.
- **X Article preservation** — if the exporter includes article title/body/URL, that content is stored locally as an `x-article` link.
- **Bounded enrichment** — public HTTP(S) links only, redirect validation, response-size limits, timeouts, and content extraction.
- **Docker + CI** — non-root container, linting, tests, coverage, dependency audit, secret scan, private-data scan, and Docker validation.

## Security Model

URL enrichment processes untrusted links, so the fetcher:

- accepts only `http://` and `https://`;
- rejects loopback, private, link-local, multicast, reserved, and other non-public IP destinations;
- validates redirect targets before following them;
- limits redirects to five hops;
- streams responses with a configurable hard byte limit;
- accepts text/HTML-style responses only;
- applies request timeouts and a descriptive User-Agent.

This is defense in depth for a local enrichment tool. Do not expose the MCP server or its data directory directly to the public Internet.

## Current Limits

- The project does **not** log into X or scrape authenticated X pages.
- Full X Article text is available only when the bookmark exporter includes that article content. A raw X Article URL by itself may not be enrichable without an authenticated browser/session.
- A bookmark marked as a reply can be identified as thread-related, but reconstructing an entire X conversation requires the exporter to include the conversation content.
- SQLite is intended for a personal/local collection, not multi-user hosted service use.

## Quick Start

### 1. Export bookmarks

Export X bookmarks to JSON and save the file under `data/exports/`, for example:

```text
data/exports/bookmarks.json
```

### 2. Install

```bash
git clone https://github.com/p0ki/x-bookmarks-mcp.git
cd x-bookmarks-mcp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Import and optionally enrich

```bash
python -m src import data/exports/bookmarks.json
python -m src enrich
python -m src stats
```

Re-running import is safe:

- new bookmark → added;
- changed bookmark/export metadata → updated;
- unchanged bookmark → skipped.

### 4. Run the MCP server

```bash
python -m src.server
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "xbookmarks": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/absolute/path/to/x-bookmarks-mcp"
    }
  }
}
```

## Docker

Build:

```bash
docker build -t xbookmarks-mcp .
```

Run the MCP server over stdio:

```bash
docker run --rm -i \
  -v "$PWD/data:/app/data" \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  xbookmarks-mcp
```

CLI through Docker Compose:

```bash
docker compose run --rm xbookmarks-cli import data/exports/bookmarks.json
docker compose run --rm xbookmarks-cli enrich
docker compose run --rm xbookmarks-cli stats
```

## How It Works

```text
bookmark export
      |
      v
  ingest.py
      |
      v
 SQLite + FTS5 <---- notes / tags
      |
      +---- optional public URL enrichment
      |
      v
 MCP server (stdio)
      |
      v
 Claude / MCP client
```

1. **Ingest** detects supported JSON formats and updates the local collection.
2. **Embedded article content** is preserved when the export contains it.
3. **Enrich** fetches bounded public linked-page content and extracts readable text.
4. **Tagger** applies configurable keyword rules.
5. **FTS5** indexes searchable fields; MCP writes rebuild the index immediately.
6. **MCP** exposes a small read/write tool contract.

## MCP Tools

| Tool | Description |
|---|---|
| `search_bookmarks` | Full-text search across bookmark content |
| `list_tags` | List tags with bookmark counts |
| `get_bookmark` | Get a bookmark with links, tags, and notes |
| `browse_by_tag` | Browse tagged bookmarks, newest first |
| `add_note` | Add or replace a local note |
| `add_tag` | Add an idempotent normalized tag |
| `get_stats` | Collection and enrichment statistics |
| `summarize_topic` | Gather bounded content for MCP-client synthesis |

## Configuration

| Variable | Default | Description |
|---|---:|---|
| `DB_PATH` | `./data/bookmarks.db` | SQLite database path |
| `CONFIG_PATH` | `./config.yaml` | Tag configuration |
| `FETCH_DELAY_SECONDS` | `1.0` | Delay between links for one bookmark |
| `FETCH_TIMEOUT_SECONDS` | `10` | HTTP timeout |
| `MAX_CONTENT_LENGTH` | `50000` | Maximum extracted text retained per link |
| `MAX_RESPONSE_BYTES` | `5000000` | Maximum downloaded response size |

Tag rules live in `config.yaml`.

## Development

```bash
pytest -v
pytest --cov=src --cov-fail-under=80 -v

ruff check src/ tests/
black --check src/ tests/
isort --check-only src/ tests/

python scripts/check_private_data.py
```

CI tests Python 3.11, 3.12, and 3.13 and also performs dependency, secret, privacy, Docker-image, and Docker-Compose checks.

## Dependency Policy

Runtime and development dependencies are pinned for reproducible CI/install behavior. The project intentionally remains on the supported MCP Python SDK **1.x** line until a deliberate MCP v2 migration is completed.

## License

[MIT](LICENSE)
