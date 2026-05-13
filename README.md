# x-bookmarks-mcp

Fully local, privacy-first MCP server that turns exported X/Twitter bookmarks into a searchable, enriched knowledge base for Claude Desktop and Claude Code.

This project explores how personal knowledge, local-first data, and MCP tooling can make AI assistants more useful without sending private bookmark data to third-party services.

[![CI](https://github.com/p0ki/x-bookmarks-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/p0ki/x-bookmarks-mcp/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Why I Built This

I save a lot of useful posts, threads, tools, and ideas on X, but bookmarks quickly become a black hole: easy to save, hard to find, and almost impossible to turn into something useful later.

I wanted a local system that could import my exported bookmarks, enrich linked content, tag topics automatically, and expose everything to Claude through MCP — while keeping the data private and under my control.

This project helped me practice MCP server design, local-first tooling, SQLite full-text search, Docker workflows, async enrichment, private data handling, and AI-assisted knowledge management.

## Portfolio Highlights

- **Local-first AI tooling:** no X API keys, no telemetry, no third-party bookmark database.
- **MCP integration:** exposes 8 tools for Claude Desktop / Claude Code to search, browse, tag, and summarize bookmarks.
- **Searchable knowledge base:** SQLite + FTS5 full-text search across bookmark text, thread text, notes, tags, and enriched URLs.
- **Async enrichment:** fetches linked pages and extracts readable content for better search and summarization.
- **Docker support:** can run locally or through Docker/Docker Compose.
- **Quality checks:** tests, coverage target, formatting/linting commands, and private data scanner.

## What it does

- **100% offline** — no X API keys, no third-party services, no telemetry
- **Full-text search** across tweet text, threads, linked page content, notes, and tags
- **Auto-enrichment** — fetches and extracts content from URLs in your bookmarks
- **MCP integration** — 8 tools available to Claude for searching, browsing, tagging, and summarizing

## Quick Start

### 1. Export your bookmarks

Use a browser extension like [twitter-web-exporter](https://github.com/prinsss/twitter-web-exporter) to export your X bookmarks as JSON.

Save the export to `data/exports/bookmarks.json`.

### 2. Install

```bash
git clone https://github.com/p0ki/x-bookmarks-mcp.git
cd x-bookmarks-mcp
pip install -r requirements.txt
```

### 3. Import and enrich

```bash
python -m src import data/exports/bookmarks.json
python -m src enrich
```

### 4. Connect to Claude

Add to your `claude_desktop_config.json`:

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

Replace `/absolute/path/to/x-bookmarks-mcp` with the full path to your clone.

## Installation

```bash
git clone https://github.com/p0ki/x-bookmarks-mcp.git
cd x-bookmarks-mcp
pip install -r requirements.txt
```

Requires Python 3.11 or higher. All dependencies are listed in `requirements.txt`.

## Usage

### CLI Commands

```bash
# Import bookmarks from JSON export
python -m src import data/exports/bookmarks.json

# Fetch and extract content from URLs in bookmarks
python -m src enrich

# Re-fetch already-enriched bookmarks
python -m src enrich --refresh

# Re-run auto-tagging on all bookmarks
python -m src retag

# Show collection statistics
python -m src stats

# Enable verbose logging
python -m src -v import data/exports/bookmarks.json
```

### MCP Server

```bash
python -m src.server
```

The server runs over stdio and is designed to be launched by Claude Desktop or Claude Code.

## Docker

### Build the image

```bash
docker build -t xbookmarks-mcp .
```

### Run MCP server via Docker

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "xbookmarks": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/absolute/path/to/xbookmarks/data:/app/data",
        "-v", "/absolute/path/to/xbookmarks/config.yaml:/app/config.yaml:ro",
        "xbookmarks-mcp"
      ]
    }
  }
}
```

Replace `/absolute/path/to/xbookmarks` with the full path to your local clone. Relative paths do not work here because Claude Desktop launches the container from its own working directory.

### CLI via Docker Compose

```bash
# Import bookmarks
docker compose run --rm xbookmarks-cli import data/exports/bookmarks.json

# Enrich bookmarks
docker compose run --rm xbookmarks-cli enrich

# Show stats
docker compose run --rm xbookmarks-cli stats
```

## How it works

```
bookmarks.json ──▶ ingest ──▶ SQLite DB
                                 │
                            enrich (async)
                            fetch URLs ──▶ extract content
                                 │
                            auto-tag (keyword rules)
                                 │
                         MCP server (stdio)
                                 │
                         Claude Desktop / Claude Code
```

1. **Ingest** — parses your JSON export, stores bookmarks in SQLite with FTS5 full-text search
2. **Enrich** — asynchronously fetches URLs from bookmarks, extracts readable content with trafilatura
3. **Auto-tag** — applies keyword-based rules from `config.yaml` to categorize bookmarks
4. **MCP Server** — exposes 8 tools over stdio for Claude to search, browse, and organize your bookmarks

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_bookmarks` | Full-text search across all bookmark content |
| `list_tags` | List all tags with bookmark counts |
| `get_bookmark` | Get a single bookmark with full detail |
| `browse_by_tag` | Browse bookmarks by tag, newest first |
| `add_note` | Add or update a personal note on a bookmark |
| `add_tag` | Add a tag to a bookmark (idempotent) |
| `get_stats` | Collection overview — counts, tags, authors, enrichment status |
| `summarize_topic` | Gather bookmarks on a topic for Claude to synthesize |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `./data/bookmarks.db` | Path to SQLite database |
| `CONFIG_PATH` | `./config.yaml` | Path to config file |
| `FETCH_DELAY_SECONDS` | `1.0` | Delay between URL fetches |
| `FETCH_TIMEOUT_SECONDS` | `10` | Timeout for URL fetches |
| `MAX_CONTENT_LENGTH` | `50000` | Maximum extracted content length |

### Tag Rules (config.yaml)

```yaml
tag_rules:
  claude-code:
    - "claude code"
    - "claude-code"
  mcp:
    - "mcp"
    - "model context protocol"
```

Bookmarks are automatically tagged when any keyword is found in the tweet text, thread text, or enriched page content.

## Development

```bash
# Clone
git clone https://github.com/p0ki/x-bookmarks-mcp.git
cd x-bookmarks-mcp

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest -v

# Run tests with coverage
pytest --cov=src --cov-fail-under=80 -v

# Lint
ruff check src/ tests/
black --check src/ tests/
isort --check-only src/ tests/

# Run private data scanner
python scripts/check_private_data.py
```

## License

[MIT](LICENSE)
