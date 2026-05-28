"""DataUpdateCoordinator for Synology Manager."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN
from .synology_client import SynologyClient

_LOGGER = logging.getLogger(__name__)


class SynologyManagerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls DSM, packages, containers, and projects."""

    def __init__(self, hass: HomeAssistant, client: SynologyClient, server_name: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS),
        )
        self.client = client
        self.server_name = server_name

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from all three sources with per-source error isolation."""
        data = await self._fetch_all()

        if data is None:
            _LOGGER.debug("All sources failed, reconnecting and retrying")
            try:
                await self.hass.async_add_executor_job(self.client.connect)
                _LOGGER.debug("Reconnect succeeded")
            except Exception:
                _LOGGER.warning("Reconnect failed", exc_info=True)
            data = await self._fetch_all()

        if data is None:
            raise UpdateFailed("All data sources failed")

        return data

    async def _fetch_all(self) -> dict[str, Any] | None:
        """Try fetching all sources. Returns None if all fail."""
        dsm = None
        packages = []
        containers = []
        projects = []
        failures = []

        try:
            dsm = await self.hass.async_add_executor_job(self.client.get_dsm_update)
        except Exception:
            _LOGGER.warning("Failed to fetch DSM update info", exc_info=True)
            failures.append("dsm")

        try:
            packages = await self.hass.async_add_executor_job(self.client.get_packages)
        except Exception:
            _LOGGER.warning("Failed to fetch package info", exc_info=True)
            failures.append("packages")

        try:
            containers = await self.hass.async_add_executor_job(self.client.get_containers)
        except Exception:
            _LOGGER.warning("Failed to fetch container info", exc_info=True)
            failures.append("containers")

        try:
            projects = await self.hass.async_add_executor_job(self.client.get_projects)
        except Exception:
            _LOGGER.warning("Failed to fetch project info", exc_info=True)
            failures.append("projects")

        if len(failures) == 4:
            return None

        project_updates, standalone_containers = self.client.group_container_updates(
            containers, projects
        )

        return {
            "dsm": dsm,
            "packages": packages,
            "containers": containers,
            "projects": projects,
            "project_updates": project_updates,
            "standalone_containers": standalone_containers,
        }
