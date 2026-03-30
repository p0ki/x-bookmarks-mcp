---
paths:
  - "src/tools.py"
  - "src/server.py"
  - "**/test_tools*.py"
---

# MCP Tools — Exact Specification (8 tools)

You **must** implement these tools exactly as specified. Parameter names, return types, and behavior must match for Claude Code / Cowork compatibility.

### 1. search_bookmarks

```python
search_bookmarks(query: str, tag: str | None = None, limit: int = 10) -> list[dict]
```

Full-text search across tweet_text, thread_text, page_content, notes, and tags. Returns ranked results with snippets.

### 2. list_tags

```python
list_tags() -> list[dict]
```

All tags with bookmark counts.

### 3. get_bookmark

```python
get_bookmark(bookmark_id: str) -> dict | None
```

Full bookmark + all linked content + tags + notes. Return clear error dict if not found.

### 4. browse_by_tag

```python
browse_by_tag(tag: str, limit: int = 20) -> list[dict]
```

Bookmarks under a tag, newest first.

### 5. add_note

```python
add_note(bookmark_id: str, note: str) -> dict
```

Add/update user note. Return updated bookmark.

### 6. add_tag

```python
add_tag(bookmark_id: str, tag: str) -> dict
```

Add tag (idempotent). Return updated bookmark.

### 7. get_stats

```python
get_stats() -> dict
```

Collection overview (counts, tags, authors, enrichment status, etc.).

### 8. summarize_topic

```python
summarize_topic(query_or_tag: str, detail_level: str = "detailed") -> dict
```

Gathers content optimized for Claude to synthesize. `detail_level` options: `"brief"`, `"detailed"`, `"guide"`.

## Rules

- All tools must be registered via the official `mcp` SDK decorators.
- Return clean JSON-serializable dicts (no raw objects).
- Use clear error messages for invalid IDs or missing data.
- Never add extra tools unless explicitly approved in a new design doc revision.