"""Unit tests for overvoltage target-boost logic in BoilerCoordinator."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is on sys.path so the integration can be imported directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.boiler_ha.coordinator import BoilerCoordinator  # noqa: E402
from custom_components.boiler_ha.const import (  # noqa: E402
    DOMAIN,
    CONF_RELAY_1,
    CONF_RELAY_2,
    CONF_TEMP_SENSOR_1,
    CONF_TEMP_SENSOR_2,
    CONF_SOLAR_SENSOR,
    CONF_GRID_SENSOR,
    CONF_VOLTAGE_SENSOR,
    CONF_GRID_POSITIVE_IS_EXPORT,
    CONF_MAX_TEMP_1,
    CONF_MAX_TEMP_2,
    CONF_MIN_SURPLUS,
    CONF_BOILER1_POWER,
    CONF_BOILER2_POWER,
    RUNTIME_AUTO_1,
    RUNTIME_AUTO_2,
    RUNTIME_USER_MAX_TEMP_1,
    RUNTIME_USER_MAX_TEMP_2,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
    VOLTAGE_OVERHEAT_BOOST,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coordinator(
    *,
    temp1: float = 60.0,
    temp2: float = 60.0,
    max_temp: float = 60.0,
    voltage: float = 245.0,
    relay1_on: bool = False,
    relay2_on: bool = False,
    grid_export: float = 2000.0,
) -> tuple[BoilerCoordinator, dict[str, Any]]:
    """Build a minimal BoilerCoordinator with mocked hass/entry, bypassing HA init."""
    entry_id = "test_entry"

    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {
        CONF_RELAY_1: "switch.relay1",
        CONF_RELAY_2: "switch.relay2",
        CONF_TEMP_SENSOR_1: "sensor.temp1",
        CONF_TEMP_SENSOR_2: "sensor.temp2",
        CONF_SOLAR_SENSOR: "sensor.solar",
        CONF_GRID_SENSOR: "sensor.grid",
        CONF_VOLTAGE_SENSOR: "sensor.voltage",
        CONF_GRID_POSITIVE_IS_EXPORT: True,
    }
    entry.options = {}

    rt: dict[str, Any] = {
        CONF_MAX_TEMP_1: max_temp,
        CONF_MAX_TEMP_2: max_temp,
        CONF_MIN_SURPLUS: DEFAULT_MIN_SURPLUS,
        CONF_BOILER1_POWER: DEFAULT_BOILER_POWER,
        CONF_BOILER2_POWER: DEFAULT_BOILER_POWER,
        RUNTIME_AUTO_1: True,
        RUNTIME_AUTO_2: True,
    }

    hass = MagicMock()
    hass.data = {DOMAIN: {entry_id: rt}}

    def _float_state_fn(eid: str, _states: dict = {
        "sensor.temp1": temp1,
        "sensor.temp2": temp2,
        "sensor.solar": 3000.0,
        "sensor.grid": grid_export,
        "sensor.voltage": voltage,
    }) -> float | None:
        return _states.get(eid)

    _switches = {
        "switch.relay1": relay1_on,
        "switch.relay2": relay2_on,
    }

    # Build coordinator instance WITHOUT calling DataUpdateCoordinator.__init__
    coord: BoilerCoordinator = object.__new__(BoilerCoordinator)
    coord.hass = hass
    coord.entry = entry

    # Patch low-level HA helpers on the instance directly
    coord._float_state = lambda eid: {  # type: ignore[method-assign]
        "sensor.temp1": temp1,
        "sensor.temp2": temp2,
        "sensor.solar": 3000.0,
        "sensor.grid": grid_export,
        "sensor.voltage": voltage,
    }.get(eid)
    coord._is_on = lambda eid: _switches.get(eid, False)  # type: ignore[method-assign]
    coord._set_switch = AsyncMock()  # type: ignore[method-assign]

    return coord, rt


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boost_activates_when_overvoltage_and_target_reached():
    """Target is raised by VOLTAGE_OVERHEAT_BOOST when voltage is high AND temp >= max_temp."""
    coord, rt = _make_coordinator(temp1=60.0, temp2=60.0, max_temp=60.0, voltage=255.0)

    await coord._apply_control_logic()

    expected = min(60.0 + VOLTAGE_OVERHEAT_BOOST, DEFAULT_MAX_TEMP)
    assert rt[CONF_MAX_TEMP_1] == expected, f"Expected {expected}, got {rt[CONF_MAX_TEMP_1]}"
    assert rt[CONF_MAX_TEMP_2] == expected
    assert rt[RUNTIME_USER_MAX_TEMP_1] == 60.0, "Original target must be saved for later restore"
    assert rt[RUNTIME_USER_MAX_TEMP_2] == 60.0


@pytest.mark.asyncio
async def test_boost_caps_at_default_max_temp():
    """Boosted target must never exceed DEFAULT_MAX_TEMP (90 °C)."""
    # 88 + 5 = 93 → must be capped at 90
    coord, rt = _make_coordinator(temp1=88.0, temp2=88.0, max_temp=88.0, voltage=255.0)

    await coord._apply_control_logic()

    assert rt[CONF_MAX_TEMP_1] == DEFAULT_MAX_TEMP
    assert rt[CONF_MAX_TEMP_2] == DEFAULT_MAX_TEMP


@pytest.mark.asyncio
async def test_no_boost_when_temp_below_target():
    """Target must NOT change if temp hasn't reached max_temp yet."""
    coord, rt = _make_coordinator(temp1=55.0, temp2=55.0, max_temp=60.0, voltage=255.0)

    await coord._apply_control_logic()

    assert rt[CONF_MAX_TEMP_1] == 60.0
    assert rt[CONF_MAX_TEMP_2] == 60.0
    assert RUNTIME_USER_MAX_TEMP_1 not in rt
    assert RUNTIME_USER_MAX_TEMP_2 not in rt


