"""Number entities for Boiler Solar Controller.

Provides dashboard-adjustable inputs (BOX mode) for:
  - Minimum solar surplus      (0–10 000 W, default 800)
  - Overvoltage threshold      (210–255 V, default 250)
  - Boiler 1 rated power       (0–10 000 W, default 1500)
  - Boiler 2 rated power       (0–10 000 W, default 1500)

Temperature targets are handled by select.py (dropdown, step 5 °C) to avoid
accidental changes on touchscreens.

Values are stored in hass.data runtime store so changes take effect immediately
without reloading the config entry. Values are restored via RestoreEntity on restart.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
    RUNTIME_PRIORITY_VOLTAGE,
)
from .coordinator import BoilerCoordinator


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
            model="Solar Boiler v1.3.3",
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



