"""Tests for the ingest pipeline."""

import json

import pytest

from src.ingest import detect_format, ingest_file, parse_twitter_web_exporter


class TestDetectFormat:
    def test_detects_twitter_web_exporter(self, tmp_path, sample_export):
        fp = tmp_path / "export.json"
        fp.write_text(json.dumps(sample_export))
        assert detect_format(fp) == "twitter-web-exporter"

    def test_unknown_format(self, tmp_path):
        fp = tmp_path / "bad.json"
        fp.write_text(json.dumps([{"random": "data"}]))
        assert detect_format(fp) == "unknown"

    def test_empty_array(self, tmp_path):
        fp = tmp_path / "empty.json"
        fp.write_text(json.dumps([]))
        assert detect_format(fp) == "unknown"


class TestParser:
    def test_parses_all_bookmarks(self, sample_export):
        bookmarks = parse_twitter_web_exporter(sample_export)
        assert len(bookmarks) == 5

    def test_extracts_fields(self, sample_export):
        bookmarks = parse_twitter_web_exporter(sample_export)
        bm = next(b for b in bookmarks if b.id == "1001")
        assert bm.author_username == "aidev_jane"
        assert bm.author_name == "Jane AI Dev"
        assert "Claude Code MCP" in bm.tweet_text

    def test_extracts_urls(self, sample_export):
        bookmarks = parse_twitter_web_exporter(sample_export)
        bm = next(b for b in bookmarks if b.id == "1003")
        assert len(bm.urls) == 1
        assert "prompt-engineering-guide" in bm.urls[0]

    def test_detects_thread(self, sample_export):
        bookmarks = parse_twitter_web_exporter(sample_export)
        bm = next(b for b in bookmarks if b.id == "1002")
        assert bm.is_thread is True

    def test_multiple_urls(self, sample_export):
        bookmarks = parse_twitter_web_exporter(sample_export)
        bm = next(b for b in bookmarks if b.id == "1004")
        assert len(bm.urls) == 2

    def test_skips_malformed_entry(self):
        data = [
            {
                "rest_id": "1",
                "legacy": {
                    "full_text": "ok",
                    "created_at": "Sat Mar 15 10:30:00 +0000 2026",
                    "entities": {"urls": []},
                },
                "core": {
                    "user_results": {
                        "result": {"legacy": {"screen_name": "a", "name": "A"}}
                    }
                },
            },
            {},
        ]
        bookmarks = parse_twitter_web_exporter(data)
        assert len(bookmarks) == 1


class TestIngestFile:
    def test_ingests_sample(self, db, tmp_path, sample_export):
        fp = tmp_path / "export.json"
        fp.write_text(json.dumps(sample_export))
        result = ingest_file(db, fp)
        assert result.added == 5
        assert result.skipped == 0

    def test_skips_duplicates(self, db, tmp_path, sample_export):
        fp = tmp_path / "export.json"
        fp.write_text(json.dumps(sample_export))
        ingest_file(db, fp)
        result = ingest_file(db, fp)
        assert result.added == 0
        assert result.skipped == 5

    def test_unknown_format_raises(self, db, tmp_path):
        fp = tmp_path / "bad.json"
        fp.write_text(json.dumps([{"random": "data"}]))
        with pytest.raises(ValueError, match="Unknown export format"):
            ingest_file(db, fp)

    def test_simple_json_is_supported(self, db, tmp_path):
        fp = tmp_path / "simple.json"
        fp.write_text(
            json.dumps(
                [
                    {
                        "id": "simple-1",
                        "text": "hello",
                        "created_at": "Sat Mar 15 10:30:00 +0000 2026",
                        "user": {"screen_name": "a", "name": "A"},
                    }
                ]
            )
        )
        result = ingest_file(db, fp)
        assert result.added == 1
        assert db.get_bookmark("simple-1")["tweet_text"] == "hello"

    def test_existing_bookmark_is_updated_when_export_changes(
        self, db, tmp_path, sample_export
    ):
        fp = tmp_path / "export.json"
        fp.write_text(json.dumps(sample_export))
        ingest_file(db, fp)

        changed = json.loads(json.dumps(sample_export))
        changed[0]["legacy"]["full_text"] = "Updated bookmark text"
        fp.write_text(json.dumps(changed))

        result = ingest_file(db, fp)
        assert result.updated == 1
        assert result.skipped == 4
        assert db.get_bookmark("1001")["tweet_text"] == "Updated bookmark text"

    def test_embedded_x_article_content_is_preserved(self, db, tmp_path):
        fp = tmp_path / "article.json"
        fp.write_text(
            json.dumps(
                [
                    {
                        "id": "2001",
                        "full_text": "Read my long-form article",
                        "screen_name": "writer",
                        "name": "Writer",
                        "created_at": "2026-03-31 20:17:06 +02:00",
                        "article_title": "Local AI Notes",
                        "article_text": "Full exported article body",
                        "article_url": "https://x.com/i/article/2001",
                    }
                ]
            )
        )

        result = ingest_file(db, fp)
        assert result.added == 1
        links = db.get_links("2001")
        assert len(links) == 1
        assert links[0]["content_type"] == "x-article"
        assert links[0]["page_title"] == "Local AI Notes"
        assert links[0]["page_content"] == "Full exported article body"
