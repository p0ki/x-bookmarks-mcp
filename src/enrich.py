"""Async URL fetching + content extraction pipeline for x-bookmarks-mcp."""

import asyncio
import logging
import os
import re
from datetime import datetime
from urllib.parse import urlparse

import httpx
import trafilatura

from src.db import Database
from src.models import BookmarkLink, EnrichResult

logger = logging.getLogger(__name__)

# Matches http/https URLs in plain text
_URL_RE = re.compile(r"https?://[^\s\"\'>]+", re.IGNORECASE)

_USER_AGENT = "x-bookmarks-mcp/1.0 (local bookmark enrichment tool)"


def _get_config() -> dict:
    """Read enrichment settings from environment variables with defaults."""
    return {
        "fetch_delay_seconds": float(os.environ.get("FETCH_DELAY_SECONDS", "1.0")),
        "fetch_timeout_seconds": float(os.environ.get("FETCH_TIMEOUT_SECONDS", "10")),
        "max_content_length": int(os.environ.get("MAX_CONTENT_LENGTH", "50000")),
    }


def _detect_content_type(url: str) -> str:
    """Detect content type from URL patterns."""
    parsed = urlparse(url.lower())
    hostname = parsed.hostname or ""
    path = parsed.path or ""

    if "github.com" in hostname or "gitlab.com" in hostname:
        return "repo"

    if "youtube.com" in hostname or "youtu.be" in hostname:
        return "video"

    doc_hosts = ("docs.", "documentation.", "developer.", "devdocs.")
    if any(hostname.startswith(prefix) for prefix in doc_hosts):
        return "docs"

    if "readthedocs." in hostname:
        return "docs"

    doc_paths = (
        "/docs/",
        "/documentation/",
        "/reference/",
        "/api/",
        "/guide/",
        "/manual/",
    )
    if any(path.startswith(p) for p in doc_paths):
        return "docs"

    return "article"


async def _fetch_and_extract(
    client: httpx.AsyncClient,
    url: str,
    max_length: int,
) -> tuple[str | None, str | None, str]:
    """Fetch a URL and extract readable content using trafilatura.

    Returns:
        (page_title, page_content, content_type)
        title and content are None on failure.
    """
    content_type = _detect_content_type(url)

    try:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP {e.response.status_code} fetching {url}: {e}")
        return None, None, content_type
    except httpx.RequestError as e:
        logger.warning(f"Request error fetching {url}: {e}")
        return None, None, content_type
    except Exception as e:
        logger.warning(f"Unexpected error fetching {url}: {e}")
        return None, None, content_type

    try:
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            output_format="txt",
        )
        metadata = trafilatura.extract_metadata(html)

        page_title = metadata.title if metadata and metadata.title else None

        if extracted:
            page_content = (
                extracted[:max_length] if len(extracted) > max_length else extracted
            )
        else:
            page_content = None

    except Exception as e:
        logger.warning(f"Trafilatura extraction failed for {url}: {e}")
        return None, None, content_type

    return page_title, page_content, content_type


def _extract_urls_from_text(text: str) -> list[str]:
    """Extract all http/https URLs from plain text using regex."""
    return _URL_RE.findall(text)


async def enrich_bookmark(
    db: Database,
    bookmark_id: str,
    client: httpx.AsyncClient,
    config: dict,
) -> bool | None:
    """Enrich a single bookmark by fetching all its URLs.

    Discovers URLs from:
    1. Existing bookmark_links rows (including unfetched placeholder rows)
    2. Regex extraction from tweet_text as a fallback

    Returns True if at least one URL was successfully fetched.
    """
    bm_data = db.get_bookmark(bookmark_id)
    if not bm_data:
        logger.warning(f"Bookmark {bookmark_id} not found, skipping")
        return False

    # Collect URLs: existing links first, then tweet_text fallback
    existing_links = db.get_links(bookmark_id)
    known_urls: set[str] = {lnk["original_url"] for lnk in existing_links}

    # Fallback: extract URLs from tweet_text
    tweet_text = bm_data.get("tweet_text") or ""
    for url in _extract_urls_from_text(tweet_text):
        if url not in known_urls:
            known_urls.add(url)

    if not known_urls:
        logger.debug(f"Bookmark {bookmark_id} has no URLs to fetch")
        return None

    max_length: int = config.get("max_content_length", 50000)
    delay: float = config.get("fetch_delay_seconds", 1.0)
    any_success = False

    for i, url in enumerate(sorted(known_urls)):
        # Only re-fetch URLs that haven't been fetched yet
        existing = next(
            (lnk for lnk in existing_links if lnk["original_url"] == url), None
        )
        if existing and existing.get("fetched_at") is not None:
            logger.debug(f"Skipping already-fetched URL: {url}")
            continue

        if i > 0:
            await asyncio.sleep(delay)

        logger.info(f"Fetching {url} for bookmark {bookmark_id}")
        title, content, ctype = await _fetch_and_extract(client, url, max_length)

        link = BookmarkLink(
            bookmark_id=bookmark_id,
            original_url=url,
            page_title=title,
            page_content=content,
            content_type=ctype,
            fetched_at=datetime.now() if (title or content) else None,
        )
        db.insert_link(link)

        if title or content:
            any_success = True

    if any_success:
        db.stamp_enriched(bookmark_id)
    return any_success


async def enrich_all(
    db: Database,
    tagger=None,
    refresh: bool = False,
) -> EnrichResult:
    """Enrich all bookmarks that haven't been enriched yet.

    Args:
        db:      Database instance.
        tagger:  Optional Tagger — if provided, retag_all() is called after enrichment.
        refresh: When True, re-fetch even bookmarks that already have enriched_at set.

    Returns:
        EnrichResult with counts of enriched / failed / skipped.
    """
    config = _get_config()
    result = EnrichResult()

    bookmark_ids = db.list_bookmark_ids()
    logger.info(f"Starting enrichment: {len(bookmark_ids)} bookmarks total")

    timeout = httpx.Timeout(config["fetch_timeout_seconds"])
    limits = httpx.Limits(max_connections=5, max_keepalive_connections=5)
    headers = {"User-Agent": _USER_AGENT}

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        headers=headers,
        max_redirects=5,
        follow_redirects=True,
    ) as client:
        for bookmark_id in bookmark_ids:
            bm_data = db.get_bookmark(bookmark_id)
            if not bm_data:
                result.skipped += 1
                continue

            already_enriched = bm_data.get("enriched_at") is not None
            if already_enriched and not refresh:
                result.skipped += 1
                continue

            try:
                outcome = await enrich_bookmark(db, bookmark_id, client, config)
                if outcome is None:
                    result.skipped += 1
                elif outcome:
                    result.enriched += 1
                else:
                    result.failed += 1
            except Exception as e:
                logger.error(
                    f"Unexpected failure enriching bookmark {bookmark_id}: {e}"
                )
                result.failed += 1

    db.rebuild_fts()
    logger.info(
        f"Enrichment complete: {result.enriched} enriched, "
        f"{result.failed} failed, {result.skipped} skipped"
    )

    if tagger is not None:
        retag = tagger.retag_all(db)
        logger.info(
            f"Retag after enrichment: {retag.bookmarks_processed} bookmarks, "
            f"{retag.tags_added} new tags"
        )

    return result
