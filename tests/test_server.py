"""Tests for src/server.py - MCP server wiring and tool delegation."""

import inspect
from datetime import datetime

import pytest

import src.server as server_module
from src.db import Database
from src.models import Bookmark

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_TOOLS = {
    "tool_search_bookmarks",
    "tool_import_xquik_search",
    "tool_list_tags",
    "tool_get_bookmark",
    "tool_browse_by_tag",
    "tool_add_note",
    "tool_add_tag",
    "tool_get_stats",
    "tool_summarize_topic",
}


def _seed_db(db: Database) -> tuple[str, str]:
    """Insert two bookmarks, rebuild FTS index, and return their IDs.

    FTS5 is configured as contentless (content=''), so rebuild_fts() must be
    called after inserting rows to populate the full-text search index.
    """
    bm1 = Bookmark(
        id="tweet_001",
        author_username="alice",
        author_name="Alice",
        tweet_text="Exploring MCP tools for Claude Code integration",
        tweet_url="https://x.com/alice/status/tweet_001",
        created_at=datetime(2025, 1, 10, 12, 0, 0),
        bookmarked_at=datetime(2025, 1, 10, 13, 0, 0),
    )
    bm2 = Bookmark(
        id="tweet_002",
        author_username="bob",
        author_name="Bob",
        tweet_text="FastMCP makes building MCP servers easy with Python decorators",
        tweet_url="https://x.com/bob/status/tweet_002",
        created_at=datetime(2025, 2, 5, 9, 0, 0),
        bookmarked_at=datetime(2025, 2, 5, 10, 0, 0),
    )
    db.insert_bookmark(bm1)
    db.insert_bookmark(bm2)
    db.add_tag("tweet_001", "mcp")
    db.add_tag("tweet_002", "mcp")
    db.add_tag("tweet_002", "python")
    # Contentless FTS5 table requires an explicit rebuild to be queryable.
    db.rebuild_fts()
    return bm1.id, bm2.id


# ---------------------------------------------------------------------------
# 1. Module import
# ---------------------------------------------------------------------------


class TestModuleImport:
    def test_mcp_object_exists(self) -> None:
        """The module exposes a FastMCP instance named 'mcp'."""
        from mcp.server.fastmcp import FastMCP

        assert hasattr(server_module, "mcp")
        assert isinstance(server_module.mcp, FastMCP)

    def test_get_db_function_exists(self) -> None:
        assert callable(server_module._get_db)

    def test_db_path_configured(self) -> None:
        """DB_PATH is set (default or from environment)."""
        assert isinstance(server_module.DB_PATH, str)
        assert len(server_module.DB_PATH) > 0


# ---------------------------------------------------------------------------
# 2. Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_all_nine_tools_registered(self) -> None:
        """All 9 tool_* functions are registered on the FastMCP instance."""
        registered = set(server_module.mcp._tool_manager._tools.keys())
        assert EXPECTED_TOOLS == registered

    def test_tool_count_is_exactly_nine(self) -> None:
        registered = server_module.mcp._tool_manager._tools
        assert len(registered) == 9

    @pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOLS))
    def test_individual_tool_registered(self, tool_name: str) -> None:
        registered = server_module.mcp._tool_manager._tools
        assert (
            tool_name in registered
        ), f"Tool '{tool_name}' not found in registered tools"


# ---------------------------------------------------------------------------
# 3. DB lazy initialisation
# ---------------------------------------------------------------------------


class TestDbLazyInit:
    def test_get_db_creates_database_instance(self, tmp_path, monkeypatch) -> None:
        """_get_db() returns a Database instance."""
        monkeypatch.setattr(server_module, "_db", None)
        monkeypatch.setattr(server_module, "DB_PATH", str(tmp_path / "lazy.db"))

        result = server_module._get_db()
        assert isinstance(result, Database)

    def test_get_db_reuses_same_instance(self, tmp_path, monkeypatch) -> None:
        """Subsequent calls to _get_db() return the identical object."""
        monkeypatch.setattr(server_module, "_db", None)
        monkeypatch.setattr(server_module, "DB_PATH", str(tmp_path / "reuse.db"))

        first = server_module._get_db()
        second = server_module._get_db()
        assert first is second

    def test_get_db_uses_existing_instance(self, tmp_path, monkeypatch) -> None:
        """If _db is already set, _get_db() returns it without creating a new one."""
        existing_db = Database(str(tmp_path / "existing.db"))
        monkeypatch.setattr(server_module, "_db", existing_db)
        # DB_PATH points somewhere different - should never be opened
        monkeypatch.setattr(
            server_module, "DB_PATH", str(tmp_path / "should_not_open.db")
        )

        result = server_module._get_db()
        assert result is existing_db

    def test_get_db_respects_db_path(self, tmp_path, monkeypatch) -> None:
        """_get_db() creates the database at DB_PATH."""
        target = tmp_path / "specific.db"
        monkeypatch.setattr(server_module, "_db", None)
        monkeypatch.setattr(server_module, "DB_PATH", str(target))

        _db = server_module._get_db()
        assert target.exists()
        # Clean up so subsequent tests start fresh
        monkeypatch.setattr(server_module, "_db", None)


