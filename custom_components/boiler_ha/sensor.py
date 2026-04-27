"""Sensor entities for Boiler Solar Controller.

Provides:
  - sensor.boiler1_status  — text status for Boiler 1
  - sensor.boiler2_status  — text status for Boiler 2
  - sensor.boiler_solar_surplus — current available solar surplus (W)
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
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
            SolarSurplusSensor(coordinator, entry),
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


# ── Solar surplus sensor ───────────────────────────────────────────────────────

class SolarSurplusSensor(_BoilerSensor):
    """Shows the calculated available solar surplus in watts."""

    _attr_name = "Surplus solar disponibil"
    _attr_icon = "mdi:solar-power-variant-outline"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_solar_surplus"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("grid_export")

    @property
    def extra_state_attributes(self) -> dict:
        if self.coordinator.data is None:
            return {}
        return {
            "productie_solara_w": self.coordinator.data.get("solar_power"),
            "boiler1_activ": self.coordinator.data.get("boiler1_on"),
            "boiler2_activ": self.coordinator.data.get("boiler2_on"),
        }
