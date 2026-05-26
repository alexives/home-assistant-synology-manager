"""Update entities for Synology Upgrades."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SynologyUpgradesCoordinator
from .synology_client import ContainerInfo, PackageInfo


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Synology Upgrades update entities."""
    coordinator: SynologyUpgradesCoordinator = entry.runtime_data.coordinator
    entities: list[UpdateEntity] = []

    entities.append(SynologyDSMUpdateEntity(coordinator))

    for pkg in coordinator.data.get("packages", []):
        entities.append(SynologyPackageUpdateEntity(coordinator, pkg.package_id))

    for ctr in coordinator.data.get("containers", []):
        entities.append(SynologyContainerUpdateEntity(coordinator, ctr.name))

    async_add_entities(entities)


class SynologyDSMUpdateEntity(CoordinatorEntity[SynologyUpgradesCoordinator], UpdateEntity):
    """Update entity for DSM firmware."""

    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: SynologyUpgradesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_dsm"

    @property
    def title(self) -> str:
        return "DSM"

    @property
    def installed_version(self) -> str | None:
        dsm = self.coordinator.data.get("dsm")
        if dsm is None:
            return None
        return dsm.installed_version

    @property
    def latest_version(self) -> str | None:
        dsm = self.coordinator.data.get("dsm")
        if dsm is None:
            return None
        if dsm.latest_version is None:
            return dsm.installed_version
        return dsm.latest_version

    async def async_release_notes(self) -> str | None:
        dsm = self.coordinator.data.get("dsm")
        if dsm is None:
            return None
        return dsm.release_notes

    async def async_install(self, version: str | None, backup: bool | None, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.client.upgrade_dsm)
        await self.coordinator.async_request_refresh()


class SynologyPackageUpdateEntity(CoordinatorEntity[SynologyUpgradesCoordinator], UpdateEntity):
    """Update entity for a Synology package."""

    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, coordinator: SynologyUpgradesCoordinator, package_id: str) -> None:
        super().__init__(coordinator)
        self._package_id = package_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_pkg_{package_id}"

    def _get_package(self) -> PackageInfo | None:
        for pkg in self.coordinator.data.get("packages", []):
            if pkg.package_id == self._package_id:
                return pkg
        return None

    @property
    def title(self) -> str:
        pkg = self._get_package()
        return pkg.display_name if pkg else self._package_id

    @property
    def installed_version(self) -> str | None:
        pkg = self._get_package()
        return pkg.installed_version if pkg else None

    @property
    def latest_version(self) -> str | None:
        pkg = self._get_package()
        return pkg.latest_version if pkg else None

    async def async_install(self, version: str | None, backup: bool | None, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.client.upgrade_package, self._package_id
        )
        await self.hass.async_add_executor_job(self.coordinator.client.trigger_security_scan)
        await self.coordinator.async_request_refresh()


class SynologyContainerUpdateEntity(CoordinatorEntity[SynologyUpgradesCoordinator], UpdateEntity):
    """Update entity for a Docker container."""

    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, coordinator: SynologyUpgradesCoordinator, container_name: str) -> None:
        super().__init__(coordinator)
        self._container_name = container_name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_ctr_{container_name}"

    def _get_container(self) -> ContainerInfo | None:
        for ctr in self.coordinator.data.get("containers", []):
            if ctr.name == self._container_name:
                return ctr
        return None

    @property
    def title(self) -> str:
        return self._container_name

    @property
    def installed_version(self) -> str | None:
        ctr = self._get_container()
        return ctr.installed_version if ctr else None

    @property
    def latest_version(self) -> str | None:
        ctr = self._get_container()
        return ctr.latest_version if ctr else None

    async def async_install(self, version: str | None, backup: bool | None, **kwargs: Any) -> None:
        ctr = self._get_container()
        if ctr is None:
            return
        await self.hass.async_add_executor_job(
            self.coordinator.client.update_container,
            self._container_name,
            ctr.image,
        )
        await self.coordinator.async_request_refresh()
