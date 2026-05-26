"""Config flow for Synology Upgrades integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .synology_client import SynologyAuthenticationError, SynologyClient, SynologyConnectionError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SSL, default=DEFAULT_SSL): bool,
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)


class InvalidAuth(Exception):
    """Error to indicate invalid authentication."""


class CannotConnect(Exception):
    """Error to indicate the NAS is unreachable."""


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict:
    """Validate credentials by connecting to the NAS."""
    client = SynologyClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        secure=data[CONF_SSL],
        verify_ssl=data[CONF_VERIFY_SSL],
    )
    try:
        await hass.async_add_executor_job(client.connect)
    except SynologyAuthenticationError as err:
        raise InvalidAuth from err
    except SynologyConnectionError as err:
        raise CannotConnect from err
    return {"host": data[CONF_HOST]}


class SynologyUpgradesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Synology Upgrades."""

    VERSION = 1

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication after credentials become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication confirmation."""
        errors: dict[str, str] | None = None

        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            data = {**reauth_entry.data, **user_input}
            try:
                await validate_input(self.hass, data)
            except InvalidAuth:
                errors = {"base": "authentication_error"}
            except CannotConnect:
                errors = {"base": "cannot_connect"}
            except Exception:
                _LOGGER.exception("Unexpected exception during reauth validation")
                errors = {"base": "unknown"}
            else:
                return self.async_update_reload_and_abort(reauth_entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] | None = None

        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors = {"base": "authentication_error"}
            except CannotConnect:
                errors = {"base": "cannot_connect"}
            except Exception:
                _LOGGER.exception("Unexpected exception during validation")
                errors = {"base": "unknown"}
            else:
                host = user_input[CONF_HOST]
                port = user_input[CONF_PORT]
                await self.async_set_unique_id(f"{host}_{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Synology NAS ({host})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
