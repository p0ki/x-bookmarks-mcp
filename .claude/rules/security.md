---
paths:
  - "**/*.py"
  - "**/*.yaml"
  - "**/*.yml"
  - "**/*.json"
  - "**/*.env*"
  - "**/Dockerfile"
  - "**/docker-compose*"
---
# Security Rules

This project is privacy-first and 100% local. These rules are non-negotiable.

## Data Privacy

- NEVER add external API calls to X/Twitter, OpenAI, or any third-party service
- NEVER add telemetry, analytics, or phone-home behavior
- NEVER commit personal data, real bookmarks, or database files to git
- NEVER hardcode file paths — use environment variables or config files
- ALL user data stays in `data/` which is gitignored

## Dependencies

- Only add dependencies that are well-known, actively maintained, and open-source
- Prefer stdlib when possible (sqlite3, pathlib, logging, json)
- Pin dependency versions in `requirements.txt`
- No dependencies that require API keys or external accounts

## Database

- SQLite only — no external database servers
- Enable WAL mode for safe concurrent access
- Use parameterized queries — NEVER use f-strings for SQL

```python
# Good
cursor.execute("SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,))

# Bad — SQL injection risk
cursor.execute(f"SELECT * FROM bookmarks WHERE id = '{bookmark_id}'")
```

## URL Fetching

- Only fetch URLs that were explicitly in the user's bookmark export
- Respect rate limits — configurable delay between fetches
- Set reasonable timeouts (default 10 seconds)
- Set a User-Agent header identifying the tool
- Handle redirects but cap at 5 hops
- Truncate content at MAX_CONTENT_LENGTH to prevent memory issues

## Configuration

- Sensitive config in `.env` (gitignored)
- Default config in `.env.example` and `config.yaml.example` (committed)
- Never log sensitive configuration values

## Docker

- Use slim base images (`python:3.12-slim`)
- Don't run as root in container
- Mount data as volumes, never bake into image
