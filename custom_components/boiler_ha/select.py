"""Select entities for Boiler Solar Controller.

Provides dropdown selectors (step 5 °C) for temperature settings:
  - Max temperature Boiler 1   (30–95 °C, step 5, default 90)
  - Max temperature Boiler 2   (30–95 °C, step 5, default 90)
  - Schedule target temperature (30–95 °C, step 5, default 60)

Replaces the slider NumberEntity variants so that values cannot be changed
accidentally on touchscreens.  Backend logic (runtime store, coordinator) is
identical to the previous implementation.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_BOILER1_NAME,
    CONF_BOILER2_NAME,
    CONF_MAX_TEMP_1,
    CONF_MAX_TEMP_2,
    RUNTIME_SCHEDULE_TARGET,
    RUNTIME_SCHEDULE_DONE_1,
    RUNTIME_SCHEDULE_DONE_2,
    RUNTIME_USER_MAX_TEMP_1,
    RUNTIME_USER_MAX_TEMP_2,
    DEFAULT_MAX_TEMP,
    DEFAULT_SCHEDULE_TARGET,
)
from .coordinator import BoilerCoordinator

# Dropdown options: 30, 35, 40 … 95 °C
_TEMP_OPTIONS: list[str] = [str(t) for t in range(30, 100, 5)]


def _snap_to_option(value: float) -> str:
    """Round a float temperature to the nearest 5 °C option string."""
    snapped = round(value / 5) * 5
    snapped = max(30, min(95, int(snapped)))
    return str(snapped)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BoilerCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    b1 = entry.data.get(CONF_BOILER1_NAME, "Boiler 1")
    b2 = entry.data.get(CONF_BOILER2_NAME, "Boiler 2")

    async_add_entities(
        [
            BoilerMaxTempSelect(coordinator, entry, CONF_MAX_TEMP_1, b1, "1", DEFAULT_MAX_TEMP),
            BoilerMaxTempSelect(coordinator, entry, CONF_MAX_TEMP_2, b2, "2", DEFAULT_MAX_TEMP),
            ScheduleTargetTempSelect(coordinator, entry, DEFAULT_SCHEDULE_TARGET),
        ]
    )


# ── Base ──────────────────────────────────────────────────────────────────────

class _BoilerTempSelect(CoordinatorEntity, SelectEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_options = _TEMP_OPTIONS
    _attr_icon = "mdi:thermometer"
    _attr_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        runtime_key: str,
        unique_suffix: str,
        default: float,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._runtime_key = runtime_key
        self._default = default
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Boiler Solar Controller",
            manufacturer="Boiler HA",
            model="Solar Boiler v1.1.9",
        )

    @property
    def current_option(self) -> str:
        value = self.hass.data[DOMAIN][self._entry.entry_id].get(
            self._runtime_key, self._default
        )
        return _snap_to_option(float(value))


# ── Concrete entities ─────────────────────────────────────────────────────────

class BoilerMaxTempSelect(_BoilerTempSelect):
    """Maximum temperature selector for one boiler."""

    _attr_icon = "mdi:thermometer-high"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        runtime_key: str,
        boiler_name: str,
        boiler_index: str,
        default: float,
    ) -> None:
        super().__init__(
            coordinator, entry, runtime_key,
            f"max_temp_{boiler_index}", default,
        )
        self._attr_name = f"Temperatură maximă {boiler_name}"
        self._boiler_name = boiler_name

    async def async_select_option(self, option: str) -> None:
        value = float(option)
        rt = self.hass.data[DOMAIN][self._entry.entry_id]
        old = rt.get(self._runtime_key)
        rt[self._runtime_key] = value
        # If a voltage boost is currently active, also update the saved pre-boost
        # target so the correct user value is restored when the boost ends.
        user_key = (
            RUNTIME_USER_MAX_TEMP_1
            if self._runtime_key == CONF_MAX_TEMP_1
            else RUNTIME_USER_MAX_TEMP_2
        )
        if user_key in rt:
            rt[user_key] = value
        self.async_write_ha_state()
        if old is not None and old != value:
            self.coordinator._log_action(
                f"Target {self._boiler_name} schimbat: {old:.1f}°C → {value:.1f}°C"
            )
        await self.coordinator.async_refresh()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable", None):
            try:
                value = float(last.state)
                self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = value
                self.coordinator._log_action(
                    f"Target {self._boiler_name} restaurat la {value:.1f}°C (restart)"
                )
            except (ValueError, TypeError):
                pass


class ScheduleTargetTempSelect(_BoilerTempSelect):
    """Target temperature selector for the shared solar-only heating schedule."""

    _attr_icon = "mdi:thermometer-alert"
    _attr_name = "Temperatură program solar"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        default: float,
    ) -> None:
        super().__init__(
            coordinator, entry, RUNTIME_SCHEDULE_TARGET,
            "schedule_target", default,
        )

    async def async_select_option(self, option: str) -> None:
        value = float(option)
        rt = self.hass.data[DOMAIN][self._entry.entry_id]
        rt[self._runtime_key] = value
        # Reset both done flags so the schedule can reactivate with the new target.
        rt.pop(RUNTIME_SCHEDULE_DONE_1, None)
        rt.pop(RUNTIME_SCHEDULE_DONE_2, None)
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable", None):
            try:
                value = float(last.state)
                self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = value
            except (ValueError, TypeError):
                pass
