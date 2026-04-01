"""JSON parser + ingestion pipeline for x-bookmarks-mcp."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from src.db import Database
from src.models import Bookmark, BookmarkLink, IngestResult

logger = logging.getLogger(__name__)


def detect_format(filepath: Path) -> str:
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list) or len(data) == 0:
        return "unknown"

    first = data[0]

    # Official Twitter web exporter (nested legacy + rest_id)
    if "rest_id" in first or (
        "legacy" in first and "full_text" in first.get("legacy", {})
    ):
        return "twitter-web-exporter"

    # Simple JSON (older format)
    if "text" in first and "user" in first:
        return "simple-json"

    # ←←← NEW: Your exact format (flattened X bookmarks)
    if "full_text" in first and "screen_name" in first and "id" in first:
        return "x-bookmarks-flat"

    return "unknown"

def _parse_datetime(date_str: str) -> datetime:
    """Parse both old Twitter format and the new flat X export format."""
    if not date_str:
        logger.warning(f"Could not parse date: {date_str}")
        return datetime.now()

    # 1. Old classic Twitter format (still used by some exporters)
    try:
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        pass

    # 2. New flat X bookmarks format: "2026-03-31 20:17:06 +02:00"
    try:
        # Normalise to format that Python 3.13 understands:
        #   - replace space with T
        #   - remove colon from timezone (+02:00 → +0200)
        iso_str = date_str.replace(" ", "T", 1)
        if len(iso_str) > 19 and iso_str[-3] == ":" and iso_str[-6] in "+-":
            iso_str = iso_str[:-3] + iso_str[-2:]
        return datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        pass

    logger.warning(f"Could not parse date: {date_str}")
    return datetime.now()


def _extract_user(entry: dict) -> tuple[str, str]:
    """Extract (screen_name, display_name) — works for both nested and flat formats."""
    # 1. Official Twitter web exporter (nested)
    try:
        user = entry["core"]["user_results"]["result"]["legacy"]
        return user["screen_name"], user["name"]
    except (KeyError, TypeError):
        pass

    # 2. Older simple-json format
    try:
        return entry["user"]["screen_name"], entry["user"]["name"]
    except (KeyError, TypeError):
        pass

    # 3. Flat X bookmarks export (your format) — direct top-level keys
    try:
        return entry["screen_name"], entry.get("name", "Unknown")
    except (KeyError, TypeError):
        pass

    return "unknown", "Unknown"


def _extract_urls(entry: dict) -> list[str]:
    """Extract URLs from all available sources in the entry.

    Priority:
    1. metadata.legacy.entities.urls (tweet-level expanded URLs)
    2. metadata.note_tweet entity_set urls (long-tweet expanded URLs)
    3. legacy.entities.urls (official twitter-web-exporter nested format)
    4. Fallback: raw t.co URLs from full_text (enrichment will resolve them)
    """
    urls: list[str] = []
    seen: set[str] = set()

    def _add(url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    # 1. metadata.legacy.entities.urls (flat export with metadata)
    meta = entry.get("metadata", {})
    for u in meta.get("legacy", {}).get("entities", {}).get("urls", []):
        _add(u.get("expanded_url", ""))

    # 2. note_tweet entity_set (long tweets)
    note = meta.get("note_tweet", {})
    note_urls = (
        note.get("note_tweet_results", {})
        .get("result", {})
        .get("entity_set", {})
        .get("urls", [])
    )
    for u in note_urls:
        _add(u.get("expanded_url", ""))

    # 3. legacy.entities.urls (nested twitter-web-exporter format)
    legacy = entry.get("legacy", entry)
    for u in legacy.get("entities", {}).get("urls", []):
        _add(u.get("expanded_url", ""))

    # 4. Fallback: t.co URLs from text (enrichment resolves redirects)
    if not urls:
        text = legacy.get("full_text") or legacy.get("text", "")
        for tco in re.findall(r"https?://t\.co/\w+", text):
            _add(tco)

    return urls


def _extract_full_text(entry: dict) -> str:
    """Get the best available tweet text, preferring note_tweet for long posts."""
    # note_tweet has the full untruncated text for long tweets
    meta = entry.get("metadata", {})
    note_text = (
        meta.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
        .get("text", "")
    )
    if note_text:
        return note_text

    legacy = entry.get("legacy", entry)
    return legacy.get("full_text") or legacy.get("text", "")


def parse_twitter_web_exporter(data: list[dict]) -> list[Bookmark]:
    bookmarks = []
    for entry in data:
        try:
            legacy = entry.get("legacy", entry)
            tweet_id = (
                entry.get("rest_id") or entry.get("id_str") or str(entry.get("id", ""))
            )
            if not tweet_id:
                logger.warning("Skipping entry with no ID")
                continue

            tweet_text = _extract_full_text(entry)
            username, display_name = _extract_user(entry)
            created_at = _parse_datetime(legacy.get("created_at", ""))
            urls = _extract_urls(entry)

            reply_to = legacy.get("in_reply_to_status_id_str")
            is_thread = reply_to is not None and reply_to == tweet_id

            bookmarks.append(
                Bookmark(
                    id=tweet_id,
                    author_username=username,
                    author_name=display_name,
                    tweet_text=tweet_text,
                    tweet_url=f"https://x.com/{username}/status/{tweet_id}",
                    created_at=created_at,
                    is_thread=is_thread,
                    urls=urls,
                )
            )
        except Exception as e:
            logger.warning(f"Skipping malformed entry: {e}")
            continue

    return bookmarks


def ingest_file(db: Database, filepath: Path, tagger=None) -> IngestResult:
    fmt = detect_format(filepath)
    if fmt == "unknown":
        raise ValueError(f"Unknown export format: {filepath}")
    if fmt == "simple-json":
        raise NotImplementedError("Simple JSON format not yet supported")

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    bookmarks = parse_twitter_web_exporter(data)
    result = IngestResult()

    for bm in bookmarks:
        existing = db.get_bookmark(bm.id)
        if existing is not None:
            result.skipped += 1
            continue
        try:
            db.insert_bookmark(bm)
            for url in bm.urls:
                db.insert_link(BookmarkLink(bookmark_id=bm.id, original_url=url))
            if tagger:
                tags = tagger.tag_bookmark(bm, [])
                for tag in tags:
                    db.add_tag(bm.id, tag)
            result.added += 1
        except Exception as e:
            logger.warning(f"Failed to insert bookmark {bm.id}: {e}")
            result.errors += 1

    db.rebuild_fts()
    logger.info(
        f"Ingest complete: {result.added} added, {result.skipped} skipped, {result.errors} errors"
    )
    return result