# ---------------------------------------------------------------------------
# 4. Integration tests - tool functions delegate to src.tools
# ---------------------------------------------------------------------------


@pytest.fixture()
def patched_db(db: Database, monkeypatch) -> Database:
    """Patch server._db to point at the test database, seed it, and return it."""
    _seed_db(db)
    monkeypatch.setattr(server_module, "_db", db)
    return db


class TestToolSearchBookmarks:
    def test_returns_results_for_matching_query(self, patched_db) -> None:
        results = server_module.tool_search_bookmarks("MCP")
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_returns_empty_list_for_no_match(self, patched_db) -> None:
        results = server_module.tool_search_bookmarks("xyznotfound99999")
        assert results == []

    def test_respects_limit_parameter(self, patched_db) -> None:
        results = server_module.tool_search_bookmarks("MCP", limit=1)
        assert len(results) <= 1

    def test_filters_by_tag(self, patched_db) -> None:
        results = server_module.tool_search_bookmarks("MCP", tag="python")
        ids = [r["id"] for r in results]
        assert "tweet_002" in ids
        # tweet_001 has no 'python' tag - should not appear when tag filter active
        assert "tweet_001" not in ids

    def test_returns_list_of_dicts(self, patched_db) -> None:
        results = server_module.tool_search_bookmarks("Claude")
        assert all(isinstance(r, dict) for r in results)


class TestToolListTags:
    def test_returns_list(self, patched_db) -> None:
        result = server_module.tool_list_tags()
        assert isinstance(result, list)

    def test_contains_seeded_tags(self, patched_db) -> None:
        result = server_module.tool_list_tags()
        tag_names = {r["tag"] for r in result}
        assert "mcp" in tag_names
        assert "python" in tag_names

    def test_includes_count_field(self, patched_db) -> None:
        result = server_module.tool_list_tags()
        assert all("count" in r for r in result)

    def test_mcp_tag_count_is_two(self, patched_db) -> None:
        result = server_module.tool_list_tags()
        mcp_entry = next(r for r in result if r["tag"] == "mcp")
        assert mcp_entry["count"] == 2


class TestToolGetBookmark:
    def test_returns_dict_for_existing_bookmark(self, patched_db) -> None:
        result = server_module.tool_get_bookmark("tweet_001")
        assert isinstance(result, dict)
        assert result.get("id") == "tweet_001"

    def test_returns_error_for_missing_bookmark(self, patched_db) -> None:
        result = server_module.tool_get_bookmark("does_not_exist")
        assert "error" in result

    def test_result_includes_tags(self, patched_db) -> None:
        result = server_module.tool_get_bookmark("tweet_001")
        assert "tags" in result
        assert "mcp" in result["tags"]

    def test_result_includes_links(self, patched_db) -> None:
        result = server_module.tool_get_bookmark("tweet_001")
        assert "links" in result


class TestToolBrowseByTag:
    def test_returns_bookmarks_for_known_tag(self, patched_db) -> None:
        results = server_module.tool_browse_by_tag("mcp")
        assert isinstance(results, list)
        assert len(results) == 2

    def test_returns_empty_for_unknown_tag(self, patched_db) -> None:
        results = server_module.tool_browse_by_tag("nonexistent_tag")
        assert results == []

    def test_respects_limit(self, patched_db) -> None:
        results = server_module.tool_browse_by_tag("mcp", limit=1)
        assert len(results) <= 1

    def test_results_are_dicts(self, patched_db) -> None:
        results = server_module.tool_browse_by_tag("mcp")
        assert all(isinstance(r, dict) for r in results)


class TestToolAddNote:
    def test_adds_note_to_existing_bookmark(self, patched_db) -> None:
        result = server_module.tool_add_note("tweet_001", "important resource")
        assert isinstance(result, dict)
        assert result.get("notes") == "important resource"

    def test_returns_error_for_missing_bookmark(self, patched_db) -> None:
        result = server_module.tool_add_note("ghost_tweet", "some note")
        assert "error" in result

    def test_note_persists_on_subsequent_get(self, patched_db) -> None:
        server_module.tool_add_note("tweet_002", "follow up later")
        fetched = server_module.tool_get_bookmark("tweet_002")
        assert fetched.get("notes") == "follow up later"

    def test_note_can_be_updated(self, patched_db) -> None:
        server_module.tool_add_note("tweet_001", "first note")
        result = server_module.tool_add_note("tweet_001", "updated note")
        assert result.get("notes") == "updated note"


