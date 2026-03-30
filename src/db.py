"""SQLite + FTS5 database layer for x-bookmarks-mcp."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from src.models import Bookmark, BookmarkLink

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id TEXT PRIMARY KEY,
    author_username TEXT NOT NULL,
    author_name TEXT NOT NULL,
    tweet_text TEXT NOT NULL,
    tweet_url TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    bookmarked_at DATETIME,
    is_thread BOOLEAN NOT NULL DEFAULT 0,
    thread_text TEXT,
    notes TEXT,
    enriched_at DATETIME
);

CREATE TABLE IF NOT EXISTS bookmark_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmark_id TEXT NOT NULL REFERENCES bookmarks(id),
    original_url TEXT NOT NULL,
    page_title TEXT,
    page_content TEXT,
    content_type TEXT NOT NULL DEFAULT 'article',
    fetched_at DATETIME,
    UNIQUE(bookmark_id, original_url)
);

CREATE TABLE IF NOT EXISTS bookmark_tags (
    bookmark_id TEXT NOT NULL REFERENCES bookmarks(id),
    tag TEXT NOT NULL,
    PRIMARY KEY (bookmark_id, tag)
);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._fts_available = self._check_fts5()
        if self._fts_available:
            self._create_fts_table()
        self._conn.commit()
        logger.info(f"Database initialized at {db_path} (FTS5: {self._fts_available})")

    def _check_fts5(self) -> bool:
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS _fts_check USING fts5(test)"
            )
            self._conn.execute("DROP TABLE IF EXISTS _fts_check")
            return True
        except sqlite3.OperationalError:
            logger.warning("FTS5 not available — falling back to LIKE queries")
            return False

    def _create_fts_table(self) -> None:
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS bookmarks_fts USING fts5(
                tweet_text,
                thread_text,
                page_content,
                notes,
                tags,
                content='',
                tokenize='porter'
            )
        """)

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    # --- Bookmarks ---

    def insert_bookmark(self, bookmark: Bookmark) -> None:
        self._conn.execute(
            """INSERT INTO bookmarks
            (id, author_username, author_name, tweet_text, tweet_url,
             created_at, bookmarked_at, is_thread, thread_text, notes, enriched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                author_username=excluded.author_username,
                author_name=excluded.author_name,
                tweet_text=excluded.tweet_text,
                tweet_url=excluded.tweet_url,
                created_at=excluded.created_at,
                bookmarked_at=excluded.bookmarked_at,
                is_thread=excluded.is_thread,
                thread_text=excluded.thread_text""",
            (
                bookmark.id,
                bookmark.author_username,
                bookmark.author_name,
                bookmark.tweet_text,
                bookmark.tweet_url,
                bookmark.created_at.isoformat(),
                bookmark.bookmarked_at.isoformat() if bookmark.bookmarked_at else None,
                bookmark.is_thread,
                bookmark.thread_text,
                bookmark.notes,
                bookmark.enriched_at.isoformat() if bookmark.enriched_at else None,
            ),
        )
        self._conn.commit()

    def get_bookmark(self, bookmark_id: str) -> dict | None:
        row = self._execute(
            "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def update_notes(self, bookmark_id: str, note: str) -> None:
        self._execute(
            "UPDATE bookmarks SET notes = ? WHERE id = ?", (note, bookmark_id)
        )
        self._conn.commit()

    def stamp_enriched(self, bookmark_id: str) -> None:
        self._execute(
            "UPDATE bookmarks SET enriched_at = ? WHERE id = ?",
            (datetime.now().isoformat(), bookmark_id),
        )
        self._conn.commit()

    # --- Links ---

    def insert_link(self, link: BookmarkLink) -> None:
        self._conn.execute(
            """INSERT INTO bookmark_links
            (bookmark_id, original_url, page_title, page_content, content_type, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(bookmark_id, original_url) DO UPDATE SET
                page_title=excluded.page_title,
                page_content=excluded.page_content,
                content_type=excluded.content_type,
                fetched_at=excluded.fetched_at""",
            (
                link.bookmark_id,
                link.original_url,
                link.page_title,
                link.page_content,
                link.content_type,
                link.fetched_at.isoformat() if link.fetched_at else None,
            ),
        )
        self._conn.commit()

    def get_links(self, bookmark_id: str) -> list[dict]:
        rows = self._execute(
            "SELECT original_url, page_title, page_content, content_type, fetched_at "
            "FROM bookmark_links WHERE bookmark_id = ?",
            (bookmark_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Tags ---

    def add_tag(self, bookmark_id: str, tag: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO bookmark_tags (bookmark_id, tag) VALUES (?, ?)",
            (bookmark_id, tag),
        )
        self._conn.commit()

    def get_tags(self, bookmark_id: str) -> list[str]:
        rows = self._execute(
            "SELECT tag FROM bookmark_tags WHERE bookmark_id = ? ORDER BY tag",
            (bookmark_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def list_all_tags(self) -> list[dict]:
        rows = self._execute(
            "SELECT tag, COUNT(*) as count FROM bookmark_tags GROUP BY tag ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Search ---

    def rebuild_fts(self) -> None:
        if not self._fts_available:
            return
        self._execute("DROP TABLE IF EXISTS bookmarks_fts")
        self._create_fts_table()
        self._execute("""
            INSERT INTO bookmarks_fts (rowid, tweet_text, thread_text, page_content, notes, tags)
            SELECT b.rowid,
                   b.tweet_text,
                   COALESCE(b.thread_text, ''),
                   COALESCE(
                       (SELECT GROUP_CONCAT(bl.page_content, ' ')
                        FROM bookmark_links bl WHERE bl.bookmark_id = b.id), ''),
                   COALESCE(b.notes, ''),
                   COALESCE(
                       (SELECT GROUP_CONCAT(bt.tag, ' ')
                        FROM bookmark_tags bt WHERE bt.bookmark_id = b.id), '')
            FROM bookmarks b
        """)
        self._conn.commit()
        logger.info("FTS5 index rebuilt")

    def search(self, query: str, tag: str | None, limit: int) -> list[dict]:
        if self._fts_available:
            return self._search_fts(query, tag, limit)
        return self._search_like(query, tag, limit)

    def _search_fts(self, query: str, tag: str | None, limit: int) -> list[dict]:
        if tag:
            rows = self._execute(
                """SELECT b.id, b.author_username, b.author_name, b.tweet_text,
                          b.tweet_url, b.created_at,
                          snippet(bookmarks_fts, 0, '<b>', '</b>', '...', 32) as snippet,
                          rank as score
                   FROM bookmarks_fts fts
                   JOIN bookmarks b ON b.rowid = fts.rowid
                   JOIN bookmark_tags t ON t.bookmark_id = b.id
                   WHERE bookmarks_fts MATCH ? AND t.tag = ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, tag, limit),
            ).fetchall()
        else:
            rows = self._execute(
                """SELECT b.id, b.author_username, b.author_name, b.tweet_text,
                          b.tweet_url, b.created_at,
                          snippet(bookmarks_fts, 0, '<b>', '</b>', '...', 32) as snippet,
                          rank as score
                   FROM bookmarks_fts fts
                   JOIN bookmarks b ON b.rowid = fts.rowid
                   WHERE bookmarks_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def _search_like(self, query: str, tag: str | None, limit: int) -> list[dict]:
        like_pattern = f"%{query}%"
        if tag:
            rows = self._execute(
                """SELECT DISTINCT b.id, b.author_username, b.author_name, b.tweet_text,
                          b.tweet_url, b.created_at, '' as snippet, 0 as score
                   FROM bookmarks b
                   JOIN bookmark_tags t ON t.bookmark_id = b.id
                   LEFT JOIN bookmark_links bl ON bl.bookmark_id = b.id
                   WHERE (b.tweet_text LIKE ? OR b.thread_text LIKE ?
                          OR b.notes LIKE ? OR bl.page_content LIKE ?)
                     AND t.tag = ?
                   LIMIT ?""",
                (like_pattern, like_pattern, like_pattern, like_pattern, tag, limit),
            ).fetchall()
        else:
            rows = self._execute(
                """SELECT DISTINCT b.id, b.author_username, b.author_name, b.tweet_text,
                          b.tweet_url, b.created_at, '' as snippet, 0 as score
                   FROM bookmarks b
                   LEFT JOIN bookmark_links bl ON bl.bookmark_id = b.id
                   WHERE b.tweet_text LIKE ? OR b.thread_text LIKE ?
                         OR b.notes LIKE ? OR bl.page_content LIKE ?
                   LIMIT ?""",
                (like_pattern, like_pattern, like_pattern, like_pattern, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Browse ---

    def browse_by_tag(self, tag: str, limit: int) -> list[dict]:
        rows = self._execute(
            """SELECT b.id, b.author_username, b.author_name, b.tweet_text,
                      b.tweet_url, b.created_at
               FROM bookmarks b
               JOIN bookmark_tags t ON t.bookmark_id = b.id
               WHERE t.tag = ?
               ORDER BY b.created_at DESC
               LIMIT ?""",
            (tag, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Stats ---

    def list_bookmark_ids(self) -> list[str]:
        rows = self._execute("SELECT id FROM bookmarks").fetchall()
        return [r[0] for r in rows]

    def get_stats(self) -> dict:
        total = self._execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
        enriched = self._execute(
            "SELECT COUNT(*) FROM bookmarks WHERE enriched_at IS NOT NULL"
        ).fetchone()[0]
        tags = self.list_all_tags()
        top_authors = [
            dict(r) for r in self._execute("""SELECT author_username, COUNT(*) as count
                   FROM bookmarks GROUP BY author_username
                   ORDER BY count DESC LIMIT 10""").fetchall()
        ]
        date_range_row = self._execute(
            "SELECT MIN(created_at) as earliest, MAX(created_at) as latest FROM bookmarks"
        ).fetchone()
        return {
            "total_bookmarks": total,
            "total_enriched": enriched,
            "total_tags": len(tags),
            "tags": tags,
            "top_authors": top_authors,
            "date_range": (
                {
                    "earliest": date_range_row["earliest"],
                    "latest": date_range_row["latest"],
                }
                if total > 0
                else None
            ),
        }
