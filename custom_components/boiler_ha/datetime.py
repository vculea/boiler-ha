"""DateTime entities for Boiler Solar Controller.

Provides a single date+time picker for the shared solar-only schedule deadline:
  - datetime.schedule_deadline  — heating deadline for both boilers

The user sets a deadline and a target temperature; the coordinator will heat
both boilers using ONLY solar surplus until each reaches the target temperature
or the deadline expires.
"""
from __future__ import annotations

import datetime as dt

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    RUNTIME_SCHEDULE_DEADLINE,
    RUNTIME_SCHEDULE_DONE_1,
    RUNTIME_SCHEDULE_DONE_2,
)
from .coordinator import BoilerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BoilerCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([ScheduleDeadlineDatetime(coordinator, entry)])


class ScheduleDeadlineDatetime(CoordinatorEntity, DateTimeEntity, RestoreEntity):
    """Date+time picker for the shared solar-only heating schedule deadline."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    _attr_name = "Deadline program solar"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_schedule_deadline"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Boiler Solar Controller",
            manufacturer="Boiler HA",
            model="Solar Boiler v1.1.2",
        )

    @property
    def native_value(self) -> dt.datetime | None:
        """Return the stored deadline (aware UTC datetime) or None."""
        return self.hass.data[DOMAIN][self._entry.entry_id].get(RUNTIME_SCHEDULE_DEADLINE)

    async def async_set_value(self, value: dt.datetime) -> None:
        """Store the deadline (converted to UTC) and reset both done flags if deadline is future."""
        utc_val = dt_util.as_utc(value)
        rt = self.hass.data[DOMAIN][self._entry.entry_id]
        rt[RUNTIME_SCHEDULE_DEADLINE] = utc_val
        # If the new deadline is in the future, the schedule becomes active again
        if utc_val > dt_util.utcnow():
            rt.pop(RUNTIME_SCHEDULE_DONE_1, None)
            rt.pop(RUNTIME_SCHEDULE_DONE_2, None)
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    async def async_added_to_hass(self) -> None:
        """Restore previous deadline from HA state history on restart."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable", None, "None"):
            try:
                parsed = dt_util.parse_datetime(last.state)
                if parsed is not None:
                    self.hass.data[DOMAIN][self._entry.entry_id][RUNTIME_SCHEDULE_DEADLINE] = (
                        dt_util.as_utc(parsed)
                    )
            except (ValueError, TypeError):
                pass
            except (ValueError, TypeError):
                pass
