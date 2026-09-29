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

- Only fetch URLs present in the bookmark export or bookmark text
- Allow only HTTP(S) URLs
- Block loopback, private, link-local, multicast, reserved, and other non-public destinations
- Revalidate every redirect target before following it
- Respect rate limits — configurable delay between fetches
- Set reasonable timeouts (default 10 seconds)
- Set a User-Agent header identifying the tool
- Cap redirects at 5 hops
- Stream responses and enforce MAX_RESPONSE_BYTES before text extraction
- Truncate extracted text at MAX_CONTENT_LENGTH

## Configuration

- Sensitive config in `.env` (gitignored)
- Default config in `.env.example` and `config.yaml` (committed)
- Never log sensitive configuration values

## Docker

- Use slim base images (`python:3.12-slim`)
- Don't run as root in container
- Mount data as volumes, never bake into image
