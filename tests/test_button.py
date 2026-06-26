"""Tests for Synology Manager button entities."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.synology_manager.button import SynologySecurityScanButtonEntity


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.client = MagicMock()
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.entry_id = "test_entry_id"
    coordinator.server_name = "Test Nas"
    return coordinator


class TestSecurityScanButton:
    """Tests for the manual Security Advisor scan button."""

    def test_unique_id_and_name(self, mock_coordinator):
        entity = SynologySecurityScanButtonEntity(mock_coordinator)
        assert entity.unique_id == "test_entry_id_security_scan"
        assert entity.name == "Test Nas Security Scan"

    @pytest.mark.asyncio
    async def test_press_triggers_security_scan(self, mock_coordinator):
        """Pressing the button runs the client's security scan trigger."""
        entity = SynologySecurityScanButtonEntity(mock_coordinator)
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_press()

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.trigger_security_scan
        )
