"""Button entities for Synology Manager."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SynologyManagerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Synology Manager button entities."""
    coordinator: SynologyManagerCoordinator = entry.runtime_data.coordinator
    async_add_entities([SynologySecurityScanButtonEntity(coordinator)])


class SynologySecurityScanButtonEntity(CoordinatorEntity[SynologyManagerCoordinator], ButtonEntity):
    """Button that triggers a Security Advisor scan on demand."""

    def __init__(self, coordinator: SynologyManagerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_security_scan"
        self._attr_name = f"{coordinator.server_name} Security Scan"

    async def async_press(self) -> None:
        """Trigger the Security Advisor scan."""
        await self.hass.async_add_executor_job(self.coordinator.client.trigger_security_scan)
