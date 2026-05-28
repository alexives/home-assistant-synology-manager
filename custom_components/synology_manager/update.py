"""Update entities for Synology Manager."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SynologyManagerCoordinator
from .synology_client import ContainerInfo, PackageInfo, ProjectUpdateInfo


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Synology Manager update entities."""
    coordinator: SynologyManagerCoordinator = entry.runtime_data.coordinator
    entities: list[UpdateEntity] = []

    entities.append(SynologyDSMUpdateEntity(coordinator))

    known_packages: set[str] = set()
    for pkg in coordinator.data.get("packages", []):
        known_packages.add(pkg.package_id)
        entities.append(SynologyPackageUpdateEntity(coordinator, pkg.package_id))

    known_projects: set[str] = set()
    for pu in coordinator.data.get("project_updates", []):
        known_projects.add(pu.project_name)
        entities.append(SynologyProjectUpdateEntity(coordinator, pu.project_name))

    known_standalone: set[str] = set()
    for ctr in coordinator.data.get("standalone_containers", []):
        known_standalone.add(ctr.name)
        entities.append(SynologyContainerUpdateEntity(coordinator, ctr.name))

    async_add_entities(entities)

    def _async_add_new_entities() -> None:
        """Add entities for newly discovered packages, projects, and containers."""
        new_entities: list[UpdateEntity] = []
        for pkg in coordinator.data.get("packages", []):
            if pkg.package_id not in known_packages:
                known_packages.add(pkg.package_id)
                new_entities.append(SynologyPackageUpdateEntity(coordinator, pkg.package_id))
        for pu in coordinator.data.get("project_updates", []):
            if pu.project_name not in known_projects:
                known_projects.add(pu.project_name)
                new_entities.append(SynologyProjectUpdateEntity(coordinator, pu.project_name))
        for ctr in coordinator.data.get("standalone_containers", []):
            if ctr.name not in known_standalone:
                known_standalone.add(ctr.name)
                new_entities.append(SynologyContainerUpdateEntity(coordinator, ctr.name))
        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(_async_add_new_entities)


class SynologyDSMUpdateEntity(CoordinatorEntity[SynologyManagerCoordinator], UpdateEntity):
    """Update entity for DSM firmware."""

    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: SynologyManagerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_dsm"
        self._attr_name = f"{coordinator.server_name} DSM"

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


class SynologyPackageUpdateEntity(CoordinatorEntity[SynologyManagerCoordinator], UpdateEntity):
    """Update entity for a Synology package."""

    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: SynologyManagerCoordinator, package_id: str) -> None:
        super().__init__(coordinator)
        self._package_id = package_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_pkg_{package_id}"

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

    async def async_release_notes(self) -> str | None:
        pkg = self._get_package()
        if pkg is None:
            return None
        return pkg.changelog

    async def async_install(self, version: str | None, backup: bool | None, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.client.upgrade_package, self._package_id
        )
        await self.hass.async_add_executor_job(self.coordinator.client.trigger_security_scan)
        await self.coordinator.async_request_refresh()


class SynologyProjectUpdateEntity(CoordinatorEntity[SynologyManagerCoordinator], UpdateEntity):
    """Update entity for a Docker compose project (all containers combined)."""

    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: SynologyManagerCoordinator, project_name: str) -> None:
        super().__init__(coordinator)
        self._project_name = project_name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_proj_update_{project_name}"

    def _get_project_update(self) -> ProjectUpdateInfo | None:
        for pu in self.coordinator.data.get("project_updates", []):
            if pu.project_name == self._project_name:
                return pu
        return None

    @property
    def name(self) -> str:
        pu = self._get_project_update()
        label = pu.display_name if pu else self._project_name
        return f"{self.coordinator.server_name} {label}"

    @property
    def title(self) -> str:
        pu = self._get_project_update()
        return pu.display_name if pu else self._project_name

    @property
    def installed_version(self) -> str | None:
        pu = self._get_project_update()
        if pu is None:
            return None
        versions = [c.installed_version for c in pu.containers]
        return ", ".join(versions)

    @property
    def latest_version(self) -> str | None:
        pu = self._get_project_update()
        if pu is None:
            return None
        versions = [c.latest_version or c.installed_version for c in pu.containers]
        return ", ".join(versions)

    async def async_release_notes(self) -> str | None:
        pu = self._get_project_update()
        if pu is None:
            return None
        parts = []
        for ctr in pu.containers:
            parts.append(f"**{ctr.display_name}**: {_container_release_notes(ctr.image)}")
        return "<br>".join(parts)

    async def async_install(self, version: str | None, backup: bool | None, **kwargs: Any) -> None:
        pu = self._get_project_update()
        if pu is None or pu.project_id is None:
            return
        await self.hass.async_add_executor_job(
            self.coordinator.client.update_project, pu.project_id, pu.images
        )
        await self.coordinator.async_request_refresh()


class SynologyContainerUpdateEntity(CoordinatorEntity[SynologyManagerCoordinator], UpdateEntity):
    """Update entity for a standalone Docker container (not in a compose project)."""

    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: SynologyManagerCoordinator, container_name: str) -> None:
        super().__init__(coordinator)
        self._container_name = container_name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_ctr_{container_name}"

    def _get_container(self) -> ContainerInfo | None:
        for ctr in self.coordinator.data.get("standalone_containers", []):
            if ctr.name == self._container_name:
                return ctr
        return None

    @property
    def name(self) -> str:
        ctr = self._get_container()
        label = ctr.display_name if ctr else self._container_name
        return f"{self.coordinator.server_name} {label}"

    @property
    def title(self) -> str:
        ctr = self._get_container()
        return ctr.display_name if ctr else self._container_name

    @property
    def installed_version(self) -> str | None:
        ctr = self._get_container()
        return ctr.installed_version if ctr else None

    @property
    def latest_version(self) -> str | None:
        ctr = self._get_container()
        return ctr.latest_version if ctr else None

    async def async_release_notes(self) -> str | None:
        ctr = self._get_container()
        if ctr is None:
            return None
        return _container_release_notes(ctr.image)

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


def _container_release_notes(image: str) -> str:
    """Generate release notes with a link to the image's registry page."""
    repo = image.split(":")[0] if ":" in image else image

    if repo.startswith("ghcr.io/"):
        path = repo.removeprefix("ghcr.io/")
        url = f"https://github.com/{path}/releases"
        source = "GitHub"
    elif repo.startswith("lscr.io/"):
        path = repo.removeprefix("lscr.io/")
        url = f"https://hub.docker.com/r/{path}"
        source = "Docker Hub"
    elif "/" in repo:
        url = f"https://hub.docker.com/r/{repo}"
        source = "Docker Hub"
    else:
        url = f"https://hub.docker.com/_/{repo}"
        source = "Docker Hub"

    return f'<a href="{url}">View on {source}</a>'
