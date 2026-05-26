"""Tests for Synology Upgrades update entities."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.update import UpdateEntityFeature

from custom_components.synology_upgrades.synology_client import (
    ContainerInfo,
    DsmUpdateInfo,
    PackageInfo,
)
from custom_components.synology_upgrades.update import (
    SynologyContainerUpdateEntity,
    SynologyDSMUpdateEntity,
    SynologyPackageUpdateEntity,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with sample data."""
    coordinator = MagicMock()
    coordinator.data = {
        "dsm": DsmUpdateInfo(
            installed_version="7.2.1-69057",
            latest_version="7.2.2-72806",
            update_available=True,
            release_notes="Bug fixes and improvements",
        ),
        "packages": [
            PackageInfo(
                package_id="HyperBackup",
                display_name="Hyper Backup",
                installed_version="4.1.0-3735",
                latest_version="4.1.1-3740",
                update_available=True,
            ),
            PackageInfo(
                package_id="SynologyDrive",
                display_name="Synology Drive Server",
                installed_version="3.5.0",
                latest_version="3.5.0",
                update_available=False,
            ),
        ],
        "containers": [
            ContainerInfo(
                name="homeassistant",
                image="ghcr.io/home-assistant/home-assistant:2024.1",
                installed_version="2024.1",
                latest_version="2024.1",
                update_available=False,
                status="running",
            ),
        ],
    }
    coordinator.client = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.entry_id = "test_entry_id"
    return coordinator


class TestDSMUpdateEntity:
    """Tests for the DSM firmware update entity."""

    def test_properties(self, mock_coordinator):
        """Test DSM entity properties."""
        entity = SynologyDSMUpdateEntity(mock_coordinator)

        assert entity.installed_version == "7.2.1-69057"
        assert entity.latest_version == "7.2.2-72806"
        assert entity.title == "DSM"
        assert UpdateEntityFeature.INSTALL in entity.supported_features

    def test_no_update_available(self, mock_coordinator):
        """Test DSM entity when up to date."""
        mock_coordinator.data["dsm"] = DsmUpdateInfo(
            installed_version="7.2.2-72806",
            latest_version=None,
            update_available=False,
            release_notes=None,
        )
        entity = SynologyDSMUpdateEntity(mock_coordinator)

        assert entity.installed_version == "7.2.2-72806"
        assert entity.latest_version == "7.2.2-72806"

    def test_dsm_data_none(self, mock_coordinator):
        """Test DSM entity when DSM data fetch failed."""
        mock_coordinator.data["dsm"] = None
        entity = SynologyDSMUpdateEntity(mock_coordinator)

        assert entity.installed_version is None
        assert entity.latest_version is None

    @pytest.mark.asyncio
    async def test_install(self, mock_coordinator):
        """Test triggering DSM upgrade."""
        entity = SynologyDSMUpdateEntity(mock_coordinator)
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.upgrade_dsm
        )


class TestPackageUpdateEntity:
    """Tests for the package update entity."""

    def test_properties(self, mock_coordinator):
        """Test package entity properties."""
        pkg = mock_coordinator.data["packages"][0]
        entity = SynologyPackageUpdateEntity(mock_coordinator, pkg.package_id)

        assert entity.installed_version == "4.1.0-3735"
        assert entity.latest_version == "4.1.1-3740"
        assert entity.title == "Hyper Backup"
        assert UpdateEntityFeature.INSTALL in entity.supported_features

    def test_up_to_date_package(self, mock_coordinator):
        """Test package entity when up to date."""
        pkg = mock_coordinator.data["packages"][1]
        entity = SynologyPackageUpdateEntity(mock_coordinator, pkg.package_id)

        assert entity.installed_version == "3.5.0"
        assert entity.latest_version == "3.5.0"

    @pytest.mark.asyncio
    async def test_install_triggers_security_scan(self, mock_coordinator):
        """Test that package install triggers security scan after."""
        pkg = mock_coordinator.data["packages"][0]
        entity = SynologyPackageUpdateEntity(mock_coordinator, pkg.package_id)
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        calls = entity.hass.async_add_executor_job.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == mock_coordinator.client.upgrade_package
        assert calls[0].args[1] == "HyperBackup"
        assert calls[1].args[0] == mock_coordinator.client.trigger_security_scan


class TestContainerUpdateEntity:
    """Tests for the container update entity."""

    def test_properties(self, mock_coordinator):
        """Test container entity properties."""
        ctr = mock_coordinator.data["containers"][0]
        entity = SynologyContainerUpdateEntity(mock_coordinator, ctr.name)

        assert entity.installed_version == "2024.1"
        assert entity.title == "homeassistant"
        assert UpdateEntityFeature.INSTALL in entity.supported_features

    @pytest.mark.asyncio
    async def test_install(self, mock_coordinator):
        """Test triggering container update."""
        ctr = mock_coordinator.data["containers"][0]
        entity = SynologyContainerUpdateEntity(mock_coordinator, ctr.name)
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.update_container,
            "homeassistant",
            "ghcr.io/home-assistant/home-assistant:2024.1",
        )
