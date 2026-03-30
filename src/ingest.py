"""JSON parser + ingestion pipeline for x-bookmarks-mcp."""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.db import Database
from src.models import Bookmark, IngestResult

logger = logging.getLogger(__name__)


def detect_format(filepath: Path) -> str:
    with open(filepath) as f:
        data = json.load(f)

    if not isinstance(data, list) or len(data) == 0:
        return "unknown"

    first = data[0]
    if "rest_id" in first or (
        "legacy" in first and "full_text" in first.get("legacy", {})
    ):
        return "twitter-web-exporter"
    if "text" in first and "user" in first:
        return "simple-json"
    return "unknown"


def _parse_datetime(date_str: str) -> datetime:
    """Parse Twitter's datetime format."""
    try:
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        logger.warning(f"Could not parse date: {date_str}")
        return datetime.now()


def _extract_user(entry: dict) -> tuple[str, str]:
    """Extract (screen_name, display_name) from nested user data."""
    try:
        user = entry["core"]["user_results"]["result"]["legacy"]
        return user["screen_name"], user["name"]
    except (KeyError, TypeError):
        try:
            return entry["user"]["screen_name"], entry["user"]["name"]
        except (KeyError, TypeError):
            return "unknown", "Unknown"


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

            tweet_text = legacy.get("full_text") or legacy.get("text", "")
            username, display_name = _extract_user(entry)
            created_at = _parse_datetime(legacy.get("created_at", ""))

            urls = []
            for url_entity in legacy.get("entities", {}).get("urls", []):
                expanded = url_entity.get("expanded_url")
                if expanded:
                    urls.append(expanded)

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

    with open(filepath) as f:
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
