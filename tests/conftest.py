"""Shared pytest fixtures."""

import json
from pathlib import Path

import pytest

from src.db import Database


@pytest.fixture
def db(tmp_path):
    """Fresh database for each test."""
    db_path = str(tmp_path / "test.db")
    return Database(db_path)


@pytest.fixture
def sample_export():
    """Load sample export fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_export.json"
    with open(fixture_path) as f:
        return json.load(f)
