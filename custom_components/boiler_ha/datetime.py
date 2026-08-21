"""DateTime entities for Boiler Solar Controller.

Provides a single date+time picker for the shared solar-only schedule deadline:
  - datetime.schedule_deadline  — heating deadline for both boilers

Also provides date pickers for the vacation period. The end date is the day
heating resumes.

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
    RUNTIME_VACATION_START,
    RUNTIME_VACATION_END,
)
from .coordinator import BoilerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BoilerCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        ScheduleDeadlineDatetime(coordinator, entry),
        VacationDateTime(coordinator, entry, RUNTIME_VACATION_START, "Început vacanță", "start"),
        VacationDateTime(coordinator, entry, RUNTIME_VACATION_END, "Revenire din vacanță", "end"),
    ])


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
            model="Solar Boiler v1.4.2",
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


class VacationDateTime(CoordinatorEntity, DateTimeEntity, RestoreEntity):
    """Date picker for one boundary of the vacation period."""

    _attr_has_entity_name = True
    _attr_has_date = True
    _attr_has_time = False
    _attr_icon = "mdi:calendar-remove"

    def __init__(self, coordinator, entry, runtime_key: str, name: str, suffix: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._runtime_key = runtime_key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_vacation_{suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Boiler Solar Controller",
            manufacturer="Boiler HA",
            model="Solar Boiler v1.4.2",
        )

    @property
    def native_value(self) -> dt.datetime | None:
        return self.hass.data[DOMAIN][self._entry.entry_id].get(self._runtime_key)

    async def async_set_value(self, value: dt.datetime) -> None:
        rt = self.hass.data[DOMAIN][self._entry.entry_id]
        rt[self._runtime_key] = dt_util.as_utc(value)
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in ("unknown", "unavailable", None, "None"):
            return
        try:
            parsed = dt_util.parse_datetime(last.state)
            if parsed is not None:
                self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = dt_util.as_utc(parsed)
        except (ValueError, TypeError):
            pass
