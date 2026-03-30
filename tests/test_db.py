"""Tests for the database layer."""

from datetime import datetime

from src.db import Database
from src.models import Bookmark, BookmarkLink


def _make_bookmark(**overrides) -> Bookmark:
    defaults = dict(
        id="123",
        author_username="testuser",
        author_name="Test User",
        tweet_text="Hello world",
        tweet_url="https://x.com/testuser/status/123",
        created_at=datetime(2026, 3, 15, 10, 0, 0),
    )
    defaults.update(overrides)
    return Bookmark(**defaults)


class TestDatabaseInit:
    def test_creates_database_file(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _db = Database(db_path)
        assert (tmp_path / "test.db").exists()

    def test_creates_bookmarks_table(self, db):
        tables = db._execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "bookmarks" in table_names

    def test_creates_bookmark_links_table(self, db):
        tables = db._execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "bookmark_links" in table_names

    def test_creates_bookmark_tags_table(self, db):
        tables = db._execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "bookmark_tags" in table_names

    def test_enables_wal_mode(self, db):
        result = db._execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"

    def test_fts5_available(self, db):
        assert db._fts_available is True


class TestBookmarkCRUD:
    def test_insert_and_get(self, db):
        bm = _make_bookmark()
        db.insert_bookmark(bm)
        result = db.get_bookmark("123")
        assert result is not None
        assert result["id"] == "123"
        assert result["author_username"] == "testuser"
        assert result["tweet_text"] == "Hello world"

    def test_get_nonexistent_returns_none(self, db):
        assert db.get_bookmark("nonexistent") is None

    def test_upsert_overwrites(self, db):
        db.insert_bookmark(_make_bookmark(tweet_text="original"))
        db.insert_bookmark(_make_bookmark(tweet_text="updated"))
        result = db.get_bookmark("123")
        assert result["tweet_text"] == "updated"

    def test_update_notes(self, db):
        db.insert_bookmark(_make_bookmark())
        db.update_notes("123", "my note")
        result = db.get_bookmark("123")
        assert result["notes"] == "my note"

    def test_stamp_enriched(self, db):
        db.insert_bookmark(_make_bookmark())
        db.stamp_enriched("123")
        result = db.get_bookmark("123")
        assert result["enriched_at"] is not None


class TestLinks:
    def test_insert_and_get_links(self, db):
        db.insert_bookmark(_make_bookmark())
        link = BookmarkLink(
            bookmark_id="123",
            original_url="https://example.com/article",
            page_title="Test Article",
            page_content="Article content here",
            content_type="article",
            fetched_at=datetime(2026, 3, 15, 12, 0, 0),
        )
        db.insert_link(link)
        links = db.get_links("123")
        assert len(links) == 1
        assert links[0]["page_title"] == "Test Article"

    def test_get_links_empty(self, db):
        db.insert_bookmark(_make_bookmark())
        assert db.get_links("123") == []


class TestTags:
    def test_add_and_get_tags(self, db):
        db.insert_bookmark(_make_bookmark())
        db.add_tag("123", "mcp")
        db.add_tag("123", "claude-code")
        tags = db.get_tags("123")
        assert set(tags) == {"mcp", "claude-code"}

    def test_add_tag_idempotent(self, db):
        db.insert_bookmark(_make_bookmark())
        db.add_tag("123", "mcp")
        db.add_tag("123", "mcp")  # no error
        tags = db.get_tags("123")
        assert tags == ["mcp"]

    def test_list_all_tags(self, db):
        db.insert_bookmark(_make_bookmark(id="1"))
        db.insert_bookmark(_make_bookmark(id="2"))
        db.add_tag("1", "mcp")
        db.add_tag("2", "mcp")
        db.add_tag("1", "claude-code")
        all_tags = db.list_all_tags()
        tag_map = {t["tag"]: t["count"] for t in all_tags}
        assert tag_map["mcp"] == 2
        assert tag_map["claude-code"] == 1


class TestSearch:
    def test_fts_search_finds_match(self, db):
        db.insert_bookmark(
            _make_bookmark(id="1", tweet_text="Setting up Claude Code MCP server")
        )
        db.insert_bookmark(_make_bookmark(id="2", tweet_text="Python async patterns"))
        db.rebuild_fts()
        results = db.search("Claude Code", tag=None, limit=10)
        assert len(results) >= 1
        assert results[0]["id"] == "1"

    def test_search_with_tag_filter(self, db):
        db.insert_bookmark(_make_bookmark(id="1", tweet_text="MCP server setup"))
        db.insert_bookmark(_make_bookmark(id="2", tweet_text="MCP client config"))
        db.add_tag("1", "setup")
        db.rebuild_fts()
        results = db.search("MCP", tag="setup", limit=10)
        assert len(results) == 1
        assert results[0]["id"] == "1"

    def test_search_no_results(self, db):
        db.insert_bookmark(_make_bookmark())
        db.rebuild_fts()
        results = db.search("nonexistent query xyz", tag=None, limit=10)
        assert results == []

    def test_search_respects_limit(self, db):
        for i in range(5):
            db.insert_bookmark(_make_bookmark(id=str(i), tweet_text=f"MCP topic {i}"))
        db.rebuild_fts()
        results = db.search("MCP", tag=None, limit=2)
        assert len(results) == 2


class TestBrowse:
    def test_browse_by_tag(self, db):
        db.insert_bookmark(_make_bookmark(id="1", created_at=datetime(2026, 3, 15)))
        db.insert_bookmark(_make_bookmark(id="2", created_at=datetime(2026, 3, 16)))
        db.add_tag("1", "mcp")
        db.add_tag("2", "mcp")
        results = db.browse_by_tag("mcp", limit=20)
        assert len(results) == 2
        assert results[0]["id"] == "2"  # newest first

    def test_browse_nonexistent_tag(self, db):
        results = db.browse_by_tag("nonexistent", limit=20)
        assert results == []


class TestStats:
    def test_stats_counts(self, db):
        db.insert_bookmark(_make_bookmark(id="1"))
        db.insert_bookmark(_make_bookmark(id="2"))
        db.add_tag("1", "mcp")
        db.stamp_enriched("1")
        stats = db.get_stats()
        assert stats["total_bookmarks"] == 2
        assert stats["total_enriched"] == 1

    def test_stats_top_authors(self, db):
        db.insert_bookmark(_make_bookmark(id="1", author_username="alice"))
        db.insert_bookmark(_make_bookmark(id="2", author_username="alice"))
        db.insert_bookmark(_make_bookmark(id="3", author_username="bob"))
        stats = db.get_stats()
        assert stats["top_authors"][0]["author_username"] == "alice"
        assert stats["top_authors"][0]["count"] == 2
