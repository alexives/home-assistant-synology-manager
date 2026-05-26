"""Tests for Synology Upgrades integration setup."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
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
from custom_components.synology_upgrades.synology_client import (
    DsmUpdateInfo,
    SynologyAuthenticationError,
    SynologyConnectionError,
)

MOCK_CONFIG = {
    CONF_HOST: "192.168.1.100",
    CONF_PORT: 5001,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_SSL: True,
    CONF_VERIFY_SSL: False,
}


def create_mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synology NAS (192.168.1.100)",
        data=MOCK_CONFIG,
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_entry(hass: HomeAssistant) -> None:
    """Test successful setup of config entry."""
    entry = create_mock_entry(hass)

    mock_client = MagicMock()
    mock_client.get_dsm_update.return_value = DsmUpdateInfo(
        installed_version="7.2.1", latest_version=None,
        update_available=False, release_notes=None,
    )
    mock_client.get_packages.return_value = []
    mock_client.get_containers.return_value = []

    with (
        patch(
            "custom_components.synology_upgrades.SynologyClient",
            return_value=mock_client,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=True)(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None


async def test_setup_entry_auth_failed(hass: HomeAssistant) -> None:
    """Test that auth failure on startup triggers reauth."""
    entry = create_mock_entry(hass)

    mock_client = MagicMock()
    mock_client.connect.side_effect = SynologyAuthenticationError("Bad credentials")

    with patch(
        "custom_components.synology_upgrades.SynologyClient",
        return_value=mock_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    reauth_flows = [f for f in flows if f["context"].get("source") == "reauth"]
    assert len(reauth_flows) == 1


async def test_setup_entry_connection_error(hass: HomeAssistant) -> None:
    """Test that connection error marks entry for retry."""
    entry = create_mock_entry(hass)

    mock_client = MagicMock()
    mock_client.connect.side_effect = SynologyConnectionError("NAS unreachable")

    with patch(
        "custom_components.synology_upgrades.SynologyClient",
        return_value=mock_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(hass: HomeAssistant) -> None:
    """Test successful unload of config entry."""
    entry = create_mock_entry(hass)

    mock_client = MagicMock()
    mock_client.get_dsm_update.return_value = DsmUpdateInfo(
        installed_version="7.2.1", latest_version=None,
        update_available=False, release_notes=None,
    )
    mock_client.get_packages.return_value = []
    mock_client.get_containers.return_value = []

    with (
        patch(
            "custom_components.synology_upgrades.SynologyClient",
            return_value=mock_client,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=True)(),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=True)(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)

    assert entry.state is ConfigEntryState.NOT_LOADED
