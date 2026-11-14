"""Tests for the NAS device, project and task child devices, and stale-device cleanup."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

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
    TaskInfo,
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
    tasks: list[TaskInfo] | None = None,
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
    client.get_tasks.return_value = tasks or []
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


LAST_RUN = datetime(2026, 11, 14, 6, 50, 1, tzinfo=UTC)
NEXT_RUN = datetime(2026, 11, 15, 6, 50, tzinfo=UTC)


def _kobo() -> TaskInfo:
    return TaskInfo(
        task_id=7,
        name="Download Kobo Books",
        task_type="script",
        real_owner="root",
        enabled=True,
        can_run=True,
        next_run=NEXT_RUN,
        last_run=LAST_RUN,
        last_exit_type="normal",
        last_exit_code=0,
    )


def _fix_ports() -> TaskInfo:
    return TaskInfo(
        task_id=1000,
        name="Fix ports",
        task_type="event_script",
        real_owner=None,
        enabled=True,
        can_run=True,
        next_run=None,
    )


def _task_entity(hass: HomeAssistant, entry: MockConfigEntry, platform: str, suffix: str):
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_task_{suffix}"
    )


def _task_device(hass: HomeAssistant, entry: MockConfigEntry, task_id: int):
    return dr.async_get(hass).async_get_child_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_task_{task_id}"), entry.entry_id
    )


async def test_task_devices_and_entities(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await _setup(hass, entry, _client(tasks=[_kobo(), _fix_ports()]))

    nas = _nas_device(hass, entry)
    kobo = _task_device(hass, entry, 7)
    assert kobo is not None
    assert kobo.parent_device_id == nas.id
    assert kobo.name == "Download Kobo Books"

    run = _task_entity(hass, entry, "button", "7_run")
    assert run == "button.synology_download_kobo_books_run"
    assert er.async_get(hass).async_get(run).device_id == kobo.id

    last_run = hass.states.get(_task_entity(hass, entry, "sensor", "7_last_run"))
    assert dt_util.parse_datetime(last_run.state) == LAST_RUN
    assert last_run.attributes["device_class"] == "timestamp"
    next_run = hass.states.get(_task_entity(hass, entry, "sensor", "7_next_run"))
    assert dt_util.parse_datetime(next_run.state) == NEXT_RUN
    result = hass.states.get(_task_entity(hass, entry, "sensor", "7_last_result"))
    assert result.state == "success"
    assert result.attributes["device_class"] == "enum"
    assert result.attributes["options"] == ["running", "success", "failed"]
    assert result.attributes["exit_type"] == "normal"
    assert "exit_code" not in result.attributes
    exit_code_id = _task_entity(hass, entry, "sensor", "7_last_exit_code")
    assert hass.states.get(exit_code_id).state == "0"
    assert er.async_get(hass).async_get(exit_code_id).entity_category == "diagnostic"

    # Triggered task: device and sensors, but no Run button.
    assert _task_device(hass, entry, 1000) is not None
    assert _task_entity(hass, entry, "button", "1000_run") is None
    assert hass.states.get(_task_entity(hass, entry, "sensor", "1000_next_run")).state == "unknown"


async def test_run_button_runs_task_and_follows_the_run(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    client = _client(tasks=[_kobo()])
    await _setup(hass, entry, client)
    started = int(dt_util.utcnow().timestamp())
    client.get_task_last_run.side_effect = [
        {"exit_code": 0, "exit_type": "running", "timestamp": str(started)},
        {"exit_code": 1, "exit_type": "normal", "timestamp": str(started)},
    ]

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.synology_download_kobo_books_run"}, blocking=True
    )
    client.run_task.assert_called_once_with(7, "root")

    result_id = _task_entity(hass, entry, "sensor", "7_last_result")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert hass.states.get(result_id).state == "running"
    exit_code_id = _task_entity(hass, entry, "sensor", "7_last_exit_code")
    assert hass.states.get(exit_code_id).state == "unknown"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=40))
    await hass.async_block_till_done()
    assert hass.states.get(result_id).state == "failed"
    assert hass.states.get(exit_code_id).state == "1"

    # Finished: no further checks.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=80))
    await hass.async_block_till_done()
    assert client.get_task_last_run.call_count == 2


async def test_run_button_failure_raises(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    client = _client(tasks=[_kobo()])
    client.run_task.side_effect = RuntimeError("Task 7 run failed: DSM error 119")
    await _setup(hass, entry, client)

    with pytest.raises(HomeAssistantError, match="DSM error 119"):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.synology_download_kobo_books_run"},
            blocking=True,
        )


async def test_stale_task_device_removed_on_setup(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    registry = dr.async_get(hass)
    nas = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}, name="Synology"
    )
    old = registry.async_get_or_create_child(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_task_99")},
        name="Deleted task",
        parent_device_id=nas.id,
    )

    await _setup(hass, entry, _client(tasks=[_kobo()]))

    assert registry.async_get(old.id) is None
    assert _task_device(hass, entry, 7) is not None


async def test_task_device_kept_when_tasks_source_failed(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    registry = dr.async_get(hass)
    nas = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}, name="Synology"
    )
    kept = registry.async_get_or_create_child(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_task_7")},
        name="Download Kobo Books",
        parent_device_id=nas.id,
    )
    client = _client()
    client.get_tasks.side_effect = Exception("Core Error: 119")

    await _setup(hass, entry, client)

    assert registry.async_get(kept.id) is not None
