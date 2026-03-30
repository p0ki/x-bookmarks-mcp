"""Tests for the Click CLI defined in src/__main__.py."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from src.__main__ import cli
from src.models import EnrichResult

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_export.json"
PROJECT_CONFIG = str(Path(__file__).parent.parent / "config.yaml")


@pytest.fixture
def runner() -> CliRunner:
    """Click test runner with isolated filesystem mixing."""
    return CliRunner()


@pytest.fixture
def patched_env(tmp_path, monkeypatch):
    """Patch DB_PATH and CONFIG_PATH to safe temp locations."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("src.__main__.DB_PATH", db_path)
    monkeypatch.setattr("src.__main__.CONFIG_PATH", PROJECT_CONFIG)
    return db_path


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_cli_help(runner: CliRunner) -> None:
    """--help returns exit code 0 and lists all subcommands."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "import" in result.output
    assert "enrich" in result.output
    assert "retag" in result.output
    assert "stats" in result.output


def test_import_help(runner: CliRunner) -> None:
    """import --help shows expected description."""
    result = runner.invoke(cli, ["import", "--help"])
    assert result.exit_code == 0
    assert "Import" in result.output


def test_enrich_help(runner: CliRunner) -> None:
    """enrich --help shows --refresh option."""
    result = runner.invoke(cli, ["enrich", "--help"])
    assert result.exit_code == 0
    assert "--refresh" in result.output


# ---------------------------------------------------------------------------
# import command
# ---------------------------------------------------------------------------


def test_import_command(runner: CliRunner, patched_env) -> None:
    """Import fixture file and report added/skipped/errors counts."""
    result = runner.invoke(cli, ["import", str(FIXTURE_PATH)])
    assert result.exit_code == 0, result.output
    assert "Import complete:" in result.output
    assert "added" in result.output
    assert "skipped" in result.output
    assert "errors" in result.output


def test_import_command_nonexistent_file(runner: CliRunner, patched_env) -> None:
    """Import with a missing file path exits with a non-zero code."""
    result = runner.invoke(cli, ["import", "/nonexistent/path/no_such_file.json"])
    assert result.exit_code != 0


def test_import_adds_bookmarks(runner: CliRunner, patched_env) -> None:
    """After import the added count is positive for the fixture file."""
    result = runner.invoke(cli, ["import", str(FIXTURE_PATH)])
    assert result.exit_code == 0, result.output
    # Extract the added number from "Import complete: N added, ..."
    import re

    match = re.search(r"(\d+) added", result.output)
    assert match is not None, f"Could not find added count in: {result.output}"
    assert int(match.group(1)) > 0


# ---------------------------------------------------------------------------
# enrich command
# ---------------------------------------------------------------------------


def test_enrich_command_mocked(runner: CliRunner, patched_env, monkeypatch) -> None:
    """Enrich command prints correct counts from mocked enrich_all."""
    mock_result = EnrichResult(enriched=2, failed=1, skipped=3)

    async def fake_enrich_all(db, tagger=None, refresh=False):
        return mock_result

    monkeypatch.setattr("src.__main__.enrich_all", fake_enrich_all)

    result = runner.invoke(cli, ["enrich"])
    assert result.exit_code == 0, result.output
    assert "2 enriched" in result.output
    assert "1 failed" in result.output
    assert "3 skipped" in result.output


def test_enrich_refresh_flag(runner: CliRunner, patched_env, monkeypatch) -> None:
    """--refresh flag is passed through to enrich_all."""
    received: dict = {}

    async def fake_enrich_all(db, tagger=None, refresh=False):
        received["refresh"] = refresh
        return EnrichResult(enriched=0, failed=0, skipped=0)

    monkeypatch.setattr("src.__main__.enrich_all", fake_enrich_all)

    result = runner.invoke(cli, ["enrich", "--refresh"])
    assert result.exit_code == 0, result.output
    assert received.get("refresh") is True


def test_enrich_without_refresh_flag(
    runner: CliRunner, patched_env, monkeypatch
) -> None:
    """refresh defaults to False when flag is omitted."""
    received: dict = {}

    async def fake_enrich_all(db, tagger=None, refresh=False):
        received["refresh"] = refresh
        return EnrichResult(enriched=0, failed=0, skipped=0)

    monkeypatch.setattr("src.__main__.enrich_all", fake_enrich_all)

    result = runner.invoke(cli, ["enrich"])
    assert result.exit_code == 0, result.output
    assert received.get("refresh") is False


# ---------------------------------------------------------------------------
# retag command
# ---------------------------------------------------------------------------


def test_retag_command(runner: CliRunner, patched_env) -> None:
    """Retag runs without error and reports processed/tags_added counts."""
    # First seed some data so retag has something to process
    runner.invoke(cli, ["import", str(FIXTURE_PATH)])

    result = runner.invoke(cli, ["retag"])
    assert result.exit_code == 0, result.output
    assert "Retag complete:" in result.output
    assert "bookmarks processed" in result.output
    assert "new tags added" in result.output


def test_retag_empty_db(runner: CliRunner, patched_env) -> None:
    """Retag on empty database exits cleanly."""
    result = runner.invoke(cli, ["retag"])
    assert result.exit_code == 0, result.output
    assert "Retag complete:" in result.output


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------


def test_stats_command_empty_db(runner: CliRunner, patched_env) -> None:
    """Stats on fresh database shows zero counts."""
    result = runner.invoke(cli, ["stats"])
    assert result.exit_code == 0, result.output
    assert "Total bookmarks:" in result.output
    assert "Total enriched:" in result.output
    assert "Total tags:" in result.output


def test_stats_command_after_import(runner: CliRunner, patched_env) -> None:
    """Stats after import shows non-zero bookmark count."""
    runner.invoke(cli, ["import", str(FIXTURE_PATH)])

    result = runner.invoke(cli, ["stats"])
    assert result.exit_code == 0, result.output

    import re

    match = re.search(r"Total bookmarks:\s+(\d+)", result.output)
    assert match is not None, f"Could not find total bookmarks in: {result.output}"
    assert int(match.group(1)) > 0


def test_stats_shows_date_range_when_data_present(
    runner: CliRunner, patched_env
) -> None:
    """Stats output includes date range after importing fixture data."""
    runner.invoke(cli, ["import", str(FIXTURE_PATH)])

    result = runner.invoke(cli, ["stats"])
    assert result.exit_code == 0, result.output
    # Date range is only shown when bookmarks are present
    assert "Date range:" in result.output


# ---------------------------------------------------------------------------
# --verbose flag
# ---------------------------------------------------------------------------


def test_verbose_flag_does_not_crash(runner: CliRunner, patched_env) -> None:
    """Running with --verbose before a subcommand does not raise errors."""
    result = runner.invoke(cli, ["--verbose", "stats"])
    assert result.exit_code == 0, result.output


def test_verbose_flag_with_import(runner: CliRunner, patched_env) -> None:
    """--verbose before import completes successfully."""
    result = runner.invoke(cli, ["--verbose", "import", str(FIXTURE_PATH)])
    assert result.exit_code == 0, result.output
    assert "Import complete:" in result.output


def test_verbose_short_flag(runner: CliRunner, patched_env) -> None:
    """-v (short form) works the same as --verbose."""
    result = runner.invoke(cli, ["-v", "stats"])
    assert result.exit_code == 0, result.output
