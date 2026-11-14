"""Button entities for Synology Manager."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .actions import run_action
from .coordinator import SynologyManagerCoordinator
from .entity import SynologyManagerEntity, task_device_info
from .synology_client import TaskInfo


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Synology Manager button entities."""
    coordinator: SynologyManagerCoordinator = entry.runtime_data.coordinator
    known_tasks: set[int] = set()

    def _new_task_buttons() -> list[ButtonEntity]:
        new: list[ButtonEntity] = []
        for task in coordinator.data.get("tasks", []):
            if task.runnable and task.task_id not in known_tasks:
                known_tasks.add(task.task_id)
                new.append(SynologyTaskRunButtonEntity(coordinator, task))
        return new

    async_add_entities([SynologySecurityScanButtonEntity(coordinator), *_new_task_buttons()])

    def _async_add_new_entities() -> None:
        if new := _new_task_buttons():
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class SynologySecurityScanButtonEntity(SynologyManagerEntity, ButtonEntity):
    """Button that triggers a Security Advisor scan on demand."""

    def __init__(self, coordinator: SynologyManagerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_security_scan"
        self._attr_name = f"{coordinator.server_name} Security Scan"

    async def async_press(self) -> None:
        """Trigger the Security Advisor scan."""
        await run_action(
            self.hass,
            self.coordinator.config_entry.entry_id,
            "Security Advisor scan",
            self.coordinator.client.trigger_security_scan,
        )


class SynologyTaskRunButtonEntity(SynologyManagerEntity, ButtonEntity):
    """Runs a Task Scheduler task now, like Task Scheduler's "Run" button."""

    _attr_has_entity_name = True
    _attr_name = "Run"

    def __init__(self, coordinator: SynologyManagerCoordinator, task: TaskInfo) -> None:
        super().__init__(coordinator)
        self._task_id = task.task_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_task_{task.task_id}_run"
        self._attr_device_info = task_device_info(coordinator, task)

    @property
    def available(self) -> bool:
        task = self.coordinator.get_task(self._task_id)
        return super().available and task is not None and task.runnable

    async def async_press(self) -> None:
        """Run the task, then follow its run until it finishes."""
        task = self.coordinator.get_task(self._task_id)
        if task is None or not task.real_owner:
            return
        await run_action(
            self.hass,
            self.coordinator.config_entry.entry_id,
            f"Running task {task.name}",
            self.coordinator.client.run_task,
            task.task_id,
            task.real_owner,
        )
        self.coordinator.async_watch_task(self._task_id)
