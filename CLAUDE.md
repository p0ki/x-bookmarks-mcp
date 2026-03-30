# CLAUDE.md

**x-bookmarks-mcp** — Fully local, privacy-first MCP server that turns your X bookmarks into a searchable, enriched knowledge base for Claude.

- 100% offline
- No X API keys
- No third-party services
- No telemetry
- All data stays in `./data/bookmarks.db`

Full architecture, schema, and future roadmap: `docs/plans/x-bookmarks-mcp-design.md`

## Tech Stack

- Python 3.11+
- Official `mcp` SDK
- `trafilatura`, `httpx` (async), `pyyaml`, `sqlite3 + FTS5`
- CLI: Click
- Formatting/linting: black + isort + ruff

## Key Commands

```bash
python -m src import data/exports/bookmarks.json
python -m src enrich --refresh
python -m src stats
python -m src.server          # MCP server (auto-started by Claude Code / Cowork)
```

## Strict Implementation Order

1. `src/db.py`
2. `src/ingest.py`
3. `src/tagger.py`
4. `src/enrich.py`
5. `src/tools.py`
6. `src/server.py`
7. CLI + config + Docker
8. Tests + README

## Claude Ecosystem Integration (Critical)

You have full access to every skill, plugin, MCP, agent, and sub-agent in these directories. Use them aggressively when they add value:

- `D:\Projekti\everything-claude-code` <!-- noqa: private-data -->
- `D:\Projekti\awesome-claude-code-toolkit` <!-- noqa: private-data -->

Examples of allowed/encouraged usage:

- Compose this MCP with other MCP servers via multi-MCP agent patterns
- Use sub-agents for bookmark triage, advanced summarization, or topic synthesis
- Leverage any relevant skills/plugins from the toolkit for enrichment, tagging, or agentic workflows

Always respect the privacy-first rules in `.claude/rules/security-and-privacy.md` — no external calls, no data exfiltration.

## Rules

- Follow every file in `.claude/rules/` (they are auto-loaded by path)
- Never deviate from the 8-tool MCP contract defined in `mcp-tools.md`
- Reference the design doc before writing any new code

---

> You are the expert maintainer of this project. Keep it simple, local, and rock-solid.