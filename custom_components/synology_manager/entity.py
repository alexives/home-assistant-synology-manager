"""Device registry helpers and the base entity for Synology Manager.

Every entity hangs off one NAS device. Compose projects get a child device
(HA 2026.9+ ``ChildDeviceInfo``) under it, holding the project's switch and
update entities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .synology_client import _prettify

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import SynologyManagerCoordinator

PROJECT_KEY = "project"

# Child device kinds: identifier key segment -> (coordinator sources that must
# have succeeded before a missing item counts as gone, live-name extractor).
_CHILD_KINDS: dict[str, tuple[frozenset[str], Any]] = {
    PROJECT_KEY: (
        frozenset({"containers", "projects"}),
        lambda data: (
            {p.name for p in data.get("projects", [])}
            | {pu.project_name for pu in data.get("project_updates", [])}
        ),
    ),
}


def child_identifier(entry_id: str, kind: str, name: str) -> str:
    """Device identifier for a child device, e.g. ``<entry>_project_immich``."""
    return f"{entry_id}_{kind}_{name}"


def nas_device_info(coordinator: SynologyManagerCoordinator) -> DeviceInfo:
    """Device info linking an entity to the NAS device registered at setup."""
    return DeviceInfo(identifiers={(DOMAIN, coordinator.config_entry.entry_id)})


def project_device_info(
    coordinator: SynologyManagerCoordinator, project_name: str
) -> ChildDeviceInfo:
    """Child device info for a compose project."""
    entry_id = coordinator.config_entry.entry_id
    return ChildDeviceInfo(
        identifiers={(DOMAIN, child_identifier(entry_id, PROJECT_KEY, project_name))},
        name=_prettify(project_name),
        parent_device_id=coordinator.nas_device_id,
    )


def register_nas_device(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: SynologyManagerCoordinator
) -> str:
    """Create or update the NAS device and return its device id."""
    dsm = coordinator.data.get("dsm")
    client = coordinator.client
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Synology",
        name=coordinator.server_name,
        model=dsm.model if dsm else None,
        serial_number=dsm.serial if dsm else None,
        sw_version=dsm.installed_version if dsm else None,
        configuration_url=client.configuration_url,
    )
    return device.id


def update_nas_sw_version(hass: HomeAssistant, coordinator: SynologyManagerCoordinator) -> None:
    """Keep the NAS device's firmware version in step with the DSM source."""
    dsm = coordinator.data.get("dsm")
    if dsm is None or not dsm.installed_version:
        return
    registry = dr.async_get(hass)
    device = registry.async_get(coordinator.nas_device_id)
    if device is not None and device.sw_version != dsm.installed_version:
        registry.async_update_device(device.id, sw_version=dsm.installed_version)


def _child_kind(entry_id: str, device: dr.DeviceEntry) -> tuple[str, str] | None:
    """Return (kind, identifier) for one of this entry's child devices, else None."""
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        for kind in _CHILD_KINDS:
            if identifier.startswith(f"{entry_id}_{kind}_"):
                return kind, identifier
    return None


def child_device_is_stale(coordinator: SynologyManagerCoordinator, device: dr.DeviceEntry) -> bool:
    """True when the device is a child whose project/task no longer exists on the NAS.

    A source that failed this cycle falls back to an empty list, so a child
    only counts as gone when every source behind its kind succeeded.
    """
    entry_id = coordinator.config_entry.entry_id
    found = _child_kind(entry_id, device)
    if found is None:
        return False
    kind, identifier = found
    sources, live_names = _CHILD_KINDS[kind]
    data = coordinator.data or {}
    if sources & set(data.get("failed_sources", sources)):
        return False
    live = {child_identifier(entry_id, kind, name) for name in live_names(data)}
    return identifier not in live


def remove_stale_child_devices(
    hass: HomeAssistant, coordinator: SynologyManagerCoordinator
) -> None:
    """Remove child devices (and their entities) for items deleted on the NAS."""
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_parent_device(registry, coordinator.nas_device_id):
        if child_device_is_stale(coordinator, device):
            registry.async_remove_device(device.id)


class SynologyManagerEntity(CoordinatorEntity["SynologyManagerCoordinator"]):
    """Base entity: attaches to the NAS device unless a subclass sets a child device."""

    def __init__(self, coordinator: SynologyManagerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = nas_device_info(coordinator)
