"""Async URL fetching + content extraction pipeline for x-bookmarks-mcp."""

import asyncio
import ipaddress
import logging
import os
import re
import socket
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from src.db import Database
from src.models import BookmarkLink, EnrichResult

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s\"\'>]+", re.IGNORECASE)
_USER_AGENT = "x-bookmarks-mcp/1.0 (local bookmark enrichment tool)"
_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_CONTENT_TYPES = (
    "text/",
    "application/xhtml+xml",
)
_MAX_REDIRECTS = 5


def _get_config() -> dict:
    return {
        "fetch_delay_seconds": float(os.environ.get("FETCH_DELAY_SECONDS", "1.0")),
        "fetch_timeout_seconds": float(os.environ.get("FETCH_TIMEOUT_SECONDS", "10")),
        "max_content_length": int(os.environ.get("MAX_CONTENT_LENGTH", "50000")),
        "max_response_bytes": int(os.environ.get("MAX_RESPONSE_BYTES", "5000000")),
    }


def _detect_content_type(url: str) -> str:
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
    if any(path.startswith(prefix) for prefix in doc_paths):
        return "docs"

    return "article"


def _is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


async def _validate_public_url(url: str) -> bool:
    """Allow only public HTTP(S) destinations.

    The hostname is resolved before each request/redirect and every returned
    address must be globally routable. This blocks localhost, RFC1918,
    link-local, multicast, reserved, and other non-public targets.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    if parsed.username or parsed.password or not parsed.hostname:
        return False

    hostname = parsed.hostname
    try:
        ipaddress.ip_address(hostname)
        return _is_public_ip(hostname)
    except ValueError:
        pass

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        logger.warning("Could not resolve URL host: %s", hostname)
        return False

    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(_is_public_ip(address) for address in addresses)


def _content_type_allowed(header_value: str) -> bool:
    if not header_value:
        return True
    mime = header_value.split(";", 1)[0].strip().lower()
    return any(
        mime.startswith(prefix) if prefix.endswith("/") else mime == prefix
        for prefix in _ALLOWED_CONTENT_TYPES
    )


async def _download_html(
    client: httpx.AsyncClient,
    url: str,
    max_response_bytes: int,
) -> tuple[str | None, str | None]:
    """Download a bounded text response and validate every redirect target."""
    current_url = url

    for _ in range(_MAX_REDIRECTS + 1):
        if not await _validate_public_url(current_url):
            logger.warning("Blocked non-public or invalid URL: %s", current_url)
            return None, None

        try:
            async with client.stream(
                "GET",
                current_url,
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None, None
                    current_url = urljoin(str(response.url), location)
                    continue

                response.raise_for_status()

                if not _content_type_allowed(response.headers.get("content-type", "")):
                    logger.warning(
                        "Skipping unsupported content type %r from %s",
                        response.headers.get("content-type"),
                        current_url,
                    )
                    return None, None

                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > max_response_bytes:
                            logger.warning(
                                "Skipping oversized response from %s (%s bytes)",
                                current_url,
                                content_length,
                            )
                            return None, None
                    except ValueError:
                        pass

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_response_bytes:
                        logger.warning(
                            "Stopped oversized streamed response from %s",
                            current_url,
                        )
                        return None, None

                encoding = response.encoding or "utf-8"
                return body.decode(encoding, errors="replace"), current_url

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "HTTP %s fetching %s: %s",
                exc.response.status_code,
                current_url,
                exc,
            )
            return None, None
        except httpx.RequestError as exc:
            logger.warning("Request error fetching %s: %s", current_url, exc)
            return None, None
        except Exception as exc:
            logger.warning("Unexpected error fetching %s: %s", current_url, exc)
            return None, None

    logger.warning("Too many redirects fetching %s", url)
    return None, None


async def _fetch_and_extract(
    client: httpx.AsyncClient,
    url: str,
    max_length: int,
    max_response_bytes: int = 5_000_000,
) -> tuple[str | None, str | None, str]:
    content_type = _detect_content_type(url)
    html, final_url = await _download_html(client, url, max_response_bytes)
    if html is None:
        return None, None, content_type

    if final_url:
        content_type = _detect_content_type(final_url)

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
        page_content = extracted[:max_length] if extracted else None
    except Exception as exc:
        logger.warning("Trafilatura extraction failed for %s: %s", url, exc)
        return None, None, content_type

    return page_title, page_content, content_type


def _extract_urls_from_text(text: str) -> list[str]:
    return _URL_RE.findall(text)


async def enrich_bookmark(
    db: Database,
    bookmark_id: str,
    client: httpx.AsyncClient,
    config: dict,
) -> bool | None:
    bm_data = db.get_bookmark(bookmark_id)
    if not bm_data:
        logger.warning("Bookmark %s not found, skipping", bookmark_id)
        return False

    existing_links = db.get_links(bookmark_id)
    known_urls: set[str] = {link["original_url"] for link in existing_links}

    for url in _extract_urls_from_text(bm_data.get("tweet_text") or ""):
        known_urls.add(url)

    if not known_urls:
        return None

    max_length = int(config.get("max_content_length", 50_000))
    max_response_bytes = int(config.get("max_response_bytes", 5_000_000))
    delay = float(config.get("fetch_delay_seconds", 1.0))
    any_success = False

    for index, url in enumerate(sorted(known_urls)):
        existing = next(
            (link for link in existing_links if link["original_url"] == url),
            None,
        )
        if existing and existing.get("fetched_at") is not None:
            continue

        if index > 0:
            await asyncio.sleep(delay)

        logger.info("Fetching %s for bookmark %s", url, bookmark_id)
        title, content, content_type = await _fetch_and_extract(
            client,
            url,
            max_length,
            max_response_bytes,
        )

        db.insert_link(
            BookmarkLink(
                bookmark_id=bookmark_id,
                original_url=url,
                page_title=title,
                page_content=content,
                content_type=content_type,
                fetched_at=datetime.now() if (title or content) else None,
            )
        )
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
    config = _get_config()
    result = EnrichResult()
    bookmark_ids = db.list_bookmark_ids()

    timeout = httpx.Timeout(config["fetch_timeout_seconds"])
    limits = httpx.Limits(max_connections=5, max_keepalive_connections=5)
    headers = {"User-Agent": _USER_AGENT}

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        headers=headers,
        follow_redirects=False,
    ) as client:
        for bookmark_id in bookmark_ids:
            bm_data = db.get_bookmark(bookmark_id)
            if not bm_data:
                result.skipped += 1
                continue

            if bm_data.get("enriched_at") is not None and not refresh:
                result.skipped += 1
                continue

            try:
                outcome = await enrich_bookmark(
                    db,
                    bookmark_id,
                    client,
                    config,
                )
                if outcome is None:
                    result.skipped += 1
                elif outcome:
                    result.enriched += 1
                else:
                    result.failed += 1
            except Exception as exc:
                logger.error(
                    "Unexpected failure enriching bookmark %s: %s",
                    bookmark_id,
                    exc,
                )
                result.failed += 1

    if tagger is not None:
        tagger.retag_all(db)
    db.rebuild_fts()

    logger.info(
        "Enrichment complete: %d enriched, %d failed, %d skipped",
        result.enriched,
        result.failed,
        result.skipped,
    )
    return result
