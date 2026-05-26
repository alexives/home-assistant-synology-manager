"""Shared test fixtures for Synology Upgrades integration tests."""

import pathlib
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    yield


@pytest.fixture(autouse=True)
def fix_custom_components_path():
    """Remove non-existent placeholder paths from custom_components.__path__."""
    import custom_components

    original_path = list(custom_components.__path__)
    real_paths = list(dict.fromkeys(p for p in original_path if pathlib.Path(p).is_dir()))
    custom_components.__path__ = real_paths
    yield
    custom_components.__path__ = original_path


@pytest.fixture(autouse=True)
def mock_process_deps_reqs():
    """Bypass integration dependency loading in tests."""
    with patch(
        "homeassistant.config_entries.async_process_deps_reqs",
        new_callable=AsyncMock,
    ):
        yield
