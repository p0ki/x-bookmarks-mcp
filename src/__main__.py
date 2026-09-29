"""CLI entry point for x-bookmarks-mcp."""

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
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )


@cli.command(name="import")
@click.argument("filepath", type=click.Path(exists=True, path_type=Path))
def import_cmd(filepath: Path) -> None:
    """Import bookmarks from a JSON export file."""
    result = ingest_file(_get_db(), filepath, tagger=_get_tagger())
    click.echo(
        "Import complete: "
        f"{result.added} added, {result.updated} updated, "
        f"{result.skipped} skipped, {result.errors} errors"
    )


@cli.command()
@click.option("--refresh", is_flag=True, help="Re-fetch already-enriched bookmarks.")
def enrich(refresh: bool) -> None:
    """Fetch URL content for all bookmarks."""
    result = asyncio.run(enrich_all(_get_db(), tagger=_get_tagger(), refresh=refresh))
    click.echo(
        f"Enrichment complete: {result.enriched} enriched, "
        f"{result.failed} failed, {result.skipped} skipped"
    )


@cli.command()
def retag() -> None:
    """Re-run auto-tagging on all bookmarks."""
    db = _get_db()
    result = _get_tagger().retag_all(db)
    db.rebuild_fts()
    click.echo(
        f"Retag complete: {result.bookmarks_processed} bookmarks processed, "
        f"{result.tags_added} new tags added"
    )


@cli.command()
def stats() -> None:
    """Show collection statistics."""
    s = _get_db().get_stats()
    click.echo(f"Total bookmarks:  {s['total_bookmarks']}")
    click.echo(f"Total enriched:   {s['total_enriched']}")
    click.echo(f"Total tags:       {s['total_tags']}")
    if s.get("date_range"):
        click.echo(
            f"Date range:       {s['date_range']['earliest']} → "
            f"{s['date_range']['latest']}"
        )
    if s.get("top_authors"):
        click.echo("Top authors:")
        for author in s["top_authors"][:5]:
            click.echo(f"  @{author['author_username']}: {author['count']} bookmarks")
    if s.get("tags"):
        click.echo("Tags:")
        for tag in s["tags"]:
            click.echo(f"  {tag['tag']}: {tag['count']}")


if __name__ == "__main__":
    cli()
