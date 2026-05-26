"""The Synology Upgrades integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    CONF_OTP_CODE,
    DOMAIN,
)
from .coordinator import SynologyUpgradesCoordinator
from .synology_client import SynologyAuthenticationError, SynologyClient, SynologyConnectionError

PLATFORMS = (Platform.UPDATE,)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class SynologyUpgradesData:
    """Runtime data for the Synology Upgrades integration."""

    client: SynologyClient
    coordinator: SynologyUpgradesCoordinator


SynologyUpgradesConfigEntry = ConfigEntry[SynologyUpgradesData]


async def async_setup_entry(hass: HomeAssistant, entry: SynologyUpgradesConfigEntry) -> bool:
    """Set up Synology Upgrades from a config entry."""
    client = SynologyClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        secure=entry.data[CONF_SSL],
        verify_ssl=entry.data[CONF_VERIFY_SSL],
        otp_code=entry.data.get(CONF_OTP_CODE),
    )

    try:
        await hass.async_add_executor_job(client.connect)
    except SynologyAuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SynologyConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = SynologyUpgradesCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SynologyUpgradesData(client=client, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SynologyUpgradesConfigEntry) -> bool:
    """Unload Synology Upgrades."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
