"""Stub homeassistant modules so the integration can be imported without a full HA install."""
import sys
from unittest.mock import MagicMock


def _stub_ha_modules() -> None:
    """Insert lightweight stubs for every homeassistant module used by the integration."""

    class _DataUpdateCoordinator:
        def __init__(self, hass, logger, *, name, update_interval):
            pass

    class _UpdateFailed(Exception):
        pass

    ha_const = MagicMock()
    ha_const.STATE_ON = "on"
    ha_const.STATE_UNAVAILABLE = "unavailable"
    ha_const.STATE_UNKNOWN = "unknown"

    ha_coordinator = MagicMock()
    ha_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
    ha_coordinator.UpdateFailed = _UpdateFailed

    stubs = {
        "homeassistant": MagicMock(),
        "homeassistant.const": ha_const,
        "homeassistant.core": MagicMock(),
        "homeassistant.helpers": MagicMock(),
        "homeassistant.helpers.event": MagicMock(),
        "homeassistant.helpers.update_coordinator": ha_coordinator,
        "homeassistant.config_entries": MagicMock(),
        "homeassistant.helpers.entity": MagicMock(),
        "homeassistant.helpers.entity_platform": MagicMock(),
        "homeassistant.helpers.restore_state": MagicMock(),
        "homeassistant.components": MagicMock(),
        "homeassistant.components.sensor": MagicMock(),
        "homeassistant.components.number": MagicMock(),
        "homeassistant.components.switch": MagicMock(),
    }

    for name, stub in stubs.items():
        if name not in sys.modules:
            sys.modules[name] = stub


_stub_ha_modules()
