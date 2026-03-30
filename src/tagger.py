"""Keyword-based auto-tagging engine for x-bookmarks-mcp."""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.db import Database
from src.models import Bookmark, BookmarkLink, RetagResult

logger = logging.getLogger(__name__)


@dataclass
class TagRule:
    tag: str
    keywords: list[str]


class Tagger:
    def __init__(self, config_path: Path) -> None:
        self._config_path = Path(config_path)
        self.rules = self.load_rules()

    def load_rules(self) -> list[TagRule]:
        with open(self._config_path) as f:
            config = yaml.safe_load(f)

        rules = []
        for tag, keywords in config.get("tag_rules", {}).items():
            rules.append(TagRule(tag=tag, keywords=[k.lower() for k in keywords]))
        return rules

    def tag_bookmark(self, bookmark: Bookmark, links: list[BookmarkLink]) -> list[str]:
        searchable_parts = [
            bookmark.tweet_text or "",
            bookmark.thread_text or "",
            bookmark.notes or "",
        ]
        for link in links:
            searchable_parts.append(link.page_title or "")
            searchable_parts.append(link.page_content or "")

        searchable_text = " ".join(searchable_parts).lower()

        matched_tags = []
        for rule in self.rules:
            for keyword in rule.keywords:
                if keyword in searchable_text:
                    matched_tags.append(rule.tag)
                    break

        return matched_tags

    def retag_all(self, db: Database) -> RetagResult:
        result = RetagResult()
        rows = db.list_bookmark_ids()
        for bookmark_id in rows:
            bm_data = db.get_bookmark(bookmark_id)
            if not bm_data:
                continue

            bookmark = Bookmark(
                id=bm_data["id"],
                author_username=bm_data["author_username"],
                author_name=bm_data["author_name"],
                tweet_text=bm_data["tweet_text"],
                tweet_url=bm_data["tweet_url"],
                created_at=bm_data["created_at"],
                thread_text=bm_data.get("thread_text"),
                notes=bm_data.get("notes"),
            )

            links_data = db.get_links(bookmark_id)
            links = [
                BookmarkLink(
                    bookmark_id=bookmark_id,
                    original_url=ld["original_url"],
                    page_title=ld.get("page_title"),
                    page_content=ld.get("page_content"),
                    content_type=ld.get("content_type", "article"),
                )
                for ld in links_data
            ]

            existing_tags = set(db.get_tags(bookmark_id))
            new_tags = set(self.tag_bookmark(bookmark, links))

            for tag in new_tags - existing_tags:
                db.add_tag(bookmark_id, tag)
                result.tags_added += 1

            result.tags_unchanged += len(new_tags & existing_tags)
            result.bookmarks_processed += 1

        logger.info(
            f"Retag complete: {result.bookmarks_processed} bookmarks, "
            f"{result.tags_added} new tags"
        )
        return result
