"""Number entities for Boiler Solar Controller.

Provides dashboard-adjustable inputs (BOX mode) for:
  - Minimum solar surplus      (0–10 000 W, default 800)
  - Grid import shutdown delay (0–3600 s, default 5, resets at local midnight)
  - Overvoltage threshold      (210–255 V, default 250)
  - Boiler 1 rated power       (0–10 000 W, default 1500)
  - Boiler 2 rated power       (0–10 000 W, default 1500)

Temperature targets are handled by select.py (dropdown, step 5 °C) to avoid
accidental changes on touchscreens.

Values are stored in hass.data runtime store so changes take effect immediately
without reloading the config entry. Values are restored via RestoreEntity on restart.
"""
from __future__ import annotations

import logging
import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_BOILER1_NAME,
    CONF_BOILER2_NAME,
    CONF_MIN_SURPLUS,
    CONF_BOILER1_POWER,
    CONF_BOILER2_POWER,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
    DEFAULT_PRIORITY_VOLTAGE,
    DEFAULT_PRIORITY_TEMP_RATIO,
    RUNTIME_PRIORITY_VOLTAGE,
    RUNTIME_PRIORITY_TEMP_RATIO,
    DEFAULT_GRID_IMPORT_DELAY,
    RUNTIME_GRID_IMPORT_DELAY,
    RUNTIME_GRID_IMPORT_DELAY_DATE,
)
from .coordinator import BoilerCoordinator

_LOGGER = logging.getLogger(__name__)


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
            BoilerSurplusThresholdNumber(coordinator, entry, DEFAULT_MIN_SURPLUS),
            BoilerOvervoltageThresholdNumber(coordinator, entry, DEFAULT_PRIORITY_VOLTAGE),
            BoilerPriorityTempRatioNumber(coordinator, entry, DEFAULT_PRIORITY_TEMP_RATIO),
            BoilerGridImportDelayNumber(coordinator, entry, DEFAULT_GRID_IMPORT_DELAY),
            BoilerRatedPowerNumber(coordinator, entry, CONF_BOILER1_POWER, b1, "1", DEFAULT_BOILER_POWER),
            BoilerRatedPowerNumber(coordinator, entry, CONF_BOILER2_POWER, b2, "2", DEFAULT_BOILER_POWER),
        ]
    )


# ── Base ──────────────────────────────────────────────────────────────────────

class _BoilerNumber(CoordinatorEntity, NumberEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

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
            model="Solar Boiler v1.5.0",
        )

    @property
    def native_value(self) -> float:
        return self.hass.data[DOMAIN][self._entry.entry_id].get(
            self._runtime_key, self._default
        )

    async def async_set_native_value(self, value: float) -> None:
        self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = value
        self.async_write_ha_state()
        await self.coordinator.async_refresh()



# ── Concrete entities ─────────────────────────────────────────────────────────

class BoilerGridImportDelayNumber(_BoilerNumber):
    """Temporary solar shutdown delay, restored only within the same local day."""

    _attr_native_min_value = 0.0
    _attr_native_max_value = 3600.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "s"
    _attr_icon = "mdi:timer-outline"
    _attr_name = "Intarziere oprire consum retea"

    def __init__(self, coordinator: BoilerCoordinator, entry: ConfigEntry, default: float) -> None:
        super().__init__(coordinator, entry, RUNTIME_GRID_IMPORT_DELAY, "grid_import_delay", default)

    @property
    def extra_state_attributes(self) -> dict:
        rt = self.hass.data[DOMAIN][self._entry.entry_id]
        return {"override_date": rt.get(RUNTIME_GRID_IMPORT_DELAY_DATE)}

    async def async_set_native_value(self, value: float) -> None:
        if not math.isfinite(value) or not self._attr_native_min_value <= value <= self._attr_native_max_value:
            raise ValueError("Intarzierea trebuie sa fie intre 0 si 3600 de secunde")
        rt = self.hass.data[DOMAIN][self._entry.entry_id]
        rt[RUNTIME_GRID_IMPORT_DELAY_DATE] = dt_util.as_local(dt_util.now()).date().isoformat()
        await super().async_set_native_value(value)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        today = dt_util.as_local(dt_util.now()).date().isoformat()
        if last is None or last.attributes.get("override_date") != today:
            return
        try:
            value = float(last.state)
        except (ValueError, TypeError):
            _LOGGER.warning("Valoare restaurata invalida pentru intarzierea opririi: %s", last.state)
            return
        await self.async_set_native_value(value)


class BoilerSurplusThresholdNumber(_BoilerNumber):
    """Minimum solar surplus (W) before starting any boiler."""

    _attr_native_min_value = 0.0
    _attr_native_max_value = 10000.0
    _attr_native_step = 50.0
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:solar-power-variant"
    _attr_name = "Prag minim surplus solar"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        default: float,
    ) -> None:
        super().__init__(coordinator, entry, CONF_MIN_SURPLUS, "min_surplus", default)


class BoilerOvervoltageThresholdNumber(_BoilerNumber):
    """Grid voltage threshold (V) above which priority heating is activated."""

    _attr_native_min_value = 210.0
    _attr_native_max_value = 255.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "V"
    _attr_icon = "mdi:transmission-tower-export"
    _attr_name = "Prag supratensiune"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        default: float,
    ) -> None:
        super().__init__(coordinator, entry, RUNTIME_PRIORITY_VOLTAGE, "priority_voltage", default)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable", None):
            try:
                value = float(last.state)
                self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = value
            except (ValueError, TypeError):
                pass


class BoilerPriorityTempRatioNumber(_BoilerNumber):
    """Percentage of max temp below which priority heating from the grid is activated.

    E.g. 50% with a 60 °C target → priority kicks in when water < 30 °C.
    Set to 0 % to disable temperature-based priority (overvoltage priority still works).
    """

    _attr_native_min_value = 0.0
    _attr_native_max_value = 90.0
    _attr_native_step = 5.0
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:thermometer-alert"
    _attr_name = "Prag prioritate temperatură"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        default: float,
    ) -> None:
        super().__init__(coordinator, entry, RUNTIME_PRIORITY_TEMP_RATIO, "priority_temp_ratio", default)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable", None):
            try:
                value = float(last.state)
                self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = value
            except (ValueError, TypeError):
                pass


class BoilerRatedPowerNumber(_BoilerNumber):
    """Estimated rated wattage of a boiler resistance (used for surplus calculation)."""

    _attr_native_min_value = 0.0
    _attr_native_max_value = 10000.0
    _attr_native_step = 50.0
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        runtime_key: str,
        boiler_name: str,
        boiler_index: str,
        default: float,
    ) -> None:
        super().__init__(coordinator, entry, runtime_key, f"rated_power_{boiler_index}", default)
        self._attr_name = f"Putere nominală {boiler_name}"
