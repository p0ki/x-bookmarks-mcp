---
paths:
  - "**/*.py"
  - "**/*.pyi"
---
# Python Coding Style

## Standards

- Follow PEP 8 conventions
- Use type annotations on ALL function signatures and return types
- Python 3.11+ — use modern syntax (match/case, `X | Y` unions, etc.)

## Formatting

- `black` for code formatting
- `isort` for import sorting
- `ruff` for linting

## Data Classes

Use `dataclasses` for all data structures:

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class Bookmark:
    id: str
    author_username: str
    tweet_text: str
    created_at: datetime
    tags: list[str] = field(default_factory=list)
    notes: str | None = None
```

## Error Handling

- Never let a single bad bookmark crash the pipeline
- Use specific exceptions, not bare `except:`
- Log warnings for skipped items with context (bookmark ID, URL)
- Return meaningful error messages from MCP tools

```python
# Good
try:
    content = fetch_url(url)
except httpx.HTTPError as e:
    logger.warning(f"Failed to fetch {url} for bookmark {bookmark_id}: {e}")
    return None

# Bad
try:
    content = fetch_url(url)
except:
    pass
```

## Async

- Use `async/await` for URL fetching in the enrichment pipeline
- MCP server tools can be sync (SQLite operations are fast)
- Use `httpx.AsyncClient` with connection pooling

## Imports

```python
# stdlib first
import sqlite3
from datetime import datetime
from pathlib import Path

# third-party
import httpx
import yaml
from mcp import Server
from trafilatura import extract

# local
from src.db import Database
from src.tagger import Tagger
```

## Logging

Use `logging` module, not print statements:

```python
import logging

logger = logging.getLogger(__name__)

logger.info(f"Ingesting {count} bookmarks from {filepath}")
logger.warning(f"Skipping bookmark {id}: malformed data")
logger.error(f"Database error: {e}")
```
