"""Switch entities for Boiler Solar Controller.

Creates two switches:
  - switch.boiler1_auto  → enables/disables automatic solar control for Boiler 1
  - switch.boiler2_auto  → enables/disables automatic solar control for Boiler 2

When auto is OFF the relay is left in its current state and controlled manually.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_BOILER1_NAME,
    CONF_BOILER2_NAME,
    RUNTIME_AUTO_1,
    RUNTIME_AUTO_2,
)
from .coordinator import BoilerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BoilerCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    boiler1_name = entry.data.get(CONF_BOILER1_NAME, "Boiler 1")
    boiler2_name = entry.data.get(CONF_BOILER2_NAME, "Boiler 2")

    async_add_entities(
        [
            BoilerAutoSwitch(
                coordinator, entry, boiler1_name, RUNTIME_AUTO_1, "1"
            ),
            BoilerAutoSwitch(
                coordinator, entry, boiler2_name, RUNTIME_AUTO_2, "2"
            ),
        ]
    )


class BoilerAutoSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Switch that enables/disables automatic solar control for one boiler."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        entry: ConfigEntry,
        boiler_name: str,
        runtime_key: str,
        boiler_index: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._runtime_key = runtime_key
        self._boiler_name = boiler_name
        self._boiler_index = boiler_index
        self._attr_unique_id = f"{entry.entry_id}_auto_{boiler_index}"
        self._attr_name = f"Control automat {boiler_name}"
        self._attr_icon = "mdi:solar-power"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Boiler Solar Controller",
            manufacturer="Boiler HA",
            model="Solar Boiler v1.2.2",
        )

    @property
    def is_on(self) -> bool:
        return self.hass.data[DOMAIN][self._entry.entry_id].get(self._runtime_key, True)

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = True
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on restart."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            value = last.state == "on"
            self.hass.data[DOMAIN][self._entry.entry_id][self._runtime_key] = value
