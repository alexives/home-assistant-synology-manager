"""Tests for the Synology Upgrades coordinator."""

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.synology_upgrades.coordinator import SynologyUpgradesCoordinator
from custom_components.synology_upgrades.synology_client import (
    ContainerInfo,
    DsmUpdateInfo,
    PackageInfo,
)


@pytest.fixture
def mock_client():
    """Create a mock SynologyClient."""
    client = MagicMock()
    client.get_dsm_update.return_value = DsmUpdateInfo(
        installed_version="7.2.1-69057",
        latest_version="7.2.2-72806",
        update_available=True,
        release_notes="Bug fixes",
    )
    client.get_packages.return_value = [
        PackageInfo(
            package_id="HyperBackup",
            display_name="Hyper Backup",
            installed_version="4.1.0-3735",
            latest_version="4.1.1-3740",
            update_available=True,
        ),
    ]
    client.get_containers.return_value = [
        ContainerInfo(
            name="homeassistant",
            image="ghcr.io/home-assistant/home-assistant:2024.1",
            installed_version="2024.1",
            latest_version="2024.1",
            update_available=False,
            status="running",
        ),
    ]
    return client


async def test_coordinator_fetches_all_sources(hass: HomeAssistant, mock_client) -> None:
    """Test that coordinator fetches DSM, packages, and containers."""
    coordinator = SynologyUpgradesCoordinator(hass, mock_client)
    await coordinator.async_refresh()

    assert coordinator.data["dsm"].installed_version == "7.2.1-69057"
    assert coordinator.data["dsm"].update_available is True
    assert len(coordinator.data["packages"]) == 1
    assert coordinator.data["packages"][0].package_id == "HyperBackup"
    assert len(coordinator.data["containers"]) == 1
    assert coordinator.data["containers"][0].name == "homeassistant"


async def test_coordinator_dsm_failure_preserves_other_data(
    hass: HomeAssistant, mock_client
) -> None:
    """Test that DSM failure doesn't block packages and containers."""
    mock_client.get_dsm_update.side_effect = Exception("DSM API down")

    coordinator = SynologyUpgradesCoordinator(hass, mock_client)
    await coordinator.async_refresh()

    assert coordinator.data["dsm"] is None
    assert len(coordinator.data["packages"]) == 1
    assert len(coordinator.data["containers"]) == 1


async def test_coordinator_packages_failure_preserves_other_data(
    hass: HomeAssistant, mock_client
) -> None:
    """Test that package failure doesn't block DSM and containers."""
    mock_client.get_packages.side_effect = Exception("Package API down")

    coordinator = SynologyUpgradesCoordinator(hass, mock_client)
    await coordinator.async_refresh()

    assert coordinator.data["dsm"] is not None
    assert coordinator.data["packages"] == []
    assert len(coordinator.data["containers"]) == 1


async def test_coordinator_all_fail_raises(hass: HomeAssistant, mock_client) -> None:
    """Test that coordinator raises UpdateFailed when all sources fail."""
    mock_client.get_dsm_update.side_effect = Exception("DSM down")
    mock_client.get_packages.side_effect = Exception("Packages down")
    mock_client.get_containers.side_effect = Exception("Docker down")

    coordinator = SynologyUpgradesCoordinator(hass, mock_client)
    await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, UpdateFailed)
