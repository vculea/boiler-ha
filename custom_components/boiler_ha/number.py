"""Number entities for Boiler Solar Controller.

Provides dashboard-adjustable sliders/inputs for:
  - Max temperature Boiler 1   (30–95 °C, default 90)
  - Max temperature Boiler 2   (30–95 °C, default 90)
  - Minimum solar surplus      (0–10 000 W, default 500)
  - Boiler 1 rated power       (0–10 000 W, default 2000)
  - Boiler 2 rated power       (0–10 000 W, default 2000)

Values are stored in hass.data runtime store so changes take effect immediately
without reloading the config entry. Values are restored via RestoreNumber on restart.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfPower
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
    CONF_MIN_SURPLUS,
    CONF_BOILER1_POWER,
    CONF_BOILER2_POWER,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
    RUNTIME_SCHEDULE_TARGET,
    RUNTIME_SCHEDULE_DONE_1,
    RUNTIME_SCHEDULE_DONE_2,
    DEFAULT_SCHEDULE_TARGET,
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
            BoilerMaxTempNumber(coordinator, entry, CONF_MAX_TEMP_1, b1, "1", DEFAULT_MAX_TEMP),
            BoilerMaxTempNumber(coordinator, entry, CONF_MAX_TEMP_2, b2, "2", DEFAULT_MAX_TEMP),
            BoilerSurplusThresholdNumber(coordinator, entry, DEFAULT_MIN_SURPLUS),
            BoilerRatedPowerNumber(coordinator, entry, CONF_BOILER1_POWER, b1, "1", DEFAULT_BOILER_POWER),
            BoilerRatedPowerNumber(coordinator, entry, CONF_BOILER2_POWER, b2, "2", DEFAULT_BOILER_POWER),
            ScheduleTargetTempNumber(
                coordinator, entry, RUNTIME_SCHEDULE_TARGET,
                DEFAULT_SCHEDULE_TARGET,
            ),
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
            model="Solar Boiler v1.1.2",
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


class BoilerMaxTempNumber(_BoilerNumber):
    """Maximum temperature setting for one boiler."""

    _attr_native_min_value = 30.0
    _attr_native_max_value = 95.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer-high"
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        runtime_key: str,
        boiler_name: str,
        boiler_index: str,
        default: float,
    ) -> None:
        super().__init__(coordinator, entry, runtime_key, f"max_temp_{boiler_index}", default)
        self._attr_name = f"Temperatură maximă {boiler_name}"
        self._boiler_name = boiler_name

    async def async_set_native_value(self, value: float) -> None:
        old = self.hass.data[DOMAIN][self._entry.entry_id].get(self._runtime_key)
        self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = value
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


class ScheduleTargetTempNumber(_BoilerNumber):
    """Target temperature for the shared solar-only heating schedule (applies to both boilers)."""

    _attr_native_min_value = 30.0
    _attr_native_max_value = 95.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer-alert"
    _attr_mode = NumberMode.SLIDER
    _attr_name = "Temperatură program solar"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        runtime_key: str,
        default: float,
    ) -> None:
        super().__init__(coordinator, entry, runtime_key, "schedule_target", default)

    async def async_set_native_value(self, value: float) -> None:
        rt = self.hass.data[DOMAIN][self._entry.entry_id]
        rt[self._runtime_key] = value
        # Reset both done flags so schedule can reactivate with the new target
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
