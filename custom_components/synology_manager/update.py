"""Update entities for Synology Manager."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .actions import notify, run_action
from .const import DOMAIN
from .coordinator import SynologyManagerCoordinator
from .synology_client import ContainerInfo, PackageInfo, ProjectUpdateInfo, _is_newer

# Synology's guidance for how long a DSM update (download, apply, reboot)
# can take; the post-upgrade refresh must wait it out, since a failed
# refresh would mark every entity unavailable for a full 6-hour interval.
DSM_UPGRADE_WINDOW = timedelta(minutes=25)

_LOGGER = logging.getLogger(__name__)


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
        await run_action(
            self.hass,
            self.coordinator.config_entry.entry_id,
            "Updating DSM",
            self.coordinator.client.upgrade_dsm,
        )
        notify(
            self.hass,
            self.coordinator.config_entry.entry_id,
            "DSM update started. The NAS is applying the update and will "
            "reboot - Synology says this can take up to 20 minutes, during "
            "which the NAS and its entities are unreachable. This is "
            "expected; do not power the NAS off.",
            suffix="dsm_upgrade",
        )

        # Refreshing now would fail against the rebooting NAS and mark every
        # entity unavailable until the next 6-hour tick; wait out the window.
        async def _refresh_after_reboot(_now) -> None:
            await self.coordinator.async_request_refresh()

        async_call_later(self.hass, DSM_UPGRADE_WINDOW, _refresh_after_reboot)


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

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Compare Synology package versions (``X.Y.Z-BUILD``).

        HA's default comparison (AwesomeVersion) ignores the build suffix, so a
        build-only bump (e.g. ``1.5.2-1831`` -> ``1.5.2-1832``) would otherwise
        render as "Up-to-date".
        """
        return _is_newer(latest_version, installed_version)

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

    @property
    def supported_features(self) -> UpdateEntityFeature:
        pkg = self._get_package()
        if pkg and pkg.blocked_reason:
            return UpdateEntityFeature.RELEASE_NOTES
        return self._attr_supported_features

    @property
    def release_summary(self) -> str | None:
        pkg = self._get_package()
        return pkg.blocked_reason if pkg else None

    async def async_release_notes(self) -> str | None:
        pkg = self._get_package()
        if pkg is None:
            return None
        notices = []
        if pkg.unmet_dependencies:
            notices.append(self._blocked_notice(pkg))
        if pkg.third_party and pkg.update_available:
            notices.append(_community_notice(pkg))
        if not notices:
            return pkg.changelog
        if pkg.changelog:
            notices.append(pkg.changelog)
        return "\n\n---\n\n".join(notices)

    def _blocked_notice(self, pkg: PackageInfo) -> str:
        """Markdown notice for a blocked update, linking to the dependency update entities."""
        registry = er.async_get(self.hass)
        lines = ["**This update can't be installed yet.** Update these packages first:", ""]
        for dep in pkg.unmet_dependencies:
            entity_id = registry.async_get_entity_id(
                "update", DOMAIN, f"{self.coordinator.config_entry.entry_id}_pkg_{dep.package_id}"
            )
            label = (
                f"[{dep.name}](/config/updates?more-info-entity-id={entity_id})"
                if entity_id
                else dep.name
            )
            lines.append(f"- {label} {dep.requirement} (installed: {dep.installed_version})")
        return "\n".join(lines)

    async def async_install(self, version: str | None, backup: bool | None, **kwargs: Any) -> None:
        await run_action(
            self.hass,
            self.coordinator.config_entry.entry_id,
            f"Updating package {self.title}",
            self.coordinator.client.upgrade_package,
            self._package_id,
        )
        # Best-effort: a failed scan must not report a successful upgrade as failed.
        try:
            await self.hass.async_add_executor_job(self.coordinator.client.trigger_security_scan)
        except Exception:
            _LOGGER.warning(
                "Post-upgrade security scan failed for %s", self._package_id, exc_info=True
            )
        await self.coordinator.async_request_refresh()


def _community_notice(pkg: PackageInfo) -> str:
    """Markdown notice for a package from a third-party Package Center source."""
    source = pkg.distributor or "a third-party package source"
    return (
        f"**Community package.** This package comes from {source}, not from Synology, "
        "and Synology does not sign it. Package Center asks you to agree before it "
        "installs an unsigned package; Install here does not ask."
    )


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
        await run_action(
            self.hass,
            self.coordinator.config_entry.entry_id,
            f"Updating project {self.title}",
            self.coordinator.client.update_project,
            pu.project_id,
            pu.images,
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
        await run_action(
            self.hass,
            self.coordinator.config_entry.entry_id,
            f"Updating container {self.title}",
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
