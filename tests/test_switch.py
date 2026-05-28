"""Tests for Synology Manager switch entities."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.synology_manager.switch import (
    SynologyPackageSwitchEntity,
    SynologyProjectSwitchEntity,
)
from custom_components.synology_manager.synology_client import PackageInfo, ProjectInfo


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with sample data."""
    coordinator = MagicMock()
    coordinator.data = {
        "packages": [
            PackageInfo(
                package_id="ContainerManager",
                display_name="Container Manager",
                installed_version="20.10.23",
                latest_version="20.10.23",
                update_available=False,
                changelog=None,
                is_running=True,
            ),
            PackageInfo(
                package_id="HyperBackup",
                display_name="Hyper Backup",
                installed_version="4.1.0",
                latest_version="4.1.0",
                update_available=False,
                changelog=None,
                is_running=False,
            ),
        ],
        "projects": [
            ProjectInfo(
                project_id="abc-123-uuid",
                name="mealie",
                display_name="Mealie",
                status="RUNNING",
            ),
            ProjectInfo(
                project_id="def-456-uuid",
                name="rallly",
                display_name="Rallly",
                status="STOPPED",
            ),
        ],
    }
    coordinator.client = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.entry_id = "test_entry_id"
    coordinator.server_name = "Test Nas"
    return coordinator


class TestPackageSwitchEntity:
    """Tests for the package switch entity."""

    def test_name_uses_display_name(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "ContainerManager")
        assert entity.name == "Test Nas Container Manager"

    def test_name_falls_back_to_package_id(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "UnknownPkg")
        assert entity.name == "Test Nas UnknownPkg"

    def test_unique_id(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "ContainerManager")
        assert entity.unique_id == "test_entry_id_pkgsw_ContainerManager"

    def test_is_on_when_running(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "ContainerManager")
        assert entity.is_on is True

    def test_is_off_when_stopped(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "HyperBackup")
        assert entity.is_on is False

    def test_is_on_none_when_package_missing(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "GhostPkg")
        assert entity.is_on is None

    def test_optimistic_state_overrides_actual(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "HyperBackup")
        assert entity.is_on is False
        entity._optimistic_state = True
        assert entity.is_on is True

    @pytest.mark.asyncio
    async def test_turn_on(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "HyperBackup")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_on()

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.start_package, "HyperBackup"
        )
        mock_coordinator.async_request_refresh.assert_awaited_once()
        assert entity._optimistic_state is None

    @pytest.mark.asyncio
    async def test_turn_off(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "ContainerManager")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_off()

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.stop_package, "ContainerManager"
        )
        assert entity._optimistic_state is None

    @pytest.mark.asyncio
    async def test_optimistic_state_cleared_on_error(self, mock_coordinator):
        entity = SynologyPackageSwitchEntity(mock_coordinator, "HyperBackup")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock(side_effect=Exception("API error"))
        entity.async_write_ha_state = MagicMock()

        with pytest.raises(Exception, match="API error"):
            await entity.async_turn_on()

        assert entity._optimistic_state is None


class TestProjectSwitchEntity:
    """Tests for the project switch entity."""

    def test_name_uses_display_name(self, mock_coordinator):
        entity = SynologyProjectSwitchEntity(mock_coordinator, "abc-123-uuid")
        assert entity.name == "Test Nas Mealie"

    def test_unique_id(self, mock_coordinator):
        entity = SynologyProjectSwitchEntity(mock_coordinator, "abc-123-uuid")
        assert entity.unique_id == "test_entry_id_proj_abc-123-uuid"

    def test_is_on_when_running(self, mock_coordinator):
        entity = SynologyProjectSwitchEntity(mock_coordinator, "abc-123-uuid")
        assert entity.is_on is True

    def test_is_off_when_stopped(self, mock_coordinator):
        entity = SynologyProjectSwitchEntity(mock_coordinator, "def-456-uuid")
        assert entity.is_on is False

    def test_is_on_none_when_project_missing(self, mock_coordinator):
        entity = SynologyProjectSwitchEntity(mock_coordinator, "nonexistent")
        assert entity.is_on is None

    def test_optimistic_state_overrides_actual(self, mock_coordinator):
        entity = SynologyProjectSwitchEntity(mock_coordinator, "def-456-uuid")
        assert entity.is_on is False
        entity._optimistic_state = True
        assert entity.is_on is True

    @pytest.mark.asyncio
    async def test_turn_on_calls_start_project(self, mock_coordinator):
        entity = SynologyProjectSwitchEntity(mock_coordinator, "def-456-uuid")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_on()

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.start_project, "def-456-uuid"
        )
        mock_coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_off_calls_stop_project(self, mock_coordinator):
        entity = SynologyProjectSwitchEntity(mock_coordinator, "abc-123-uuid")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_turn_off()

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.stop_project, "abc-123-uuid"
        )

    @pytest.mark.asyncio
    async def test_optimistic_state_cleared_on_error(self, mock_coordinator):
        entity = SynologyProjectSwitchEntity(mock_coordinator, "abc-123-uuid")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock(side_effect=Exception("1202"))
        entity.async_write_ha_state = MagicMock()

        with pytest.raises(Exception, match="1202"):
            await entity.async_turn_off()

        assert entity._optimistic_state is None
