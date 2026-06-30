"""MCP server entry point for x-bookmarks-mcp.

Exposes 8 tools over stdio for Claude Code / Cowork integration.
Run: python -m src.server
"""

import logging
import os

from mcp.server.fastmcp import FastMCP

from src.db import Database
from src.tools import (
    add_note,
    add_tag,
    browse_by_tag,
    get_bookmark,
    get_stats,
    import_xquik_search,
    list_tags,
    search_bookmarks,
    summarize_topic,
)

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "./data/bookmarks.db")

mcp = FastMCP("x-bookmarks-mcp")

# Lazy-initialised database - created on first tool call.
_db: Database | None = None


def _get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(DB_PATH)
    return _db


# --- Tool 1: search_bookmarks ---


@mcp.tool()
def tool_search_bookmarks(
    query: str,
    tag: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search bookmarks using full-text search.

    Searches across tweet text, thread content, enriched page content,
    notes, and tags. Returns ranked results with snippets.

    Args:
        query: Search query string.
        tag: Optional tag to filter results.
        limit: Maximum number of results (default 10).
    """
    return search_bookmarks(_get_db(), query, tag, limit)


@mcp.tool()
def tool_import_xquik_search(
    query: str,
    tag: str = "xquik",
    limit: int = 10,
    query_type: str = "Latest",
) -> dict:
    """Import public X search results from Xquik.

    Args:
        query: Search query string.
        tag: Tag to attach to imported results.
        limit: Maximum number of results to import. Min 1, max 100.
        query_type: Xquik query type, usually 'Latest' or 'Top'.
    """
    return import_xquik_search(_get_db(), query, tag, limit, query_type)


# --- Tool 2: list_tags ---


@mcp.tool()
def tool_list_tags() -> list[dict]:
    """List all tags with bookmark counts.

    Returns every tag in the collection along with how many
    bookmarks have that tag. Useful for understanding what
    topics the bookmarks cover.
    """
    return list_tags(_get_db())


# --- Tool 3: get_bookmark ---


@mcp.tool()
def tool_get_bookmark(bookmark_id: str) -> dict:
    """Get a single bookmark with full detail.

    Returns the complete bookmark including tweet text, thread text,
    all linked page content, tags, and user notes.

    Args:
        bookmark_id: The tweet ID of the bookmark.
    """
    return get_bookmark(_get_db(), bookmark_id)


# --- Tool 4: browse_by_tag ---


@mcp.tool()
def tool_browse_by_tag(tag: str, limit: int = 20) -> list[dict]:
    """Browse bookmarks by tag, newest first.

    Args:
        tag: Tag to filter by (e.g. 'claude-code', 'mcp').
        limit: Maximum number of results (default 20).
    """
    return browse_by_tag(_get_db(), tag, limit)


# --- Tool 5: add_note ---


@mcp.tool()
def tool_add_note(bookmark_id: str, note: str) -> dict:
    """Add or update a personal note on a bookmark.

    Args:
        bookmark_id: The tweet ID of the bookmark.
        note: The note text to attach.
    """
    return add_note(_get_db(), bookmark_id, note)


# --- Tool 6: add_tag ---


@mcp.tool()
def tool_add_tag(bookmark_id: str, tag: str) -> dict:
    """Add a tag to a bookmark (idempotent).

    Args:
        bookmark_id: The tweet ID of the bookmark.
        tag: Tag to add (e.g. 'home-lab', 'must-read').
    """
    return add_tag(_get_db(), bookmark_id, tag)


# --- Tool 7: get_stats ---


@mcp.tool()
def tool_get_stats() -> dict:
    """Get a collection overview.

    Returns total bookmarks, enrichment status, tag counts,
    top authors, and date range.
    """
    return get_stats(_get_db())


# --- Tool 8: summarize_topic ---


@mcp.tool()
def tool_summarize_topic(
    query_or_tag: str,
    detail_level: str = "detailed",
) -> dict:
    """Gather bookmarks on a topic for synthesis.

    Collects all matching bookmarks and structures their content
    at the requested detail level for you to summarize.

    Args:
        query_or_tag: A tag name or search query.
        detail_level: One of 'brief', 'detailed', or 'guide'.
    """
    return summarize_topic(_get_db(), query_or_tag, detail_level)


def main() -> None:
    """Run the MCP server over stdio."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info(f"Starting x-bookmarks-mcp server (DB: {DB_PATH})")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
