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

    @pytest.mark.asyncio
    async def test_press_failure_surfaces_as_popup_and_notification(self, mock_coordinator):
        """A failed scan must produce an error popup, not a silent no-op."""
        from unittest.mock import patch

        from homeassistant.exceptions import HomeAssistantError

        entity = SynologySecurityScanButtonEntity(mock_coordinator)
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock(
            side_effect=RuntimeError("Security scan start failed: DSM error 119")
        )

        with (
            patch("custom_components.synology_manager.actions.persistent_notification") as mock_pn,
            pytest.raises(HomeAssistantError, match="DSM error 119"),
        ):
            await entity.async_press()

        mock_pn.async_create.assert_called_once()
