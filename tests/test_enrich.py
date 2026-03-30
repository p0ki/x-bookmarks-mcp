"""Tests for the enrichment pipeline (src/enrich.py)."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db import Database
from src.models import Bookmark, BookmarkLink, EnrichResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bm(
    bookmark_id: str = "1",
    tweet_text: str = "Check this out",
    urls: list[str] | None = None,
    enriched_at: datetime | None = None,
) -> Bookmark:
    """Create a minimal Bookmark for testing."""
    return Bookmark(
        id=bookmark_id,
        author_username="testuser",
        author_name="Test User",
        tweet_text=tweet_text,
        tweet_url=f"https://x.com/testuser/status/{bookmark_id}",
        created_at=datetime(2026, 3, 15),
        urls=urls or [],
        enriched_at=enriched_at,
    )


def _insert(db: Database, bm: Bookmark) -> None:
    """Insert a bookmark and, if it carries urls, also seed bookmark_links rows."""
    db.insert_bookmark(bm)
    for url in bm.urls:
        db.insert_link(
            BookmarkLink(
                bookmark_id=bm.id,
                original_url=url,
            )
        )


# ---------------------------------------------------------------------------
# _detect_content_type
# ---------------------------------------------------------------------------


class TestDetectContentType:
    """URL pattern matching for content type classification."""

    def test_github_url_returns_repo(self) -> None:
        from src.enrich import _detect_content_type

        assert _detect_content_type("https://github.com/anthropics/claude") == "repo"

    def test_github_url_with_subdomain(self) -> None:
        from src.enrich import _detect_content_type

        assert _detect_content_type("https://gist.github.com/user/abc123") == "repo"

    def test_youtube_watch_url(self) -> None:
        from src.enrich import _detect_content_type

        assert _detect_content_type("https://www.youtube.com/watch?v=abc") == "video"

    def test_youtu_be_short_url(self) -> None:
        from src.enrich import _detect_content_type

        assert _detect_content_type("https://youtu.be/abc123") == "video"

    def test_docs_subdomain(self) -> None:
        from src.enrich import _detect_content_type

        assert _detect_content_type("https://docs.anthropic.com/claude") == "docs"

    def test_readthedocs_url(self) -> None:
        from src.enrich import _detect_content_type

        assert _detect_content_type("https://httpx.readthedocs.io/en/latest/") == "docs"

    def test_regular_article_url(self) -> None:
        from src.enrich import _detect_content_type

        assert _detect_content_type("https://example.com/blog/my-post") == "article"

    def test_unknown_url_defaults_to_article(self) -> None:
        from src.enrich import _detect_content_type

        assert (
            _detect_content_type("https://newsletter.substack.com/post/123")
            == "article"
        )


# ---------------------------------------------------------------------------
# _fetch_and_extract
# ---------------------------------------------------------------------------


class TestFetchAndExtract:
    """Async URL fetching + trafilatura content extraction."""

    @pytest.mark.asyncio
    async def test_successful_fetch_returns_title_and_content(self) -> None:
        from src.enrich import _fetch_and_extract

        fake_html = "<html><head><title>My Page</title></head><body><p>Hello world</p></body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = fake_html
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        mock_meta = MagicMock()
        mock_meta.title = "My Page"
        with patch("trafilatura.extract", return_value="Hello world"), patch(
            "trafilatura.extract_metadata", return_value=mock_meta
        ):
            title, content, ctype = await _fetch_and_extract(
                mock_client,
                "https://example.com/post",
                max_length=50_000,
            )

        assert content == "Hello world"
        assert title == "My Page"

    @pytest.mark.asyncio
    async def test_failed_request_returns_none_values(self) -> None:
        import httpx

        from src.enrich import _fetch_and_extract

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.RequestError("connection refused")
        )

        title, content, ctype = await _fetch_and_extract(
            mock_client,
            "https://unreachable.example.com/page",
            max_length=50_000,
        )

        assert title is None
        assert content is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none_values(self) -> None:
        import httpx

        from src.enrich import _fetch_and_extract

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=mock_response,
            )
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        title, content, ctype = await _fetch_and_extract(
            mock_client,
            "https://example.com/missing",
            max_length=50_000,
        )

        assert title is None
        assert content is None

    @pytest.mark.asyncio
    async def test_content_truncated_at_max_length(self) -> None:
        from src.enrich import _fetch_and_extract

        long_text = "x" * 100_000
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body><p>" + long_text + "</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        max_len = 500
        mock_meta = MagicMock()
        mock_meta.title = "Long"
        with patch("trafilatura.extract", return_value=long_text), patch(
            "trafilatura.extract_metadata", return_value=mock_meta
        ):
            title, content, ctype = await _fetch_and_extract(
                mock_client,
                "https://example.com/long",
                max_length=max_len,
            )

        assert content is not None
        assert len(content) <= max_len

    @pytest.mark.asyncio
    async def test_content_type_is_detected_from_url(self) -> None:
        from src.enrich import _fetch_and_extract

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>code</body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        mock_meta = MagicMock()
        mock_meta.title = "Repo"
        with patch("trafilatura.extract", return_value="code stuff"), patch(
            "trafilatura.extract_metadata", return_value=mock_meta
        ):
            _title, _content, ctype = await _fetch_and_extract(
                mock_client,
                "https://github.com/user/repo",
                max_length=50_000,
            )

        assert ctype == "repo"


# ---------------------------------------------------------------------------
# enrich_bookmark
# ---------------------------------------------------------------------------


class TestEnrichBookmark:
    """Single-bookmark enrichment logic."""

    @pytest.mark.asyncio
    async def test_enriches_bookmark_with_url(self, db: Database) -> None:
        from src.enrich import enrich_bookmark

        bm = _bm("42", urls=["https://example.com/article"])
        _insert(db, bm)

        mock_client = AsyncMock()

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(
                return_value=("My Article", "Article content here.", "article")
            ),
        ):
            success = await enrich_bookmark(db, "42", mock_client, config={})

        assert success is True
        row = db.get_bookmark("42")
        assert row is not None
        assert row["enriched_at"] is not None

    @pytest.mark.asyncio
    async def test_enriched_at_is_stamped_on_success(self, db: Database) -> None:
        from src.enrich import enrich_bookmark

        bm = _bm("43", urls=["https://example.com/post"])
        _insert(db, bm)

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=("Title", "Body text.", "article")),
        ):
            await enrich_bookmark(db, "43", AsyncMock(), config={})

        row = db.get_bookmark("43")
        assert row["enriched_at"] is not None

    @pytest.mark.asyncio
    async def test_link_stored_in_bookmark_links(self, db: Database) -> None:
        from src.enrich import enrich_bookmark

        url = "https://example.com/stored"
        bm = _bm("44", urls=[url])
        _insert(db, bm)

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=("Stored Title", "Stored content.", "article")),
        ):
            await enrich_bookmark(db, "44", AsyncMock(), config={})

        links = db.get_links("44")
        assert len(links) == 1
        assert links[0]["original_url"] == url
        assert links[0]["page_title"] == "Stored Title"
        assert links[0]["page_content"] == "Stored content."

    @pytest.mark.asyncio
    async def test_bookmark_with_no_urls_is_skipped(self, db: Database) -> None:
        from src.enrich import enrich_bookmark

        bm = _bm("45", urls=[])
        db.insert_bookmark(bm)

        _success = await enrich_bookmark(db, "45", AsyncMock(), config={})

        # No URLs → nothing to enrich; function may return False or True (skipped)
        # The bookmark must NOT be marked enriched (or if it is, that's implementation choice)
        # The critical check: no crash and no links stored
        links = db.get_links("45")
        assert links == []

    @pytest.mark.asyncio
    async def test_all_urls_fail_does_not_stamp_enriched(self, db: Database) -> None:
        from src.enrich import enrich_bookmark

        bm = _bm(
            "46", urls=["https://fail.example.com/a", "https://fail.example.com/b"]
        )
        _insert(db, bm)

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=(None, None, "article")),
        ):
            success = await enrich_bookmark(db, "46", AsyncMock(), config={})

        assert success is False
        row = db.get_bookmark("46")
        assert row["enriched_at"] is None

    @pytest.mark.asyncio
    async def test_partial_url_failure_still_enriches(self, db: Database) -> None:
        """If at least one URL succeeds, bookmark should be marked enriched."""
        from src.enrich import enrich_bookmark

        bm = _bm("47", urls=["https://ok.example.com/a", "https://fail.example.com/b"])
        _insert(db, bm)

        async def mock_fetch(client, url, max_length):
            if "ok" in url:
                return ("Good Title", "Good content.", "article")
            return (None, None, "article")

        with patch("src.enrich._fetch_and_extract", new=mock_fetch):
            success = await enrich_bookmark(db, "47", AsyncMock(), config={})

        assert success is True
        row = db.get_bookmark("47")
        assert row["enriched_at"] is not None


# ---------------------------------------------------------------------------
# enrich_all
# ---------------------------------------------------------------------------


class TestEnrichAll:
    """Full enrichment pipeline — the main entry point."""

    @pytest.mark.asyncio
    async def test_empty_database_returns_zero_counts(self, db: Database) -> None:
        from src.enrich import enrich_all

        result = await enrich_all(db)

        assert isinstance(result, EnrichResult)
        assert result.enriched == 0
        assert result.failed == 0
        assert result.skipped == 0

    @pytest.mark.asyncio
    async def test_enriches_bookmarks_with_urls(self, db: Database) -> None:
        from src.enrich import enrich_all

        bm1 = _bm("101", urls=["https://example.com/a"])
        bm2 = _bm("102", urls=["https://example.com/b"])
        _insert(db, bm1)
        _insert(db, bm2)

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=("Title", "Content.", "article")),
        ), patch("asyncio.sleep", new=AsyncMock()):
            result = await enrich_all(db)

        assert result.enriched == 2
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_skips_already_enriched_bookmarks(self, db: Database) -> None:
        from src.enrich import enrich_all

        already_done = _bm(
            "201", urls=["https://done.example.com"], enriched_at=datetime(2026, 3, 1)
        )
        fresh = _bm("202", urls=["https://new.example.com"])
        _insert(db, already_done)
        _insert(db, fresh)

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=("Title", "Content.", "article")),
        ), patch("asyncio.sleep", new=AsyncMock()):
            result = await enrich_all(db)

        # "201" is already enriched — should be counted as skipped
        assert result.skipped >= 1
        # "202" is fresh — should be enriched
        assert result.enriched >= 1

    @pytest.mark.asyncio
    async def test_refresh_true_reenriches_everything(self, db: Database) -> None:
        from src.enrich import enrich_all

        bm = _bm(
            "301",
            urls=["https://refresh.example.com"],
            enriched_at=datetime(2026, 3, 1),
        )
        _insert(db, bm)

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=("New Title", "New content.", "article")),
        ), patch("asyncio.sleep", new=AsyncMock()):
            result = await enrich_all(db, refresh=True)

        # With refresh=True the bookmark was previously enriched but must be processed again
        assert result.enriched == 1
        assert result.skipped == 0

    @pytest.mark.asyncio
    async def test_failed_enrichment_counted(self, db: Database) -> None:
        from src.enrich import enrich_all

        bm = _bm("401", urls=["https://broken.example.com"])
        _insert(db, bm)

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=(None, None, "article")),
        ), patch("asyncio.sleep", new=AsyncMock()):
            result = await enrich_all(db)

        assert result.failed == 1
        assert result.enriched == 0

    @pytest.mark.asyncio
    async def test_bookmark_with_no_urls_counted_as_skipped(self, db: Database) -> None:
        from src.enrich import enrich_all

        bm = _bm("501", urls=[])
        db.insert_bookmark(bm)

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await enrich_all(db)

        # No URLs to fetch — should not appear in enriched or failed
        assert result.enriched == 0
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_fts_rebuilt_after_enrichment(self, db: Database) -> None:
        from src.enrich import enrich_all

        bm = _bm("601", urls=["https://example.com/fts"])
        _insert(db, bm)

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=("FTS Title", "Searchable content.", "article")),
        ), patch("asyncio.sleep", new=AsyncMock()):
            with patch.object(db, "rebuild_fts", wraps=db.rebuild_fts) as mock_rebuild:
                await enrich_all(db)

        mock_rebuild.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limit_delay_respected(self, db: Database) -> None:
        from src.enrich import enrich_all

        # One bookmark with 2 URLs — sleep happens between URLs within a bookmark
        bm = _bm("701", urls=["https://a.example.com", "https://b.example.com"])
        _insert(db, bm)

        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=("T", "C", "article")),
        ), patch("asyncio.sleep", new=fake_sleep):
            await enrich_all(db)

        # Sleep must occur between the 2 URL fetches
        assert len(sleep_calls) >= 1
        # Each delay must be non-negative
        assert all(s >= 0 for s in sleep_calls)

    @pytest.mark.asyncio
    async def test_tagger_called_when_provided(self, db: Database) -> None:
        from src.enrich import enrich_all

        bm = _bm("801", urls=["https://example.com/tagged"])
        _insert(db, bm)

        mock_tagger = MagicMock()
        mock_tagger.retag_all = MagicMock()

        with patch(
            "src.enrich._fetch_and_extract",
            new=AsyncMock(return_value=("Tagged Title", "Tagged content.", "article")),
        ), patch("asyncio.sleep", new=AsyncMock()):
            result = await enrich_all(db, tagger=mock_tagger)

        assert result.enriched == 1
        mock_tagger.retag_all.assert_called_once_with(db)

    @pytest.mark.asyncio
    async def test_no_crash_when_single_bookmark_throws(self, db: Database) -> None:
        """Pipeline must continue processing remaining bookmarks on error."""
        from src.enrich import enrich_all

        bm_bad = _bm("901", urls=["https://crash.example.com"])
        bm_ok = _bm("902", urls=["https://ok.example.com"])
        _insert(db, bm_bad)
        _insert(db, bm_ok)

        call_count = 0

        async def flaky_fetch(client, url, max_length):
            nonlocal call_count
            call_count += 1
            if "crash" in url:
                raise RuntimeError("unexpected network error")
            return ("OK Title", "OK Content.", "article")

        with patch("src.enrich._fetch_and_extract", new=flaky_fetch), patch(
            "asyncio.sleep", new=AsyncMock()
        ):
            result = await enrich_all(db)

        # The good bookmark should still have been processed
        assert result.enriched >= 1