@pytest.mark.asyncio
async def test_no_boost_when_voltage_normal():
    """No boost when voltage is below the overvoltage threshold."""
    coord, rt = _make_coordinator(temp1=60.0, temp2=60.0, max_temp=60.0, voltage=245.0)

    await coord._apply_control_logic()

    assert rt[CONF_MAX_TEMP_1] == 60.0
    assert rt[CONF_MAX_TEMP_2] == 60.0
    assert RUNTIME_USER_MAX_TEMP_1 not in rt


@pytest.mark.asyncio
async def test_no_double_boost():
    """Calling twice under sustained overvoltage must not boost the target a second time."""
    coord, rt = _make_coordinator(temp1=60.0, temp2=60.0, max_temp=60.0, voltage=255.0)

    await coord._apply_control_logic()
    boosted_1 = rt[CONF_MAX_TEMP_1]
    boosted_2 = rt[CONF_MAX_TEMP_2]

    # Second call — temp still at 60 (below the now-boosted target)
    await coord._apply_control_logic()

    assert rt[CONF_MAX_TEMP_1] == boosted_1, "Second call must not boost again"
    assert rt[CONF_MAX_TEMP_2] == boosted_2


@pytest.mark.asyncio
async def test_restore_on_voltage_drop():
    """Original target is restored when overvoltage clears."""
    coord, rt = _make_coordinator(temp1=60.0, temp2=60.0, max_temp=60.0, voltage=255.0)

    # First cycle: overvoltage → boost
    await coord._apply_control_logic()
    assert rt[CONF_MAX_TEMP_1] == 60.0 + VOLTAGE_OVERHEAT_BOOST

    # Second cycle: voltage returns to normal
    coord._float_state = lambda eid: {  # type: ignore[method-assign]
        "sensor.temp1": 62.0,
        "sensor.temp2": 62.0,
        "sensor.solar": 3000.0,
        "sensor.grid": 2000.0,
        "sensor.voltage": 245.0,
    }.get(eid)

    await coord._apply_control_logic()

    assert rt[CONF_MAX_TEMP_1] == 60.0, "Original target must be restored after voltage drop"
    assert rt[CONF_MAX_TEMP_2] == 60.0
    assert RUNTIME_USER_MAX_TEMP_1 not in rt, "Saved original must be cleaned up"
    assert RUNTIME_USER_MAX_TEMP_2 not in rt
