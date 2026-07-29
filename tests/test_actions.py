"""Tests for the entity action failure-surfacing helper."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.synology_manager.actions import LOGS_URL, run_action


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(return_value="result")
    return hass


class TestRunAction:
    """Tests for run_action."""

    @pytest.mark.asyncio
    async def test_success_passes_through(self, mock_hass):
        """A successful call returns the executor result untouched."""
        func = MagicMock()

        result = await run_action(mock_hass, "entry1", "Updating DSM", func, "arg")

        assert result == "result"
        mock_hass.async_add_executor_job.assert_called_once_with(func, "arg")

    @pytest.mark.asyncio
    async def test_failure_raises_homeassistanterror_with_detail(self, mock_hass):
        """The popup message must carry the real cause and point at the logs."""
        err = Exception("")
        err.error_message = "Preserve for other purpose"
        err.error_code = 120
        mock_hass.async_add_executor_job = AsyncMock(side_effect=err)

        with (
            patch("custom_components.synology_manager.actions.persistent_notification") as mock_pn,
            pytest.raises(HomeAssistantError) as exc_info,
        ):
            await run_action(mock_hass, "entry1", "Updating package HyperBackup", MagicMock())

        msg = str(exc_info.value)
        assert "Updating package HyperBackup failed" in msg
        assert "DSM error 120: Preserve for other purpose" in msg
        assert "synology_manager" in msg
        # The notification carries a clickable link to the filtered logs page.
        mock_pn.async_create.assert_called_once()
        note = mock_pn.async_create.call_args
        assert LOGS_URL in note.kwargs["message"]
        assert note.kwargs["notification_id"] == "synology_manager_entry1_action_error"

    @pytest.mark.asyncio
    async def test_failure_logs_full_traceback_at_error(self, mock_hass, caplog):
        """The full traceback must land in the logs the popup points at."""
        mock_hass.async_add_executor_job = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch("custom_components.synology_manager.actions.persistent_notification"),
            caplog.at_level(logging.ERROR),
            pytest.raises(HomeAssistantError),
        ):
            await run_action(mock_hass, "entry1", "Starting project x", MagicMock())

        record = next(r for r in caplog.records if "Starting project x" in r.message)
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None
