# x-bookmarks-mcp

Shared instructions for coding agents (Codex, Claude Code).

## Purpose
Local-first, privacy-focused MCP server that turns exported X/Twitter bookmarks into a searchable, enriched knowledge base. The database, notes, tags and search index stay local; optional enrichment fetches public links contained in the export.

## Stack
Python 3.11+ (CI: 3.11, 3.12, 3.13), official `mcp` SDK 1.x, `trafilatura`, `httpx`, `pyyaml`, SQLite + FTS5, Click CLI. Code in `src/`, tests in `tests/`.

## Commands
- Install: `pip install -r requirements.txt`
- Test: `pytest --cov=src --cov-fail-under=80 -v`
- Lint: `ruff check src/ tests/`, `black --check src/ tests/`, `isort --check-only src/ tests/`
- Privacy check: `python scripts/check_private_data.py`
- Run: `python -m src import data/exports/bookmarks.json`, `python -m src enrich`, `python -m src stats`, `python -m src.server`

## Verify before done
- Tests (coverage at least 80%), the three linters and the privacy check pass, as in CI (`.github/workflows/ci.yml`).

## Boundaries
- Rules in `.claude/rules/` (coding style, MCP tool contract in `mcp-tools.md`, security, testing) apply to every agent.
- Keep the MCP tool contract stable; changing it is a deliberate, documented decision.
- Enrichment handles untrusted links: keep the SSRF protections described in `README.md` (public http/https only, redirect checks, byte and time limits).
- Stay on MCP SDK 1.x until a planned v2 migration.
- No personal data, bookmarks, local paths or secrets in the repo.
