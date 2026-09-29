"""JSON parser + ingestion pipeline for x-bookmarks-mcp."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.db import Database
from src.models import Bookmark, BookmarkLink, IngestResult

logger = logging.getLogger(__name__)


def detect_format(filepath: Path) -> str:
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list) or not data:
        return "unknown"

    first = data[0]
    if "rest_id" in first or (
        "legacy" in first and "full_text" in first.get("legacy", {})
    ):
        return "twitter-web-exporter"
    if "full_text" in first and "screen_name" in first and "id" in first:
        return "x-bookmarks-flat"
    if "text" in first and "user" in first:
        return "simple-json"
    return "unknown"


def _parse_datetime(date_str: str) -> datetime:
    if not date_str:
        logger.warning("Bookmark has no parseable created_at value")
        return datetime.now()

    try:
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        pass

    try:
        iso_str = date_str.replace(" ", "T", 1)
        if len(iso_str) > 19 and iso_str[-3] == ":" and iso_str[-6] in "+-":
            iso_str = iso_str[:-3] + iso_str[-2:]
        return datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        logger.warning("Could not parse bookmark date: %r", date_str)
        return datetime.now()


def _entry_id(entry: dict) -> str:
    return str(entry.get("rest_id") or entry.get("id_str") or entry.get("id") or "")


def _extract_user(entry: dict) -> tuple[str, str]:
    try:
        user = entry["core"]["user_results"]["result"]["legacy"]
        return user["screen_name"], user["name"]
    except (KeyError, TypeError):
        pass

    try:
        user = entry["user"]
        return user["screen_name"], user.get("name", user["screen_name"])
    except (KeyError, TypeError):
        pass

    if entry.get("screen_name"):
        return entry["screen_name"], entry.get("name", "Unknown")

    return "unknown", "Unknown"


def _extract_urls(entry: dict) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def _add(url: str | None) -> None:
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    meta = entry.get("metadata", {})
    for u in meta.get("legacy", {}).get("entities", {}).get("urls", []):
        _add(u.get("expanded_url"))

    note_urls = (
        meta.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
        .get("entity_set", {})
        .get("urls", [])
    )
    for u in note_urls:
        _add(u.get("expanded_url"))

    legacy = entry.get("legacy", entry)
    for u in legacy.get("entities", {}).get("urls", []):
        _add(u.get("expanded_url"))

    article = _extract_embedded_article(entry)
    if article:
        _add(article.get("url"))

    if not urls:
        text = legacy.get("full_text") or legacy.get("text", "")
        for tco in re.findall(r"https?://t\.co/\w+", text):
            _add(tco)

    return urls


def _extract_full_text(entry: dict) -> str:
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


def _collect_text_nodes(value: Any) -> list[str]:
    """Collect text leaves from an X Article content_state structure."""
    found: list[str] = []
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text.strip():
            found.append(text.strip())
        for child in value.values():
            found.extend(_collect_text_nodes(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_collect_text_nodes(child))
    return found


def _extract_embedded_article(entry: dict) -> dict | None:
    """Return article content when the bookmark export already contains it."""
    title = entry.get("article_title")
    text = entry.get("article_text")
    url = entry.get("article_url")

    meta = entry.get("metadata", {})
    article_result = (
        meta.get("article", {}).get("article_results", {}).get("result", {})
    )
    if not article_result:
        article_result = (
            entry.get("article", {}).get("article_results", {}).get("result", {})
        )

    if article_result:
        title = title or article_result.get("title")
        url = url or article_result.get("url")
        if not text:
            content_state = article_result.get("content_state")
            nodes = _collect_text_nodes(content_state)
            if nodes:
                text = "\n\n".join(dict.fromkeys(nodes))

    if not (title or text or url):
        return None

    if not url:
        username, _ = _extract_user(entry)
        tweet_id = _entry_id(entry)
        if tweet_id:
            url = f"https://x.com/{username}/status/{tweet_id}"

    return {"title": title, "text": text, "url": url}


def _parse_entry(entry: dict) -> Bookmark | None:
    tweet_id = _entry_id(entry)
    if not tweet_id:
        logger.warning("Skipping entry with no ID")
        return None

    legacy = entry.get("legacy", entry)
    tweet_text = _extract_full_text(entry)
    username, display_name = _extract_user(entry)
    created_at = _parse_datetime(
        legacy.get("created_at") or entry.get("created_at") or ""
    )
    urls = _extract_urls(entry)

    reply_to = legacy.get("in_reply_to_status_id_str")
    conversation_id = legacy.get("conversation_id_str")
    is_thread = bool(reply_to) or bool(
        conversation_id and str(conversation_id) != tweet_id
    )

    return Bookmark(
        id=tweet_id,
        author_username=username,
        author_name=display_name,
        tweet_text=tweet_text,
        tweet_url=f"https://x.com/{username}/status/{tweet_id}",
        created_at=created_at,
        is_thread=is_thread,
        urls=urls,
    )


def parse_twitter_web_exporter(data: list[dict]) -> list[Bookmark]:
    bookmarks: list[Bookmark] = []
    for entry in data:
        try:
            bookmark = _parse_entry(entry)
            if bookmark:
                bookmarks.append(bookmark)
        except Exception as exc:
            logger.warning("Skipping malformed entry: %s", exc)
    return bookmarks


def _bookmark_changed(existing: dict, bookmark: Bookmark) -> bool:
    expected = {
        "author_username": bookmark.author_username,
        "author_name": bookmark.author_name,
        "tweet_text": bookmark.tweet_text,
        "tweet_url": bookmark.tweet_url,
        "created_at": bookmark.created_at.isoformat(),
        "is_thread": int(bookmark.is_thread),
        "thread_text": bookmark.thread_text,
    }
    return any(existing.get(key) != value for key, value in expected.items())


def ingest_file(db: Database, filepath: Path, tagger=None) -> IngestResult:
    fmt = detect_format(filepath)
    if fmt == "unknown":
        raise ValueError(f"Unknown export format: {filepath}")

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    bookmarks = parse_twitter_web_exporter(data)
    entries_by_id = {_entry_id(entry): entry for entry in data}
    result = IngestResult()

    for bm in bookmarks:
        try:
            existing = db.get_bookmark(bm.id)
            existing_links = {
                link["original_url"]: link for link in db.get_links(bm.id)
            }
            article = _extract_embedded_article(entries_by_id.get(bm.id, {}))

            missing_urls = [url for url in bm.urls if url not in existing_links]
            article_changed = False
            if article and article.get("url"):
                previous = existing_links.get(article["url"])
                article_changed = (
                    previous is None
                    or previous.get("page_title") != article.get("title")
                    or previous.get("page_content") != article.get("text")
                    or previous.get("content_type") != "x-article"
                )

            changed = (
                existing is None
                or _bookmark_changed(existing, bm)
                or bool(missing_urls)
                or article_changed
            )

            if not changed:
                result.skipped += 1
                continue

            db.insert_bookmark(bm)

            for url in missing_urls:
                db.insert_link(BookmarkLink(bookmark_id=bm.id, original_url=url))

            if article and article.get("url"):
                db.insert_link(
                    BookmarkLink(
                        bookmark_id=bm.id,
                        original_url=article["url"],
                        page_title=article.get("title"),
                        page_content=article.get("text"),
                        content_type="x-article",
                        fetched_at=(
                            datetime.now()
                            if article.get("title") or article.get("text")
                            else None
                        ),
                    )
                )

            if tagger:
                link_models = [
                    BookmarkLink(
                        bookmark_id=bm.id,
                        original_url=link["original_url"],
                        page_title=link.get("page_title"),
                        page_content=link.get("page_content"),
                        content_type=link.get("content_type", "article"),
                    )
                    for link in db.get_links(bm.id)
                ]
                for tag in tagger.tag_bookmark(bm, link_models):
                    db.add_tag(bm.id, tag)

            if existing is None:
                result.added += 1
            else:
                result.updated += 1
        except Exception as exc:
            logger.warning("Failed to ingest bookmark %s: %s", bm.id, exc)
            result.errors += 1

    db.rebuild_fts()
    logger.info(
        "Ingest complete: %d added, %d updated, %d skipped, %d errors",
        result.added,
        result.updated,
        result.skipped,
        result.errors,
    )
    return result
