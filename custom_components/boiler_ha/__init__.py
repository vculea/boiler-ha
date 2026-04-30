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
    RUNTIME_SCHEDULE_TARGET,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
    DEFAULT_SCHEDULE_TARGET,
)
from .coordinator import BoilerCoordinator

_LOGGER = logging.getLogger(__name__)

# Old defaults that should be migrated to current defaults on next load
_LEGACY_DEFAULTS = {
    CONF_MIN_SURPLUS: (500.0, DEFAULT_MIN_SURPLUS),    # 500 → 800 W
    CONF_BOILER1_POWER: (2000.0, DEFAULT_BOILER_POWER), # 2000 → 1500 W
    CONF_BOILER2_POWER: (2000.0, DEFAULT_BOILER_POWER), # 2000 → 1500 W
}


async def _migrate_legacy_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """If saved options still hold old default values, upgrade them silently."""
    updates = {}
    for key, (old_val, new_val) in _LEGACY_DEFAULTS.items():
        if entry.options.get(key) == old_val:
            updates[key] = new_val
    if updates:
        new_options = {**entry.options, **updates}
        hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info("Boiler HA: valori implicite migrate %s", updates)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Boiler Solar Controller from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    await _migrate_legacy_options(hass, entry)

    # Initialize runtime store (for values controlled by switch/number entities)
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_MAX_TEMP_1: entry.options.get(CONF_MAX_TEMP_1, DEFAULT_MAX_TEMP),
        CONF_MAX_TEMP_2: entry.options.get(CONF_MAX_TEMP_2, DEFAULT_MAX_TEMP),
        CONF_MIN_SURPLUS: entry.options.get(CONF_MIN_SURPLUS, DEFAULT_MIN_SURPLUS),
        CONF_BOILER1_POWER: entry.options.get(CONF_BOILER1_POWER, DEFAULT_BOILER_POWER),
        CONF_BOILER2_POWER: entry.options.get(CONF_BOILER2_POWER, DEFAULT_BOILER_POWER),
        RUNTIME_AUTO_1: True,
        RUNTIME_AUTO_2: True,
        # Schedule target initialized to default so the coordinator sees it even
        # before the user explicitly moves the slider (slider shows default visually
        # but doesn't write to rt until actually changed).
        RUNTIME_SCHEDULE_TARGET: DEFAULT_SCHEDULE_TARGET,
        # RUNTIME_SCHEDULE_DEADLINE intentionally absent (None = no active schedule)
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
