"""DataUpdateCoordinator for Synology Upgrades."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN
from .synology_client import SynologyClient

_LOGGER = logging.getLogger(__name__)


class SynologyUpgradesCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls DSM, packages, and containers."""

    def __init__(self, hass: HomeAssistant, client: SynologyClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from all three sources with per-source error isolation."""
        dsm = None
        packages = []
        containers = []
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

        if len(failures) == 3:
            raise UpdateFailed("All data sources failed")

        return {
            "dsm": dsm,
            "packages": packages,
            "containers": containers,
        }
