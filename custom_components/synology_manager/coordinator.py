"""DataUpdateCoordinator for Synology Manager."""

from __future__ import annotations

import logging
from collections.abc import Callable
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
        """Fetch data from all sources with per-source error isolation."""
        data = await self._fetch_all()
        if data is None:
            raise UpdateFailed("All data sources failed")
        return data

    async def _fetch_source(
        self,
        name: str,
        fetch: Callable[[], Any],
        default: Any,
        failures: list[str],
    ) -> Any:
        """Fetch one source, reconnecting the shared session and retrying once on failure.

        On unrecoverable failure, records the source name in ``failures`` and
        returns ``default`` so the other sources still update.
        """
        try:
            return await self.hass.async_add_executor_job(fetch)
        except Exception:
            _LOGGER.debug("%s fetch failed, reconnecting session", name, exc_info=True)
            try:
                await self.hass.async_add_executor_job(self.client.reconnect)
                return await self.hass.async_add_executor_job(fetch)
            except Exception:
                _LOGGER.warning("Failed to fetch %s after reconnect", name, exc_info=True)
                failures.append(name)
                return default

    async def _fetch_all(self) -> dict[str, Any] | None:
        """Try fetching all sources. Returns None if all fail."""
        failures: list[str] = []
        sources = (
            ("dsm", self.client.get_dsm_update, None),
            ("packages", self.client.get_packages, []),
            ("containers", self.client.get_containers, []),
            ("projects", self.client.get_projects, []),
        )
        results = {
            name: await self._fetch_source(name, fetch, default, failures)
            for name, fetch, default in sources
        }
        dsm = results["dsm"]
        packages = results["packages"]
        containers = results["containers"]
        projects = results["projects"]

        if len(failures) == len(sources):
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
