"""Tests for the Synology Upgrades config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.synology_upgrades.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)

VALID_USER_INPUT = {
    CONF_HOST: "192.168.1.100",
    CONF_PORT: 5001,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_SSL: True,
    CONF_VERIFY_SSL: False,
}


async def test_form_success(hass: HomeAssistant) -> None:
    """Test successful config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        return_value={"host": "192.168.1.100"},
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Synology NAS (192.168.1.100)"
    assert result2["data"][CONF_HOST] == "192.168.1.100"
    assert result2["data"][CONF_USERNAME] == "admin"


async def test_form_invalid_auth(hass: HomeAssistant) -> None:
    """Test config flow with invalid credentials."""
    from custom_components.synology_upgrades.config_flow import InvalidAuth

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        side_effect=InvalidAuth,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "authentication_error"}


async def test_form_cannot_connect(hass: HomeAssistant) -> None:
    """Test config flow when NAS is unreachable."""
    from custom_components.synology_upgrades.config_flow import CannotConnect

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        side_effect=CannotConnect,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_unknown_error(hass: HomeAssistant) -> None:
    """Test config flow with an unexpected error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        side_effect=RuntimeError("Unexpected"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "unknown"}


async def test_form_already_configured(hass: HomeAssistant) -> None:
    """Test config flow aborts when the same NAS is already configured."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Synology NAS (192.168.1.100)",
        data={**VALID_USER_INPUT},
        unique_id="192.168.1.100_5001",
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        return_value={"host": "192.168.1.100"},
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"
