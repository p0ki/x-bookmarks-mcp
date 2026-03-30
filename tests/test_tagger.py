"""Tests for the auto-tagger."""

from datetime import datetime

import pytest

from src.models import Bookmark, BookmarkLink
from src.tagger import Tagger


@pytest.fixture
def config_file(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("""
tag_rules:
  claude-code:
    - "claude code"
    - "claude-code"
  mcp:
    - "mcp"
    - "model context protocol"
  prompting:
    - "prompt engineering"
""")
    return config


@pytest.fixture
def tagger(config_file):
    return Tagger(config_file)


def _bm(text: str, **kw) -> Bookmark:
    defaults = dict(
        id="1",
        author_username="u",
        author_name="U",
        tweet_text=text,
        tweet_url="https://x.com/u/status/1",
        created_at=datetime(2026, 3, 15),
    )
    defaults.update(kw)
    return Bookmark(**defaults)


class TestTagger:
    def test_matches_keyword(self, tagger):
        tags = tagger.tag_bookmark(_bm("Setting up Claude Code"), [])
        assert "claude-code" in tags

    def test_case_insensitive(self, tagger):
        tags = tagger.tag_bookmark(_bm("CLAUDE CODE is great"), [])
        assert "claude-code" in tags

    def test_multiple_tags(self, tagger):
        tags = tagger.tag_bookmark(_bm("Claude Code MCP server setup"), [])
        assert "claude-code" in tags
        assert "mcp" in tags

    def test_no_match(self, tagger):
        tags = tagger.tag_bookmark(_bm("Python async patterns"), [])
        assert tags == []

    def test_matches_in_page_content(self, tagger):
        link = BookmarkLink(
            bookmark_id="1",
            original_url="https://example.com",
            page_content="A guide to prompt engineering techniques",
        )
        tags = tagger.tag_bookmark(_bm("Check this out"), [link])
        assert "prompting" in tags

    def test_matches_in_thread_text(self, tagger):
        bm = _bm("Thread below", thread_text="How to use MCP servers")
        tags = tagger.tag_bookmark(bm, [])
        assert "mcp" in tags

    def test_matches_in_notes(self, tagger):
        bm = _bm("Some tweet", notes="Useful for Claude Code setup")
        tags = tagger.tag_bookmark(bm, [])
        assert "claude-code" in tags
