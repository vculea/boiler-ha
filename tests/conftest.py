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

    from datetime import datetime, timezone

    ha_dt = MagicMock()
    ha_dt.now = lambda: datetime.now(timezone.utc)
    ha_dt.utcnow = lambda: datetime.now(timezone.utc)
    ha_dt.as_utc = lambda d: d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    ha_dt.parse_datetime = lambda s: datetime.fromisoformat(s) if s else None

    ha_util = MagicMock()
    ha_util.dt = ha_dt

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
        "homeassistant.components.datetime": MagicMock(),
        "homeassistant.util": ha_util,
        "homeassistant.util.dt": ha_dt,
    }

    for name, stub in stubs.items():
        if name not in sys.modules:
            sys.modules[name] = stub


_stub_ha_modules()
