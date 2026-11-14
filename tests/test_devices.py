"""Tests for the NAS device, compose-project child devices, and stale-device cleanup."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.synology_manager import async_remove_config_entry_device
from custom_components.synology_manager.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.synology_manager.synology_client import (
    ContainerInfo,
    DsmUpdateInfo,
    PackageInfo,
    ProjectInfo,
    SynologyClient,
)

MOCK_CONFIG = {
    CONF_HOST: "192.168.1.100",
    CONF_PORT: 5001,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_SSL: True,
    CONF_VERIFY_SSL: False,
}


def _container(name: str, project: str) -> ContainerInfo:
    return ContainerInfo(
        name=name,
        display_name=name.title(),
        image=f"example/{name}:latest",
        installed_version="latest",
        latest_version=None,
        update_available=False,
        status="running",
        project_name=project,
    )


def _client(
    *,
    projects: list[ProjectInfo] | None = None,
    containers: list[ContainerInfo] | None = None,
    dsm_version: str = "DSM 7.4.1-86400",
) -> MagicMock:
    client = MagicMock()
    client.get_dsm_update.return_value = DsmUpdateInfo(
        installed_version=dsm_version,
        latest_version=None,
        update_available=False,
        release_notes=None,
        model="DS920+",
        serial="2010ABC123",
    )
    client.get_packages.return_value = [
        PackageInfo(
            package_id="HyperBackup",
            display_name="Hyper Backup",
            installed_version="4.1.0",
            latest_version="4.1.0",
            update_available=False,
            changelog=None,
            is_running=True,
        )
    ]
    client.get_projects.return_value = projects or []
    client.get_containers.return_value = containers or []
    client.group_container_updates = SynologyClient.group_container_updates
    client.configuration_url = "https://192.168.1.100:5001"
    client.has_docker = True
    return client


MEALIE = ProjectInfo(project_id="uuid-1", name="mealie", display_name="Mealie", status="RUNNING")


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="NAS", data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    return entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    with patch("custom_components.synology_manager.SynologyClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _nas_device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device is not None
    return device


def _child(hass: HomeAssistant, entry: MockConfigEntry, name: str):
    return dr.async_get(hass).async_get_child_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_project_{name}"), entry.entry_id
    )


def _seed_stale_project(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Register a NAS device with a child device for a project that no longer exists."""
    registry = dr.async_get(hass)
    nas = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}, name="Synology"
    )
    child = registry.async_get_or_create_child(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_project_oldproj")},
        name="Oldproj",
        parent_device_id=nas.id,
    )
    er.async_get(hass).async_get_or_create(
        "switch",
        DOMAIN,
        f"{entry.entry_id}_proj_uuid-old",
        config_entry=entry,
        device_id=child.id,
    )
    return child.id


async def test_nas_device_registered(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await _setup(hass, entry, _client())

    device = _nas_device(hass, entry)
    assert device.manufacturer == "Synology"
    assert device.model == "DS920+"
    assert device.serial_number == "2010ABC123"
    assert device.sw_version == "DSM 7.4.1-86400"
    assert device.configuration_url == "https://192.168.1.100:5001"
    assert device.name == "Synology"


async def test_entities_attach_to_nas_and_project_devices(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    client = _client(projects=[MEALIE], containers=[_container("mealie", "mealie")])
    await _setup(hass, entry, client)

    nas = _nas_device(hass, entry)
    project = _child(hass, entry, "mealie")
    assert project is not None
    assert project.parent_device_id == nas.id
    assert project.name == "Mealie"

    entities = er.async_get(hass)
    entry_id = entry.entry_id

    def device_of(platform: str, unique_id: str) -> str | None:
        entity_id = entities.async_get_entity_id(platform, DOMAIN, unique_id)
        assert entity_id is not None, unique_id
        return entities.async_get(entity_id).device_id

    assert device_of("switch", f"{entry_id}_proj_uuid-1") == project.id
    assert device_of("update", f"{entry_id}_proj_update_mealie") == project.id
    assert device_of("update", f"{entry_id}_dsm") == nas.id
    assert device_of("update", f"{entry_id}_pkg_HyperBackup") == nas.id
    assert device_of("switch", f"{entry_id}_pkgsw_HyperBackup") == nas.id
    assert device_of("button", f"{entry_id}_security_scan") == nas.id


async def test_stale_project_device_removed_on_setup(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    child_id = _seed_stale_project(hass, entry)

    await _setup(hass, entry, _client(projects=[MEALIE]))

    assert dr.async_get(hass).async_get(child_id) is None
    assert (
        er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_proj_uuid-old")
        is None
    )
    assert _child(hass, entry, "mealie") is not None


async def test_stale_device_kept_when_projects_source_failed(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    child_id = _seed_stale_project(hass, entry)
    client = _client()
    client.get_projects.side_effect = Exception("API error 1202")

    await _setup(hass, entry, client)

    assert dr.async_get(hass).async_get(child_id) is not None


async def test_stale_device_kept_without_container_manager(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    child_id = _seed_stale_project(hass, entry)
    client = _client()
    client.has_docker = False

    await _setup(hass, entry, client)

    assert dr.async_get(hass).async_get(child_id) is not None


async def test_manual_device_removal(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    client = _client(projects=[MEALIE])
    await _setup(hass, entry, client)
    registry = dr.async_get(hass)
    nas = _nas_device(hass, entry)
    mealie = _child(hass, entry, "mealie")
    gone = registry.async_get_or_create_child(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_project_gone")},
        name="Gone",
        parent_device_id=nas.id,
    )

    assert await async_remove_config_entry_device(hass, entry, gone) is True
    assert await async_remove_config_entry_device(hass, entry, mealie) is False
    assert await async_remove_config_entry_device(hass, entry, nas) is False


async def test_nas_sw_version_follows_dsm(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    client = _client()
    await _setup(hass, entry, client)

    client.get_dsm_update.return_value = DsmUpdateInfo(
        installed_version="DSM 7.4.2-86500",
        latest_version=None,
        update_available=False,
        release_notes=None,
    )
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _nas_device(hass, entry).sw_version == "DSM 7.4.2-86500"
