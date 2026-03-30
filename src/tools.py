"""MCP tool definitions for x-bookmarks-mcp.

Eight tools exposing search, browse, annotate, and summarize
capabilities over the local bookmark database.
"""

import logging

from src.db import Database

logger = logging.getLogger(__name__)


def _full_bookmark(db: Database, bookmark_id: str) -> dict | None:
    """Return a bookmark with its links and tags attached, or None."""
    bm = db.get_bookmark(bookmark_id)
    if bm is None:
        return None
    bm["tags"] = db.get_tags(bookmark_id)
    bm["links"] = db.get_links(bookmark_id)
    return bm


# --- Tool 1: search_bookmarks ---


def search_bookmarks(
    db: Database,
    query: str,
    tag: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Full-text search across tweet_text, thread_text, page_content, notes, and tags.

    Returns ranked results with snippets.
    """
    return db.search(query, tag, limit)


# --- Tool 2: list_tags ---


def list_tags(db: Database) -> list[dict]:
    """All tags with bookmark counts."""
    return db.list_all_tags()


# --- Tool 3: get_bookmark ---


def get_bookmark(db: Database, bookmark_id: str) -> dict:
    """Full bookmark + all linked content + tags + notes.

    Returns error dict if not found.
    """
    result = _full_bookmark(db, bookmark_id)
    if result is None:
        return {"error": f"Bookmark '{bookmark_id}' not found"}
    return result


# --- Tool 4: browse_by_tag ---


def browse_by_tag(db: Database, tag: str, limit: int = 20) -> list[dict]:
    """Bookmarks under a tag, newest first."""
    return db.browse_by_tag(tag, limit)


# --- Tool 5: add_note ---


def add_note(db: Database, bookmark_id: str, note: str) -> dict:
    """Add/update user note. Returns updated bookmark."""
    bm = db.get_bookmark(bookmark_id)
    if bm is None:
        return {"error": f"Bookmark '{bookmark_id}' not found"}
    db.update_notes(bookmark_id, note)
    return _full_bookmark(db, bookmark_id)


# --- Tool 6: add_tag ---


def add_tag(db: Database, bookmark_id: str, tag: str) -> dict:
    """Add tag (idempotent). Returns updated bookmark."""
    bm = db.get_bookmark(bookmark_id)
    if bm is None:
        return {"error": f"Bookmark '{bookmark_id}' not found"}
    db.add_tag(bookmark_id, tag)
    return _full_bookmark(db, bookmark_id)


# --- Tool 7: get_stats ---


def get_stats(db: Database) -> dict:
    """Collection overview: counts, tags, authors, enrichment status."""
    return db.get_stats()


# --- Tool 8: summarize_topic ---


def summarize_topic(
    db: Database,
    query_or_tag: str,
    detail_level: str = "detailed",
) -> dict:
    """Gather bookmarks matching a tag or search query, structured for Claude to synthesize.

    detail_level:
        "brief"    - tweet texts and titles only
        "detailed" - tweet texts + enriched content snippets
        "guide"    - full enriched content
    """
    if detail_level not in ("brief", "detailed", "guide"):
        return {
            "error": f"Invalid detail_level '{detail_level}'. Use: brief, detailed, guide"
        }

    # Try tag-based browse first, fall back to search
    tags = db.list_all_tags()
    tag_names = {t["tag"] for t in tags}

    if query_or_tag in tag_names:
        rows = db.browse_by_tag(query_or_tag, limit=100)
    else:
        rows = db.search(query_or_tag, tag=None, limit=100)

    if not rows:
        return {
            "query": query_or_tag,
            "detail_level": detail_level,
            "count": 0,
            "bookmarks": [],
        }

    bookmarks = []
    for row in rows:
        bid = row["id"]
        entry: dict = {
            "id": bid,
            "author": row.get("author_username", ""),
            "tweet_text": row.get("tweet_text", ""),
            "url": row.get("tweet_url", ""),
        }

        if detail_level == "brief":
            # Add link titles only
            links = db.get_links(bid)
            entry["link_titles"] = [
                lnk["page_title"] for lnk in links if lnk.get("page_title")
            ]
        elif detail_level == "detailed":
            # Add truncated content snippets
            links = db.get_links(bid)
            entry["links"] = [
                {
                    "title": lnk.get("page_title", ""),
                    "content_snippet": (lnk.get("page_content") or "")[:500],
                    "content_type": lnk.get("content_type", "article"),
                }
                for lnk in links
                if lnk.get("page_title") or lnk.get("page_content")
            ]
            bm_full = db.get_bookmark(bid)
            if bm_full and bm_full.get("thread_text"):
                entry["thread_text"] = bm_full["thread_text"][:1000]
        else:
            # "guide" — full content
            full = _full_bookmark(db, bid)
            if full:
                if full.get("thread_text"):
                    entry["thread_text"] = full["thread_text"]
                if full.get("notes"):
                    entry["notes"] = full["notes"]
                entry["links"] = [
                    {
                        "title": lnk.get("page_title", ""),
                        "content": lnk.get("page_content", ""),
                        "content_type": lnk.get("content_type", "article"),
                        "url": lnk.get("original_url", ""),
                    }
                    for lnk in full.get("links", [])
                ]

        bookmarks.append(entry)

    return {
        "query": query_or_tag,
        "detail_level": detail_level,
        "count": len(bookmarks),
        "bookmarks": bookmarks,
    }
