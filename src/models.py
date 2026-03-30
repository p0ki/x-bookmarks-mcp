"""Shared data structures for x-bookmarks-mcp."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Bookmark:
    id: str
    author_username: str
    author_name: str
    tweet_text: str
    tweet_url: str
    created_at: datetime
    bookmarked_at: datetime | None = None
    is_thread: bool = False
    thread_text: str | None = None
    notes: str | None = None
    enriched_at: datetime | None = None
    urls: list[str] = field(default_factory=list)


@dataclass
class BookmarkLink:
    bookmark_id: str
    original_url: str
    page_title: str | None = None
    page_content: str | None = None
    content_type: str = "article"
    fetched_at: datetime | None = None


@dataclass
class IngestResult:
    added: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass
class EnrichResult:
    enriched: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass
class RetagResult:
    bookmarks_processed: int = 0
    tags_added: int = 0
    tags_unchanged: int = 0
