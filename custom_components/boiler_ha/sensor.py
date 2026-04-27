"""Sensor entities for Boiler Solar Controller.

Provides:
  - sensor.boiler1_status      — text status for Boiler 1
  - sensor.boiler2_status      — text status for Boiler 2
  - sensor.boiler1_temp        — temperature Boiler 1 (°C)
  - sensor.boiler2_temp        — temperature Boiler 2 (°C)
  - sensor.solar_production    — raw solar panel production (W)
  - sensor.grid_power          — grid power: positive=import, negative=export
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_BOILER1_NAME,
    CONF_BOILER2_NAME,
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
            BoilerStatusSensor(coordinator, entry, b1, "boiler1_status", "1"),
            BoilerStatusSensor(coordinator, entry, b2, "boiler2_status", "2"),
            BoilerTemperatureSensor(coordinator, entry, b1, "boiler1_temp", "1"),
            BoilerTemperatureSensor(coordinator, entry, b2, "boiler2_temp", "2"),
            SolarProductionSensor(coordinator, entry),
            GridPowerSensor(coordinator, entry),
        ]
    )


# ── Device info mixin ─────────────────────────────────────────────────────────

class _BoilerSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Boiler Solar Controller",
            manufacturer="Boiler HA",
            model="Solar Boiler",
        )


# ── Boiler status sensor ───────────────────────────────────────────────────────

class BoilerStatusSensor(_BoilerSensor):
    """Text status sensor for one boiler."""

    _attr_icon = "mdi:water-boiler"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        boiler_name: str,
        data_key: str,
        boiler_index: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._data_key = data_key
        self._attr_unique_id = f"{entry.entry_id}_status_{boiler_index}"
        self._attr_name = f"Status {boiler_name}"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._data_key)

    @property
    def extra_state_attributes(self) -> dict:
        if self.coordinator.data is None:
            return {}
        idx = self._data_key.replace("_status", "")
        return {
            "temperatura": self.coordinator.data.get(f"{idx}_temp"),
            "rezistenta_activa": self.coordinator.data.get(f"{idx}_on"),
        }




# ── Boiler temperature sensor ─────────────────────────────────────────────────

class BoilerTemperatureSensor(_BoilerSensor):
    """Mirrors the boiler temperature from the configured sensor entity."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer-water"

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        boiler_name: str,
        data_key: str,
        boiler_index: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._data_key = data_key
        self._attr_unique_id = f"{entry.entry_id}_temp_{boiler_index}"
        self._attr_name = f"Temperatură {boiler_name}"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._data_key)


# ── Solar production sensor ─────────────────────────────────────────────

class SolarProductionSensor(_BoilerSensor):
    """Shows the raw solar panel production in watts."""

    _attr_name = "Producție solară"
    _attr_icon = "mdi:solar-panel"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BoilerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_solar_production"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("solar_power")


# ── Grid power sensor ──────────────────────────────────────────────────

class GridPowerSensor(_BoilerSensor):
    """Shows grid power: positive = consuming from grid, negative = injecting to grid."""

    _attr_name = "Rețea (consum/injecție)"
    _attr_icon = "mdi:transmission-tower"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BoilerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_grid_power"

    @property
    def native_value(self) -> float | None:
        """Return grid power normalized: positive = import, negative = export (surplus)."""
        if self.coordinator.data is None:
            return None
        grid_export = self.coordinator.data.get("grid_export")
        if grid_export is None:
            return None
        # grid_export is positive when exporting; we flip so positive = consuming
        return -grid_export

    @property
    def extra_state_attributes(self) -> dict:
        if self.coordinator.data is None:
            return {}
        grid_export = self.coordinator.data.get("grid_export")
        if grid_export is None:
            return {}
        if grid_export > 0:
            status = f"Injecție în rețea: {grid_export:.0f} W"
        elif grid_export < 0:
            status = f"Consum din rețea: {abs(grid_export):.0f} W"
        else:
            status = "Echilibrat"
        return {"status": status}
