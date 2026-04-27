"""Boiler Solar Controller — Home Assistant custom integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_MAX_TEMP_1,
    CONF_MAX_TEMP_2,
    CONF_MIN_SURPLUS,
    CONF_BOILER1_POWER,
    CONF_BOILER2_POWER,
    RUNTIME_AUTO_1,
    RUNTIME_AUTO_2,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
)
from .coordinator import BoilerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Boiler Solar Controller from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize runtime store (for values controlled by switch/number entities)
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_MAX_TEMP_1: entry.options.get(CONF_MAX_TEMP_1, DEFAULT_MAX_TEMP),
        CONF_MAX_TEMP_2: entry.options.get(CONF_MAX_TEMP_2, DEFAULT_MAX_TEMP),
        CONF_MIN_SURPLUS: entry.options.get(CONF_MIN_SURPLUS, DEFAULT_MIN_SURPLUS),
        CONF_BOILER1_POWER: entry.options.get(CONF_BOILER1_POWER, DEFAULT_BOILER_POWER),
        CONF_BOILER2_POWER: entry.options.get(CONF_BOILER2_POWER, DEFAULT_BOILER_POWER),
        RUNTIME_AUTO_1: True,
        RUNTIME_AUTO_2: True,
    }

    coordinator = BoilerCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator

    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: BoilerCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.async_cancel_subscriptions()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — sync new values into runtime store."""
    store = hass.data[DOMAIN][entry.entry_id]
    for key, default in [
        (CONF_MAX_TEMP_1, DEFAULT_MAX_TEMP),
        (CONF_MAX_TEMP_2, DEFAULT_MAX_TEMP),
        (CONF_MIN_SURPLUS, DEFAULT_MIN_SURPLUS),
        (CONF_BOILER1_POWER, DEFAULT_BOILER_POWER),
        (CONF_BOILER2_POWER, DEFAULT_BOILER_POWER),
    ]:
        store[key] = entry.options.get(key, default)
