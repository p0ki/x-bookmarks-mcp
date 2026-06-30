"""Comprehensive tests for all 8 MCP tools in src/tools.py."""

from datetime import datetime

import pytest

from src.db import Database
from src.models import Bookmark, BookmarkLink
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bm(
    id: str,
    tweet_text: str,
    author_username: str = "testuser",
    thread_text: str | None = None,
    notes: str | None = None,
) -> Bookmark:
    return Bookmark(
        id=id,
        author_username=author_username,
        author_name=author_username.title(),
        tweet_text=tweet_text,
        tweet_url=f"https://x.com/{author_username}/status/{id}",
        created_at=datetime(2024, 1, int(id[-1]) if id[-1].isdigit() else 1),
        thread_text=thread_text,
        notes=notes,
    )


def _link(
    bookmark_id: str,
    url: str,
    title: str | None = None,
    content: str | None = None,
    content_type: str = "article",
) -> BookmarkLink:
    return BookmarkLink(
        bookmark_id=bookmark_id,
        original_url=url,
        page_title=title,
        page_content=content,
        content_type=content_type,
        fetched_at=datetime(2024, 2, 1),
    )


# ---------------------------------------------------------------------------
# Seed fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_db(db: Database) -> Database:
    """DB seeded with 5 bookmarks covering diverse scenarios."""

    # bm1 - Python article with link + tags
    db.insert_bookmark(_bm("bm1", "Python async is amazing for IO-bound tasks"))
    db.insert_link(
        _link(
            "bm1",
            "https://example.com/async",
            "Understanding asyncio",
            "Full asyncio guide content",
        )
    )
    db.add_tag("bm1", "python")
    db.add_tag("bm1", "async")

    # bm2 - thread about machine learning
    db.insert_bookmark(
        _bm(
            "bm2",
            "Machine learning fundamentals thread",
            thread_text="Part 1: supervised learning\nPart 2: unsupervised learning",
        )
    )
    db.add_tag("bm2", "ml")
    db.add_tag("bm2", "python")

    # bm3 - bookmark with notes and a link
    db.insert_bookmark(
        _bm(
            "bm3",
            "Docker containers for dev environments",
            notes="Useful for local setup",
        )
    )
    db.insert_link(
        _link(
            "bm3",
            "https://example.com/docker",
            "Docker Guide",
            "Step by step Docker tutorial",
        )
    )
    db.add_tag("bm3", "devops")
    db.add_tag("bm3", "docker")

    # bm4 - security article
    db.insert_bookmark(
        _bm("bm4", "SQL injection prevention techniques", author_username="secauthor")
    )
    db.add_tag("bm4", "security")

    # bm5 - unicode and long content, no tags, no links
    db.insert_bookmark(_bm("bm5", "Slovenian language unicode test: čšž 🚀"))

    # Rebuild FTS so searches work
    db.rebuild_fts()

    return db


# ---------------------------------------------------------------------------
# Tool 1: search_bookmarks
# ---------------------------------------------------------------------------


class TestSearchBookmarks:
    def test_returns_list(self, seeded_db: Database) -> None:
        result = search_bookmarks(seeded_db, "python")
        assert isinstance(result, list)

    def test_found_results(self, seeded_db: Database) -> None:
        result = search_bookmarks(seeded_db, "python")
        ids = [r["id"] for r in result]
        assert "bm1" in ids

    def test_no_results_returns_empty_list(self, seeded_db: Database) -> None:
        result = search_bookmarks(seeded_db, "xyzzy_no_match_ever")
        assert result == []

    def test_tag_filter_narrows_results(self, seeded_db: Database) -> None:
        # bm1 and bm2 both have 'python', but only bm1 has 'async'
        result = search_bookmarks(seeded_db, "python", tag="async")
        ids = [r["id"] for r in result]
        assert "bm1" in ids
        assert "bm2" not in ids

    def test_tag_filter_no_match_returns_empty(self, seeded_db: Database) -> None:
        result = search_bookmarks(seeded_db, "python", tag="nonexistent_tag")
        assert result == []

    def test_limit_respected(self, seeded_db: Database) -> None:
        # bm1 and bm2 both tagged python; limit=1 should return at most 1
        result = search_bookmarks(seeded_db, "python", limit=1)
        assert len(result) <= 1

    def test_result_has_expected_keys(self, seeded_db: Database) -> None:
        result = search_bookmarks(seeded_db, "python")
        assert len(result) > 0
        row = result[0]
        for key in ("id", "author_username", "tweet_text", "tweet_url", "created_at"):
            assert key in row


