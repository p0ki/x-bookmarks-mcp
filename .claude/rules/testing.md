---
paths:
  - "**/*.py"
  - "**/test_*.py"
  - "**/tests/**"
---
# Testing Rules

## Framework

- Use `pytest` for all tests
- Test files: `tests/test_<module>.py`
- Use fixtures in `tests/fixtures/` for sample data

## Test Data

- Use `tests/fixtures/sample_export.json` with 5-10 fake bookmarks
- NEVER use real user data in tests
- Sample bookmarks should cover: single tweets, threads, tweets with URLs, tweets with multiple URLs, tweets with no URLs
- Include edge cases: empty text, unicode, very long content, malformed URLs

## What to Test

### `db.py`
- Schema creation on fresh database
- Insert, upsert, and query operations
- FTS5 search returns ranked results
- Tag operations (add, list, filter)
- Notes CRUD
- WAL mode is enabled

### `ingest.py`
- Parse `twitter-web-exporter` JSON format
- Parse alternative export formats (simple JSON, CSV)
- Skip malformed entries with warning
- Detect and handle duplicate bookmark IDs (upsert)
- Format auto-detection

### `tagger.py`
- Keyword matching is case-insensitive
- Multiple tags can apply to one bookmark
- Custom rules from config.yaml are loaded
- Tags match across tweet_text, thread_text, and page_content

### `enrich.py`
- URL extraction from tweet entities
- Content extraction returns title + text
- Failed URLs are skipped gracefully
- Rate limiting delay is respected
- Content truncation at MAX_CONTENT_LENGTH

### `tools.py`
- Each MCP tool returns expected schema
- Search with no results returns empty list
- Invalid bookmark_id returns clear error
- `summarize_topic` respects detail_level parameter

## Test Pattern

```python
import pytest
from src.db import Database

@pytest.fixture
def db(tmp_path):
    """Fresh database for each test."""
    db_path = tmp_path / "test.db"
    return Database(str(db_path))

def test_insert_and_search(db):
    db.insert_bookmark(id="123", tweet_text="Setting up Claude Code MCP")
    results = db.search("Claude Code")
    assert len(results) == 1
    assert results[0]["id"] == "123"
```
