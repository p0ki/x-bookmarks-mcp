"""CLI entry point for x-bookmarks-mcp.

Usage:
    python -m src import data/exports/bookmarks.json
    python -m src enrich [--refresh]
    python -m src retag
    python -m src stats
"""

import asyncio
import logging
import os
from pathlib import Path

import click

from src.db import Database
from src.enrich import enrich_all
from src.ingest import ingest_file
from src.tagger import Tagger

DB_PATH = os.environ.get("DB_PATH", "./data/bookmarks.db")
CONFIG_PATH = os.environ.get("CONFIG_PATH", "./config.yaml")


def _get_db() -> Database:
    return Database(DB_PATH)


def _get_tagger() -> Tagger:
    return Tagger(Path(CONFIG_PATH))


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool) -> None:
    """x-bookmarks-mcp — manage your local bookmark knowledge base."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )


@cli.command(name="import")
@click.argument("filepath", type=click.Path(exists=True, path_type=Path))
def import_cmd(filepath: Path) -> None:
    """Import bookmarks from a JSON export file."""
    db = _get_db()
    tagger = _get_tagger()
    result = ingest_file(db, filepath, tagger=tagger)
    click.echo(
        f"Import complete: {result.added} added, {result.skipped} skipped, {result.errors} errors"
    )


@cli.command()
@click.option("--refresh", is_flag=True, help="Re-fetch already-enriched bookmarks.")
def enrich(refresh: bool) -> None:
    """Fetch URL content for all bookmarks."""
    db = _get_db()
    tagger = _get_tagger()
    result = asyncio.run(enrich_all(db, tagger=tagger, refresh=refresh))
    click.echo(
        f"Enrichment complete: {result.enriched} enriched, "
        f"{result.failed} failed, {result.skipped} skipped"
    )


@cli.command()
def retag() -> None:
    """Re-run auto-tagging on all bookmarks."""
    db = _get_db()
    tagger = _get_tagger()
    result = tagger.retag_all(db)
    db.rebuild_fts()
    click.echo(
        f"Retag complete: {result.bookmarks_processed} bookmarks processed, "
        f"{result.tags_added} new tags added"
    )


@cli.command()
def stats() -> None:
    """Show collection statistics."""
    db = _get_db()
    s = db.get_stats()
    click.echo(f"Total bookmarks:  {s['total_bookmarks']}")
    click.echo(f"Total enriched:   {s['total_enriched']}")
    click.echo(f"Total tags:       {s['total_tags']}")
    if s.get("date_range"):
        click.echo(
            f"Date range:       {s['date_range']['earliest']} → {s['date_range']['latest']}"
        )
    if s.get("top_authors"):
        click.echo("Top authors:")
        for a in s["top_authors"][:5]:
            click.echo(f"  @{a['author_username']}: {a['count']} bookmarks")
    if s.get("tags"):
        click.echo("Tags:")
        for t in s["tags"]:
            click.echo(f"  {t['tag']}: {t['count']}")


if __name__ == "__main__":
    cli()