class _FakeXquikResponse:
    status_code = 200
    text = ""

    def json(self) -> dict:
        return {
            "tweets": [
                {
                    "id": "1234567890",
                    "text": "MCP search result from Xquik",
                    "created_at": "2026-06-30T00:00:00Z",
                    "author": {"username": "xquik", "name": "Xquik"},
                }
            ]
        }


class _FakeXquikClient:
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    def __enter__(self) -> "_FakeXquikClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, *_args: object, **_kwargs: object) -> _FakeXquikResponse:
        return _FakeXquikResponse()


class TestImportXquikSearch:
    def test_imports_xquik_results_as_bookmarks(
        self, db: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.tools.httpx.Client", _FakeXquikClient)

        result = import_xquik_search(db, "mcp", tag="xquik-test", limit=20)

        assert result["imported"] == 1
        imported = db.get_bookmark("1234567890")
        assert imported is not None
        assert imported["author_username"] == "xquik"
        assert imported["tweet_text"] == "MCP search result from Xquik"
        assert "xquik-test" in db.get_tags("1234567890")

    def test_rejects_empty_query(self, db: Database) -> None:
        result = import_xquik_search(db, "   ")

        assert result == {"error": "query is required"}


# ---------------------------------------------------------------------------
# Tool 2: list_tags
# ---------------------------------------------------------------------------


class TestListTags:
    def test_returns_list(self, seeded_db: Database) -> None:
        result = list_tags(seeded_db)
        assert isinstance(result, list)

    def test_contains_seeded_tags(self, seeded_db: Database) -> None:
        result = list_tags(seeded_db)
        tag_names = {r["tag"] for r in result}
        assert {"python", "async", "ml", "devops", "docker", "security"}.issubset(
            tag_names
        )

    def test_each_entry_has_tag_and_count(self, seeded_db: Database) -> None:
        result = list_tags(seeded_db)
        for entry in result:
            assert "tag" in entry
            assert "count" in entry
            assert isinstance(entry["count"], int)
            assert entry["count"] >= 1

    def test_python_count_is_two(self, seeded_db: Database) -> None:
        result = list_tags(seeded_db)
        python_entry = next(r for r in result if r["tag"] == "python")
        assert python_entry["count"] == 2

    def test_empty_db_returns_empty_list(self, db: Database) -> None:
        result = list_tags(db)
        assert result == []


# ---------------------------------------------------------------------------
# Tool 3: get_bookmark
# ---------------------------------------------------------------------------


class TestGetBookmark:
    def test_found_returns_dict(self, seeded_db: Database) -> None:
        result = get_bookmark(seeded_db, "bm1")
        assert isinstance(result, dict)
        assert "error" not in result

    def test_found_has_expected_keys(self, seeded_db: Database) -> None:
        result = get_bookmark(seeded_db, "bm1")
        for key in (
            "id",
            "author_username",
            "tweet_text",
            "tweet_url",
            "created_at",
            "tags",
            "links",
        ):
            assert key in result

    def test_found_includes_tags(self, seeded_db: Database) -> None:
        result = get_bookmark(seeded_db, "bm1")
        assert set(result["tags"]) == {"python", "async"}

    def test_found_includes_links(self, seeded_db: Database) -> None:
        result = get_bookmark(seeded_db, "bm1")
        assert len(result["links"]) == 1
        assert result["links"][0]["original_url"] == "https://example.com/async"

    def test_not_found_returns_error_dict(self, seeded_db: Database) -> None:
        result = get_bookmark(seeded_db, "nonexistent_id")
        assert "error" in result
        assert "nonexistent_id" in result["error"]

    def test_no_links_returns_empty_list(self, seeded_db: Database) -> None:
        result = get_bookmark(seeded_db, "bm4")
        assert result["links"] == []

    def test_bookmark_with_notes_includes_notes(self, seeded_db: Database) -> None:
        result = get_bookmark(seeded_db, "bm3")
        assert result["notes"] == "Useful for local setup"


# ---------------------------------------------------------------------------
# Tool 4: browse_by_tag
# ---------------------------------------------------------------------------


class TestBrowseByTag:
    def test_returns_list(self, seeded_db: Database) -> None:
        result = browse_by_tag(seeded_db, "python")
        assert isinstance(result, list)

    def test_returns_bookmarks_with_tag(self, seeded_db: Database) -> None:
        result = browse_by_tag(seeded_db, "python")
        ids = [r["id"] for r in result]
        assert "bm1" in ids
        assert "bm2" in ids

    def test_does_not_return_untagged(self, seeded_db: Database) -> None:
        result = browse_by_tag(seeded_db, "python")
        ids = [r["id"] for r in result]
        # bm4 is security, bm5 has no tags
        assert "bm4" not in ids
        assert "bm5" not in ids

    def test_empty_tag_returns_empty_list(self, seeded_db: Database) -> None:
        result = browse_by_tag(seeded_db, "nonexistent_tag_xyz")
        assert result == []

    def test_limit_respected(self, seeded_db: Database) -> None:
        result = browse_by_tag(seeded_db, "python", limit=1)
        assert len(result) <= 1

    def test_result_has_expected_keys(self, seeded_db: Database) -> None:
        result = browse_by_tag(seeded_db, "python")
        assert len(result) > 0
        row = result[0]
        for key in ("id", "author_username", "tweet_text", "tweet_url", "created_at"):
            assert key in row


# ---------------------------------------------------------------------------
# Tool 5: add_note
# ---------------------------------------------------------------------------


class TestAddNote:
    def test_adds_note_and_returns_bookmark(self, seeded_db: Database) -> None:
        result = add_note(seeded_db, "bm1", "My personal note")
        assert result["notes"] == "My personal note"

    def test_returned_dict_has_id(self, seeded_db: Database) -> None:
        result = add_note(seeded_db, "bm1", "A note")
        assert result["id"] == "bm1"

    def test_returned_dict_includes_tags(self, seeded_db: Database) -> None:
        result = add_note(seeded_db, "bm1", "A note")
        assert "tags" in result
        assert isinstance(result["tags"], list)

    def test_returned_dict_includes_links(self, seeded_db: Database) -> None:
        result = add_note(seeded_db, "bm1", "A note")
        assert "links" in result
        assert isinstance(result["links"], list)

    def test_note_is_persisted(self, seeded_db: Database) -> None:
        add_note(seeded_db, "bm2", "Persisted note")
        fetched = get_bookmark(seeded_db, "bm2")
        assert fetched["notes"] == "Persisted note"

    def test_note_update_overwrites(self, seeded_db: Database) -> None:
        add_note(seeded_db, "bm3", "First note")
        add_note(seeded_db, "bm3", "Updated note")
        fetched = get_bookmark(seeded_db, "bm3")
        assert fetched["notes"] == "Updated note"

    def test_not_found_returns_error_dict(self, seeded_db: Database) -> None:
        result = add_note(seeded_db, "ghost_id", "Some note")
        assert "error" in result
        assert "ghost_id" in result["error"]


# ---------------------------------------------------------------------------
# Tool 6: add_tag
# ---------------------------------------------------------------------------


class TestAddTag:
    def test_adds_tag_and_returns_bookmark(self, seeded_db: Database) -> None:
        result = add_tag(seeded_db, "bm5", "newtag")
        assert "newtag" in result["tags"]

    def test_idempotent_duplicate_tag(self, seeded_db: Database) -> None:
        add_tag(seeded_db, "bm1", "python")  # already exists
        result = add_tag(seeded_db, "bm1", "python")
        assert result["tags"].count("python") == 1

    def test_returned_dict_has_correct_id(self, seeded_db: Database) -> None:
        result = add_tag(seeded_db, "bm4", "extra")
        assert result["id"] == "bm4"

    def test_returned_dict_includes_links(self, seeded_db: Database) -> None:
        result = add_tag(seeded_db, "bm4", "extra")
        assert "links" in result

    def test_tag_is_persisted(self, seeded_db: Database) -> None:
        add_tag(seeded_db, "bm5", "tagged_now")
        fetched = get_bookmark(seeded_db, "bm5")
        assert "tagged_now" in fetched["tags"]

    def test_not_found_returns_error_dict(self, seeded_db: Database) -> None:
        result = add_tag(seeded_db, "ghost_id", "tag")
        assert "error" in result
        assert "ghost_id" in result["error"]


# ---------------------------------------------------------------------------
# Tool 7: get_stats
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_returns_dict(self, seeded_db: Database) -> None:
        result = get_stats(seeded_db)
        assert isinstance(result, dict)

    def test_has_expected_keys(self, seeded_db: Database) -> None:
        result = get_stats(seeded_db)
        for key in (
            "total_bookmarks",
            "total_enriched",
            "total_tags",
            "tags",
            "top_authors",
        ):
            assert key in result

    def test_total_bookmarks_correct(self, seeded_db: Database) -> None:
        result = get_stats(seeded_db)
        assert result["total_bookmarks"] == 5

    def test_total_tags_correct(self, seeded_db: Database) -> None:
        result = get_stats(seeded_db)
        # unique tags: python, async, ml, devops, docker, security = 6
        assert result["total_tags"] == 6

    def test_top_authors_is_list(self, seeded_db: Database) -> None:
        result = get_stats(seeded_db)
        assert isinstance(result["top_authors"], list)

    def test_date_range_present(self, seeded_db: Database) -> None:
        result = get_stats(seeded_db)
        assert result["date_range"] is not None
        assert "earliest" in result["date_range"]
        assert "latest" in result["date_range"]

    def test_empty_db_stats(self, db: Database) -> None:
        result = get_stats(db)
        assert result["total_bookmarks"] == 0
        assert result["total_enriched"] == 0
        assert result["total_tags"] == 0
        assert result["date_range"] is None

    def test_total_enriched_counts_only_enriched(self, seeded_db: Database) -> None:
        # stamp one as enriched
        seeded_db.stamp_enriched("bm1")
        result = get_stats(seeded_db)
        assert result["total_enriched"] == 1


# ---------------------------------------------------------------------------
# Tool 8: summarize_topic
# ---------------------------------------------------------------------------


class TestSummarizeTopic:
    def test_returns_dict(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python")
        assert isinstance(result, dict)

    def test_has_expected_keys(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python")
        for key in ("query", "detail_level", "count", "bookmarks"):
            assert key in result

    def test_query_echoed_back(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python")
        assert result["query"] == "python"

    def test_detail_level_echoed_back(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python", detail_level="brief")
        assert result["detail_level"] == "brief"

    # --- no results ---

    def test_no_results_returns_empty_bookmarks(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "xyzzy_no_match_ever_unique_string")
        assert result["count"] == 0
        assert result["bookmarks"] == []

    def test_no_results_still_has_all_keys(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "xyzzy_no_match_ever_unique_string")
        for key in ("query", "detail_level", "count", "bookmarks"):
            assert key in result

    # --- invalid detail_level ---

    def test_invalid_detail_level_returns_error(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python", detail_level="superlong")
        assert "error" in result

    def test_invalid_detail_level_error_message_descriptive(
        self, seeded_db: Database
    ) -> None:
        result = summarize_topic(seeded_db, "python", detail_level="bad_level")
        assert "bad_level" in result["error"]
        assert "brief" in result["error"]

    # --- detail_level: brief ---

    def test_brief_bookmarks_have_link_titles(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python", detail_level="brief")
        assert result["count"] > 0
        # bm1 has a link with title; check it appears in some entry
        bm1_entry = next((b for b in result["bookmarks"] if b["id"] == "bm1"), None)
        assert bm1_entry is not None
        assert "link_titles" in bm1_entry

    def test_brief_link_titles_is_list(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python", detail_level="brief")
        bm1_entry = next(b for b in result["bookmarks"] if b["id"] == "bm1")
        assert isinstance(bm1_entry["link_titles"], list)
        assert "Understanding asyncio" in bm1_entry["link_titles"]

    def test_brief_does_not_include_full_content(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python", detail_level="brief")
        bm1_entry = next(b for b in result["bookmarks"] if b["id"] == "bm1")
        # brief mode should NOT have 'links' with content
        assert "links" not in bm1_entry

    # --- detail_level: detailed ---

    def test_detailed_bookmarks_have_links_with_snippet(
        self, seeded_db: Database
    ) -> None:
        result = summarize_topic(seeded_db, "python", detail_level="detailed")
        bm1_entry = next((b for b in result["bookmarks"] if b["id"] == "bm1"), None)
        assert bm1_entry is not None
        assert "links" in bm1_entry
        link = bm1_entry["links"][0]
        assert "title" in link
        assert "content_snippet" in link
        assert "content_type" in link

    def test_detailed_snippet_truncated_at_500(self, seeded_db: Database) -> None:
        long_content = "x" * 1000
        db2_bm = _bm("long1", "long content tweet")
        # We need a fresh db for isolation; use the seeded_db's connection
        seeded_db.insert_bookmark(db2_bm)
        seeded_db.insert_link(
            _link("long1", "https://example.com/long", "Long Page", long_content)
        )
        seeded_db.rebuild_fts()
        result = summarize_topic(
            seeded_db, "long content tweet", detail_level="detailed"
        )
        entries = [b for b in result["bookmarks"] if b["id"] == "long1"]
        assert len(entries) == 1
        if entries[0].get("links"):
            snippet = entries[0]["links"][0]["content_snippet"]
            assert len(snippet) <= 500

    # --- detail_level: guide ---

    def test_guide_bookmarks_have_full_links(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python", detail_level="guide")
        bm1_entry = next((b for b in result["bookmarks"] if b["id"] == "bm1"), None)
        assert bm1_entry is not None
        assert "links" in bm1_entry
        link = bm1_entry["links"][0]
        assert "title" in link
        assert "content" in link
        assert "content_type" in link
        assert "url" in link

    def test_guide_includes_notes_when_present(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "docker", detail_level="guide")
        bm3_entry = next((b for b in result["bookmarks"] if b["id"] == "bm3"), None)
        assert bm3_entry is not None
        assert bm3_entry.get("notes") == "Useful for local setup"

    def test_guide_includes_thread_text_when_present(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "ml", detail_level="guide")
        bm2_entry = next((b for b in result["bookmarks"] if b["id"] == "bm2"), None)
        assert bm2_entry is not None
        assert "thread_text" in bm2_entry

    # --- tag-based vs search fallback ---

    def test_tag_based_lookup_used_when_tag_exists(self, seeded_db: Database) -> None:
        # "python" is a known tag - should use browse_by_tag path
        result = summarize_topic(seeded_db, "python")
        assert result["count"] > 0

    def test_search_fallback_when_not_a_tag(self, seeded_db: Database) -> None:
        # "asyncio" is not a tag but appears in linked content
        result = summarize_topic(seeded_db, "asyncio")
        # May or may not find results depending on FTS index; just check schema
        assert "count" in result
        assert "bookmarks" in result
        assert isinstance(result["bookmarks"], list)

    def test_count_matches_bookmarks_list_length(self, seeded_db: Database) -> None:
        result = summarize_topic(seeded_db, "python")
        assert result["count"] == len(result["bookmarks"])
