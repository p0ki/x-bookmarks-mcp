"""MCP tool definitions for x-bookmarks-mcp.

Eight tools exposing search, browse, annotate, and summarize
capabilities over the local bookmark database.
"""

import logging
import os
from datetime import datetime

import httpx
from src.db import Database
from src.models import Bookmark

logger = logging.getLogger(__name__)

XQUIK_BASE_URL = os.environ.get("XQUIK_BASE_URL", "https://xquik.com").rstrip("/")
XQUIK_TIMEOUT_SECONDS = float(os.environ.get("XQUIK_TIMEOUT_SECONDS", "30"))


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


# --- Tool 1b: import_xquik_search ---


def _xquik_headers() -> dict[str, str]:
    api_key = os.environ.get("XQUIK_API_KEY", "").strip()
    return {"x-api-key": api_key} if api_key else {}


def _as_record(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _tweet_candidates(payload: object) -> list:
    if isinstance(payload, list):
        return payload
    record = _as_record(payload)
    for key in ("tweets", "data", "results", "items"):
        value = record.get(key)
        if isinstance(value, list):
            return value
    return []


def _tweet_value(tweet: dict, *keys: str) -> str:
    for key in keys:
        value = tweet.get(key)
        if value is not None:
            return str(value)
    return ""


def _tweet_author(tweet: dict) -> tuple[str, str]:
    author = _as_record(tweet.get("author") or tweet.get("user"))
    username = _tweet_value(author, "username", "screen_name", "handle")
    username = username.lstrip("@") or "unknown"
    name = _tweet_value(author, "name", "display_name") or username
    return username, name


def _tweet_created_at(tweet: dict) -> datetime:
    value = _tweet_value(tweet, "created_at", "createdAt", "created_time")
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.now()


def import_xquik_search(
    db: Database,
    query: str,
    tag: str = "xquik",
    limit: int = 10,
    query_type: str = "Latest",
) -> dict:
    """Import public X search results from Xquik into the bookmark database."""
    stripped_query = query.strip()
    if not stripped_query:
        return {"error": "query is required"}

    safe_limit = max(1, min(limit, 100))
    with httpx.Client(timeout=XQUIK_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{XQUIK_BASE_URL}/api/v1/x/tweets/search",
            headers=_xquik_headers(),
            params={
                "q": stripped_query,
                "queryType": query_type,
                "limit": safe_limit,
            },
        )
    if response.status_code >= 400:
        return {
            "error": "Xquik search failed",
            "status_code": response.status_code,
            "details": response.text,
        }

    payload = response.json()
    imported = 0
    skipped = 0
    for candidate in _tweet_candidates(payload):
        tweet = _as_record(candidate)
        tweet_id = _tweet_value(tweet, "id", "tweetId", "rest_id")
        tweet_text = _tweet_value(tweet, "text", "full_text", "content")
        if not tweet_id or not tweet_text:
            skipped += 1
            continue
        username, author_name = _tweet_author(tweet)
        db.insert_bookmark(
            Bookmark(
                id=tweet_id,
                author_username=username,
                author_name=author_name,
                tweet_text=tweet_text,
                tweet_url=f"https://x.com/{username}/status/{tweet_id}",
                created_at=_tweet_created_at(tweet),
            )
        )
        if tag:
            db.add_tag(tweet_id, tag)
        imported += 1

    db.rebuild_fts()
    return {
        "query": stripped_query,
        "tag": tag,
        "query_type": query_type,
        "imported": imported,
        "skipped": skipped,
    }


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
            # "guide" - full content
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
