"""Surface entity action failures in the UI instead of swallowing them.

The "Failed to perform the action" popup renders plain text only, so it
carries the cause and a where-to-look hint; the persistent notification
carries the clickable link to the pre-filtered logs page (the frontend
reads the ``filter`` query param into the search box).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .synology_client import _err_detail

_LOGGER = logging.getLogger(__name__)

LOGS_URL = f"/config/logs?filter={DOMAIN}"


async def run_action(
    hass: HomeAssistant,
    entry_id: str,
    description: str,
    func: Callable[..., Any],
    *args: Any,
) -> Any:
    """Run a sync client call; on failure log, notify, and raise for the popup.

    The notification id is stable per config entry so repeated failures
    replace the notification instead of piling up.
    """
    try:
        return await hass.async_add_executor_job(func, *args)
    except HomeAssistantError:
        raise
    except Exception as err:
        detail = _err_detail(err)
        _LOGGER.exception("%s failed: %s", description, detail)
        persistent_notification.async_create(
            hass,
            message=(
                f"{description} failed: {detail}\n\n"
                f"[Open the logs]({LOGS_URL}) for the full traceback."
            ),
            title="Synology Manager",
            notification_id=f"{DOMAIN}_{entry_id}_action_error",
        )
        raise HomeAssistantError(
            f"{description} failed: {detail} - see Settings > System > Logs "
            f"(search '{DOMAIN}') for details"
        ) from err
