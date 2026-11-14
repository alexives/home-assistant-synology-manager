"""DataUpdateCoordinator for Synology Manager."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN
from .synology_client import SynologyClient, TaskInfo, apply_task_run

_LOGGER = logging.getLogger(__name__)

# After Run is pressed, re-read that task's run history until it finishes:
# first check soon, then every 30 s for up to 30 min.
TASK_WATCH_FIRST = timedelta(seconds=5)
TASK_WATCH_INTERVAL = timedelta(seconds=30)
TASK_WATCH_MAX_CHECKS = 60
TASK_CLOCK_SLACK = timedelta(minutes=1)


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
        # Set by async_setup_entry once the NAS device is registered.
        self.nas_device_id: str | None = None
        self._task_watches: dict[int, CALLBACK_TYPE] = {}

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
            ("tasks", partial(self.client.get_tasks, dt_util.get_default_time_zone()), []),
        )
        results = {
            name: await self._fetch_source(name, fetch, default, failures)
            for name, fetch, default in sources
        }
        dsm = results["dsm"]
        packages = results["packages"]
        containers = results["containers"]
        projects = results["projects"]
        tasks = results["tasks"]

        if len(failures) == len(sources):
            return None

        # Without Container Manager (not installed, or still starting after a
        # reboot) the Docker sources return empty lists; that is not evidence
        # that any project is gone.
        if not self.client.has_docker:
            failures.extend(name for name in ("containers", "projects") if name not in failures)

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
            "tasks": tasks,
            "failed_sources": failures,
        }

    def get_task(self, task_id: int) -> TaskInfo | None:
        """Return the task with this id from the latest data, or None."""
        for task in (self.data or {}).get("tasks", []):
            if task.task_id == task_id:
                return task
        return None

    @callback
    def async_watch_task(self, task_id: int) -> None:
        """Track a task started from HA until its run finishes.

        Re-reads only that task's run history, so Last run / Last result
        update within seconds instead of at the next 6-hour poll.
        """
        self.async_cancel_task_watch(task_id)
        # The NAS clock may differ from HA's; a minute of slack still tells
        # this run apart from the previous one (scheduled runs are rarely
        # closer together).
        since = dt_util.utcnow() - TASK_CLOCK_SLACK
        self._schedule_task_check(task_id, since, TASK_WATCH_FIRST, TASK_WATCH_MAX_CHECKS)

    @callback
    def async_cancel_task_watch(self, task_id: int | None = None) -> None:
        """Cancel one task watch, or all of them (on unload)."""
        ids = list(self._task_watches) if task_id is None else [task_id]
        for tid in ids:
            if (cancel := self._task_watches.pop(tid, None)) is not None:
                cancel()

    def _schedule_task_check(self, task_id: int, since, delay: timedelta, checks_left: int) -> None:
        async def _check(_now) -> None:
            self._task_watches.pop(task_id, None)
            run = await self.hass.async_add_executor_job(self.client.get_task_last_run, task_id)
            task = self.get_task(task_id)
            if task is None:
                return
            apply_task_run(task, run)
            self.async_update_listeners()
            not_started = task.last_run is None or task.last_run < since
            if (not_started or task.last_result == "running") and checks_left > 1:
                self._schedule_task_check(task_id, since, TASK_WATCH_INTERVAL, checks_left - 1)

        self._task_watches[task_id] = async_call_later(self.hass, delay, _check)
