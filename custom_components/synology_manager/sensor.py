"""Sensor entities for Synology Manager Task Scheduler tasks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SynologyManagerCoordinator
from .entity import SynologyManagerEntity, task_device_info
from .synology_client import TaskInfo


@dataclass(frozen=True, kw_only=True)
class TaskSensorDescription(SensorEntityDescription):
    """Describes one per-task sensor."""

    value_fn: Callable[[TaskInfo], datetime | int | str | None]
    attrs_fn: Callable[[TaskInfo], dict[str, Any]] | None = None


TASK_SENSORS: tuple[TaskSensorDescription, ...] = (
    TaskSensorDescription(
        key="last_run",
        name="Last run",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda task: task.last_run,
    ),
    TaskSensorDescription(
        key="next_run",
        name="Next run",
        device_class=SensorDeviceClass.TIMESTAMP,
        # None for disabled and triggered (boot-up/shutdown) tasks.
        value_fn=lambda task: task.next_run,
    ),
    TaskSensorDescription(
        key="last_result",
        name="Last result",
        device_class=SensorDeviceClass.ENUM,
        options=["running", "success", "failed"],
        value_fn=lambda task: task.last_result,
        # DSM's own label for the run ("by_signal" shows as "Interrupted").
        attrs_fn=lambda task: {"exit_type": task.last_exit_type},
    ),
    TaskSensorDescription(
        key="last_exit_code",
        name="Last exit code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda task: task.finished_exit_code,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up per-task sensors."""
    coordinator: SynologyManagerCoordinator = entry.runtime_data.coordinator
    known_tasks: set[int] = set()

    def _new_sensors() -> list[SensorEntity]:
        new: list[SensorEntity] = []
        for task in coordinator.data.get("tasks", []):
            if task.task_id not in known_tasks:
                known_tasks.add(task.task_id)
                new.extend(
                    SynologyTaskSensorEntity(coordinator, task, description)
                    for description in TASK_SENSORS
                )
        return new

    async_add_entities(_new_sensors())

    def _async_add_new_entities() -> None:
        if new := _new_sensors():
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class SynologyTaskSensorEntity(SynologyManagerEntity, SensorEntity):
    """A run-time or run-result sensor on a task's child device."""

    _attr_has_entity_name = True
    entity_description: TaskSensorDescription

    def __init__(
        self,
        coordinator: SynologyManagerCoordinator,
        task: TaskInfo,
        description: TaskSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._task_id = task.task_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_task_{task.task_id}_{description.key}"
        )
        self._attr_device_info = task_device_info(coordinator, task)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.get_task(self._task_id) is not None

    @property
    def native_value(self) -> datetime | int | str | None:
        task = self.coordinator.get_task(self._task_id)
        return self.entity_description.value_fn(task) if task else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        task = self.coordinator.get_task(self._task_id)
        if task is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(task)
