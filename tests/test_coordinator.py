"""Tests for the Synology Manager coordinator."""

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.synology_manager.coordinator import SynologyManagerCoordinator
from custom_components.synology_manager.synology_client import (
    ContainerInfo,
    DsmUpdateInfo,
    PackageInfo,
    ProjectInfo,
    SynologyClient,
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
            changelog="<h4>Bug fixes</h4>",
            is_running=True,
        ),
    ]
    client.get_containers.return_value = [
        ContainerInfo(
            name="homeassistant",
            display_name="Homeassistant",
            image="ghcr.io/home-assistant/home-assistant:2024.1",
            installed_version="2024.1",
            latest_version="2024.1",
            update_available=False,
            status="running",
            project_name="ha",
        ),
    ]
    client.get_projects.return_value = [
        ProjectInfo(
            project_id="1",
            name="ha",
            display_name="Ha",
            status="running",
        ),
    ]
    client.group_container_updates = SynologyClient.group_container_updates
    return client


async def test_coordinator_fetches_all_sources(hass: HomeAssistant, mock_client) -> None:
    """Test that coordinator fetches DSM, packages, and containers."""
    coordinator = SynologyManagerCoordinator(hass, mock_client, "Test Nas")
    await coordinator.async_refresh()

    assert coordinator.data["dsm"].installed_version == "7.2.1-69057"
    assert coordinator.data["dsm"].update_available is True
    assert len(coordinator.data["packages"]) == 1
    assert coordinator.data["packages"][0].package_id == "HyperBackup"
    assert len(coordinator.data["project_updates"]) == 1
    assert coordinator.data["project_updates"][0].project_name == "ha"
    assert len(coordinator.data["standalone_containers"]) == 0


async def test_coordinator_dsm_failure_preserves_other_data(
    hass: HomeAssistant, mock_client
) -> None:
    """Test that DSM failure doesn't block packages and containers."""
    mock_client.get_dsm_update.side_effect = Exception("DSM API down")

    coordinator = SynologyManagerCoordinator(hass, mock_client, "Test Nas")
    await coordinator.async_refresh()

    assert coordinator.data["dsm"] is None
    assert len(coordinator.data["packages"]) == 1
    assert len(coordinator.data["project_updates"]) == 1


async def test_coordinator_packages_failure_preserves_other_data(
    hass: HomeAssistant, mock_client
) -> None:
    """Test that package failure doesn't block DSM and containers."""
    mock_client.get_packages.side_effect = Exception("Package API down")

    coordinator = SynologyManagerCoordinator(hass, mock_client, "Test Nas")
    await coordinator.async_refresh()

    assert coordinator.data["dsm"] is not None
    assert coordinator.data["packages"] == []
    assert len(coordinator.data["project_updates"]) == 1


async def test_coordinator_all_fail_raises(hass: HomeAssistant, mock_client) -> None:
    """Test that coordinator raises UpdateFailed when all sources fail."""
    mock_client.get_dsm_update.side_effect = Exception("DSM down")
    mock_client.get_packages.side_effect = Exception("Packages down")
    mock_client.get_containers.side_effect = Exception("Docker down")
    mock_client.get_projects.side_effect = Exception("Projects down")

    coordinator = SynologyManagerCoordinator(hass, mock_client, "Test Nas")
    await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, UpdateFailed)