class TestToolAddTag:
    def test_adds_new_tag(self, patched_db) -> None:
        result = server_module.tool_add_tag("tweet_001", "new-tag")
        assert isinstance(result, dict)
        assert "new-tag" in result.get("tags", [])

    def test_idempotent_on_duplicate(self, patched_db) -> None:
        server_module.tool_add_tag("tweet_001", "mcp")
        result = server_module.tool_add_tag("tweet_001", "mcp")
        assert result.get("tags", []).count("mcp") == 1

    def test_returns_error_for_missing_bookmark(self, patched_db) -> None:
        result = server_module.tool_add_tag("ghost_tweet", "some-tag")
        assert "error" in result

    def test_tag_appears_in_list_tags_after_add(self, patched_db) -> None:
        server_module.tool_add_tag("tweet_001", "brand-new")
        tags = {r["tag"] for r in server_module.tool_list_tags()}
        assert "brand-new" in tags


class TestToolGetStats:
    def test_returns_dict(self, patched_db) -> None:
        result = server_module.tool_get_stats()
        assert isinstance(result, dict)

    def test_contains_total_bookmarks(self, patched_db) -> None:
        result = server_module.tool_get_stats()
        assert "total_bookmarks" in result

    def test_total_bookmarks_matches_seeded_count(self, patched_db) -> None:
        result = server_module.tool_get_stats()
        assert result["total_bookmarks"] == 2


class TestToolSummarizeTopic:
    def test_returns_dict_with_required_keys(self, patched_db) -> None:
        result = server_module.tool_summarize_topic("mcp")
        assert isinstance(result, dict)
        for key in ("query", "detail_level", "count", "bookmarks"):
            assert key in result, f"Missing key: {key}"

    def test_returns_results_for_known_tag(self, patched_db) -> None:
        result = server_module.tool_summarize_topic("mcp")
        assert result["count"] == 2

    def test_returns_empty_for_no_match(self, patched_db) -> None:
        result = server_module.tool_summarize_topic("xyznotfound99999")
        assert result["count"] == 0
        assert result["bookmarks"] == []

    def test_default_detail_level_is_detailed(self, patched_db) -> None:
        result = server_module.tool_summarize_topic("mcp")
        assert result["detail_level"] == "detailed"

    def test_brief_detail_level(self, patched_db) -> None:
        result = server_module.tool_summarize_topic("mcp", detail_level="brief")
        assert result["detail_level"] == "brief"

    def test_guide_detail_level(self, patched_db) -> None:
        result = server_module.tool_summarize_topic("mcp", detail_level="guide")
        assert result["detail_level"] == "guide"

    def test_invalid_detail_level_returns_error(self, patched_db) -> None:
        result = server_module.tool_summarize_topic("mcp", detail_level="invalid")
        assert "error" in result


# ---------------------------------------------------------------------------
# 5. Tool function signatures and docstrings
# ---------------------------------------------------------------------------


class TestToolSignatures:
    @pytest.mark.parametrize(
        "func_name,expected_params",
        [
            ("tool_search_bookmarks", ["query", "tag", "limit"]),
            ("tool_import_xquik_search", ["query", "tag", "limit", "query_type"]),
            ("tool_list_tags", []),
            ("tool_get_bookmark", ["bookmark_id"]),
            ("tool_browse_by_tag", ["tag", "limit"]),
            ("tool_add_note", ["bookmark_id", "note"]),
            ("tool_add_tag", ["bookmark_id", "tag"]),
            ("tool_get_stats", []),
            ("tool_summarize_topic", ["query_or_tag", "detail_level"]),
        ],
    )
    def test_parameter_names(self, func_name: str, expected_params: list[str]) -> None:
        func = getattr(server_module, func_name)
        sig = inspect.signature(func)
        actual_params = list(sig.parameters.keys())
        assert (
            actual_params == expected_params
        ), f"{func_name}: expected params {expected_params}, got {actual_params}"

    @pytest.mark.parametrize("func_name", sorted(EXPECTED_TOOLS))
    def test_has_docstring(self, func_name: str) -> None:
        func = getattr(server_module, func_name)
        assert (
            func.__doc__ is not None and len(func.__doc__.strip()) > 0
        ), f"{func_name} is missing a docstring"

    def test_search_bookmarks_has_type_annotations(self) -> None:
        hints = server_module.tool_search_bookmarks.__annotations__
        assert "query" in hints
        assert "return" in hints

    def test_get_bookmark_return_annotation_is_dict(self) -> None:
        hints = server_module.tool_get_bookmark.__annotations__
        assert hints.get("return") is dict

    def test_list_tags_return_annotation_is_list(self) -> None:
        # The annotation is list[dict] - verify it is a list-origin generic.
        hints = server_module.tool_list_tags.__annotations__
        return_hint = hints.get("return")
        assert return_hint is not None
        # list[dict] has __origin__ == list; bare `list` does not have __origin__
        origin = getattr(return_hint, "__origin__", return_hint)
        assert origin is list

    def test_get_stats_return_annotation_is_dict(self) -> None:
        hints = server_module.tool_get_stats.__annotations__
        assert hints.get("return") is dict
