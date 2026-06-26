"""The Synology Manager integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_HOST,
    CONF_NAME_PREFIX,
    CONF_OTP_CODE,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_NAME_PREFIX,
    DOMAIN,
)
from .coordinator import SynologyManagerCoordinator
from .synology_client import SynologyAuthenticationError, SynologyClient, SynologyConnectionError

PLATFORMS = (Platform.BUTTON, Platform.SWITCH, Platform.UPDATE)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class SynologyManagerData:
    """Runtime data for the Synology Manager integration."""

    client: SynologyClient
    coordinator: SynologyManagerCoordinator


SynologyManagerConfigEntry = ConfigEntry[SynologyManagerData]


async def async_setup_entry(hass: HomeAssistant, entry: SynologyManagerConfigEntry) -> bool:
    """Set up Synology Manager from a config entry."""
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

    server_name = entry.options.get(
        CONF_NAME_PREFIX, entry.data.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX)
    )
    coordinator = SynologyManagerCoordinator(hass, client, server_name)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SynologyManagerData(client=client, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: SynologyManagerConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SynologyManagerConfigEntry) -> bool:
    """Unload Synology Manager."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
