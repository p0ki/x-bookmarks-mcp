"""MCP tool definitions for x-bookmarks-mcp.

Eight tools exposing search, browse, annotate, and summarize
capabilities over the local bookmark database.
"""

import logging

from src.db import Database

logger = logging.getLogger(__name__)


def _full_bookmark(db: Database, bookmark_id: str) -> dict | None:
    bm = db.get_bookmark(bookmark_id)
    if bm is None:
        return None
    bm["tags"] = db.get_tags(bookmark_id)
    bm["links"] = db.get_links(bookmark_id)
    return bm


def search_bookmarks(
    db: Database,
    query: str,
    tag: str | None = None,
    limit: int = 10,
) -> list[dict]:
    if not query.strip():
        return []
    limit = max(1, min(limit, 100))
    return db.search(query, tag, limit)


def list_tags(db: Database) -> list[dict]:
    return db.list_all_tags()


def get_bookmark(db: Database, bookmark_id: str) -> dict:
    result = _full_bookmark(db, bookmark_id)
    if result is None:
        return {"error": f"Bookmark '{bookmark_id}' not found"}
    return result


def browse_by_tag(db: Database, tag: str, limit: int = 20) -> list[dict]:
    limit = max(1, min(limit, 100))
    return db.browse_by_tag(tag, limit)


def add_note(db: Database, bookmark_id: str, note: str) -> dict:
    bm = db.get_bookmark(bookmark_id)
    if bm is None:
        return {"error": f"Bookmark '{bookmark_id}' not found"}
    db.update_notes(bookmark_id, note[:10_000])
    db.rebuild_fts()
    return _full_bookmark(db, bookmark_id)


def add_tag(db: Database, bookmark_id: str, tag: str) -> dict:
    bm = db.get_bookmark(bookmark_id)
    if bm is None:
        return {"error": f"Bookmark '{bookmark_id}' not found"}

    normalized = tag.strip().lower()
    if not normalized:
        return {"error": "Tag must not be empty"}
    if len(normalized) > 100:
        return {"error": "Tag must be 100 characters or fewer"}

    db.add_tag(bookmark_id, normalized)
    db.rebuild_fts()
    return _full_bookmark(db, bookmark_id)


def get_stats(db: Database) -> dict:
    return db.get_stats()


def summarize_topic(
    db: Database,
    query_or_tag: str,
    detail_level: str = "detailed",
) -> dict:
    if detail_level not in ("brief", "detailed", "guide"):
        return {
            "error": f"Invalid detail_level '{detail_level}'. Use: brief, detailed, guide"
        }

    query_or_tag = query_or_tag.strip()
    if not query_or_tag:
        return {
            "query": query_or_tag,
            "detail_level": detail_level,
            "count": 0,
            "bookmarks": [],
        }

    tag_names = {t["tag"] for t in db.list_all_tags()}
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

        links = db.get_links(bid)
        if detail_level == "brief":
            entry["link_titles"] = [
                link["page_title"] for link in links if link.get("page_title")
            ]
        elif detail_level == "detailed":
            entry["links"] = [
                {
                    "title": link.get("page_title", ""),
                    "content_snippet": (link.get("page_content") or "")[:500],
                    "content_type": link.get("content_type", "article"),
                }
                for link in links
                if link.get("page_title") or link.get("page_content")
            ]
            bm_full = db.get_bookmark(bid)
            if bm_full and bm_full.get("thread_text"):
                entry["thread_text"] = bm_full["thread_text"][:1000]
        else:
            full = _full_bookmark(db, bid)
            if full:
                if full.get("thread_text"):
                    entry["thread_text"] = full["thread_text"]
                if full.get("notes"):
                    entry["notes"] = full["notes"]
                entry["links"] = [
                    {
                        "title": link.get("page_title", ""),
                        "content": (link.get("page_content") or "")[:50_000],
                        "content_type": link.get("content_type", "article"),
                        "url": link.get("original_url", ""),
                    }
                    for link in full.get("links", [])
                ]

        bookmarks.append(entry)

    return {
        "query": query_or_tag,
        "detail_level": detail_level,
        "count": len(bookmarks),
        "bookmarks": bookmarks,
    }
