"""Switch entities for Synology Manager packages and compose projects."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SynologyManagerCoordinator
from .synology_client import PackageInfo, ProjectInfo


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Synology Manager switch entities."""
    coordinator: SynologyManagerCoordinator = entry.runtime_data.coordinator
    entities: list[SwitchEntity] = []

    known_packages: set[str] = set()
    for pkg in coordinator.data.get("packages", []):
        if pkg.is_running is not None:
            known_packages.add(pkg.package_id)
            entities.append(SynologyPackageSwitchEntity(coordinator, pkg.package_id))

    known_projects: set[str] = set()
    for proj in coordinator.data.get("projects", []):
        known_projects.add(proj.project_id)
        entities.append(SynologyProjectSwitchEntity(coordinator, proj.project_id))

    async_add_entities(entities)

    def _async_add_new_entities() -> None:
        new_entities: list[SwitchEntity] = []
        for pkg in coordinator.data.get("packages", []):
            if pkg.is_running is not None and pkg.package_id not in known_packages:
                known_packages.add(pkg.package_id)
                new_entities.append(SynologyPackageSwitchEntity(coordinator, pkg.package_id))
        for proj in coordinator.data.get("projects", []):
            if proj.project_id not in known_projects:
                known_projects.add(proj.project_id)
                new_entities.append(SynologyProjectSwitchEntity(coordinator, proj.project_id))
        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(_async_add_new_entities)


class SynologyPackageSwitchEntity(CoordinatorEntity[SynologyManagerCoordinator], SwitchEntity):
    """Switch entity for a Synology package."""

    _optimistic_state: bool | None = None

    def __init__(self, coordinator: SynologyManagerCoordinator, package_id: str) -> None:
        super().__init__(coordinator)
        self._package_id = package_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_pkgsw_{package_id}"

    def _get_package(self) -> PackageInfo | None:
        for pkg in self.coordinator.data.get("packages", []):
            if pkg.package_id == self._package_id:
                return pkg
        return None

    @property
    def name(self) -> str:
        pkg = self._get_package()
        label = pkg.display_name if pkg else self._package_id
        return f"{self.coordinator.server_name} {label}"

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        pkg = self._get_package()
        if pkg is None:
            return None
        return pkg.is_running

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._optimistic_state = True
        self.async_write_ha_state()
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.client.start_package, self._package_id
            )
        finally:
            self._optimistic_state = None
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._optimistic_state = False
        self.async_write_ha_state()
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.client.stop_package, self._package_id
            )
        finally:
            self._optimistic_state = None
        await self.coordinator.async_request_refresh()


class SynologyProjectSwitchEntity(CoordinatorEntity[SynologyManagerCoordinator], SwitchEntity):
    """Switch entity for a Docker compose project."""

    _optimistic_state: bool | None = None

    def __init__(self, coordinator: SynologyManagerCoordinator, project_id: str) -> None:
        super().__init__(coordinator)
        self._project_id = project_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_proj_{project_id}"

    def _get_project(self) -> ProjectInfo | None:
        for proj in self.coordinator.data.get("projects", []):
            if proj.project_id == self._project_id:
                return proj
        return None

    @property
    def name(self) -> str:
        proj = self._get_project()
        label = proj.display_name if proj else self._project_id
        return f"{self.coordinator.server_name} {label}"

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        proj = self._get_project()
        if proj is None:
            return None
        return proj.status.lower() == "running"

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._optimistic_state = True
        self.async_write_ha_state()
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.client.start_project, self._project_id
            )
        finally:
            self._optimistic_state = None
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._optimistic_state = False
        self.async_write_ha_state()
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.client.stop_project, self._project_id
            )
        finally:
            self._optimistic_state = None
        await self.coordinator.async_request_refresh()
