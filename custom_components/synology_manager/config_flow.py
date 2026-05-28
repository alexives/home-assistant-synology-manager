"""Config flow for Synology Manager integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_HOST,
    CONF_NAME_PREFIX,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_NAME_PREFIX,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .synology_client import SynologyAuthenticationError, SynologyClient, SynologyConnectionError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME_PREFIX, default=DEFAULT_NAME_PREFIX): str,
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


class SynologyManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Synology Manager."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow handler."""
        return SynologyManagerOptionsFlow(config_entry)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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


class SynologyManagerOptionsFlow(OptionsFlow):
    """Handle options for Synology Manager."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_prefix = self._config_entry.options.get(
            CONF_NAME_PREFIX,
            self._config_entry.data.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME_PREFIX, default=current_prefix): str,
                }
            ),
        )
