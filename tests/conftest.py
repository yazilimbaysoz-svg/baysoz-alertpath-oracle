"""Shared fixtures for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

from pathlib import Path

import pytest

from baysoz_alertpath import load_config

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


@pytest.fixture
def example_config():
    return load_config(EXAMPLES / "alertmanager.yml")


@pytest.fixture
def example_alerts_path():
    return EXAMPLES / "alerts.json"


@pytest.fixture
def example_fixtures_path():
    return EXAMPLES / "fixtures.json"
