"""Unit tests for overvoltage target-boost logic in BoilerCoordinator."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
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
    RUNTIME_VOLTAGE_BOOST_SINCE_1,
    RUNTIME_VOLTAGE_BOOST_SINCE_2,
    RUNTIME_HIGH_VOLTAGE,
    RUNTIME_HIGH_VOLTAGE_SINCE,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
    DEFAULT_PRIORITY_VOLTAGE,
    VOLTAGE_PRIORITY_RELEASE,
    VOLTAGE_OVERHEAT_BOOST,
    VOLTAGE_BOOST_MIN_DURATION,
    OVERVOLTAGE_TRIGGER_DELAY,
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
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)

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
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)

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
    """Original target is restored when overvoltage clears AND minimum hold time has elapsed."""
    coord, rt = _make_coordinator(temp1=60.0, temp2=60.0, max_temp=60.0, voltage=255.0)
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)

    # First cycle: overvoltage → boost
    await coord._apply_control_logic()
    assert rt[CONF_MAX_TEMP_1] == 60.0 + VOLTAGE_OVERHEAT_BOOST

    # Simulate that the boost was activated long enough ago (past the minimum duration)
    past_time = datetime.now() - timedelta(seconds=VOLTAGE_BOOST_MIN_DURATION + 1)
    rt[RUNTIME_VOLTAGE_BOOST_SINCE_1] = past_time
    rt[RUNTIME_VOLTAGE_BOOST_SINCE_2] = past_time

    # Second cycle: voltage returns to normal (clearly below VOLTAGE_PRIORITY_RELEASE)
    coord._float_state = lambda eid: {  # type: ignore[method-assign]
        "sensor.temp1": 62.0,
        "sensor.temp2": 62.0,
        "sensor.solar": 3000.0,
        "sensor.grid": 2000.0,
        "sensor.voltage": VOLTAGE_PRIORITY_RELEASE - 1.0,
    }.get(eid)

    await coord._apply_control_logic()

    assert rt[CONF_MAX_TEMP_1] == 60.0, "Original target must be restored after voltage drop"
    assert rt[CONF_MAX_TEMP_2] == 60.0
    assert RUNTIME_USER_MAX_TEMP_1 not in rt, "Saved original must be cleaned up"
    assert RUNTIME_USER_MAX_TEMP_2 not in rt


# ---------------------------------------------------------------------------
# Voltage hysteresis tests
# ---------------------------------------------------------------------------

def _make_coordinator_mutable_voltage(
    *,
    temp1: float = 50.0,
    temp2: float = 50.0,
    max_temp: float = 65.0,
    initial_voltage: float = 245.0,
) -> tuple[BoilerCoordinator, dict[str, Any], dict]:
    """Like _make_coordinator but voltage is stored in a mutable dict so tests can change it."""
    coord, rt = _make_coordinator(
        temp1=temp1, temp2=temp2, max_temp=max_temp, voltage=initial_voltage
    )
    sensor_state: dict = {"voltage": initial_voltage, "temp1": temp1, "temp2": temp2}

    def _float_state(eid: str) -> float | None:
        return {
            "sensor.temp1": sensor_state["temp1"],
            "sensor.temp2": sensor_state["temp2"],
            "sensor.solar": 3000.0,
            "sensor.grid": 2000.0,
            "sensor.voltage": sensor_state["voltage"],
        }.get(eid)

    coord._float_state = _float_state  # type: ignore[method-assign]
    return coord, rt, sensor_state


@pytest.mark.asyncio
async def test_high_voltage_activates_above_threshold():
    """high_voltage flag must be set when voltage exceeds DEFAULT_PRIORITY_VOLTAGE and delay has elapsed."""
    coord, rt, sensors = _make_coordinator_mutable_voltage(initial_voltage=251.0)
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)

    await coord._apply_control_logic()

    assert rt[RUNTIME_HIGH_VOLTAGE] is True


@pytest.mark.asyncio
async def test_high_voltage_not_set_below_threshold():
    """high_voltage flag must be False when voltage is below DEFAULT_PRIORITY_VOLTAGE."""
    coord, rt, sensors = _make_coordinator_mutable_voltage(initial_voltage=245.0)

    await coord._apply_control_logic()

    assert rt.get(RUNTIME_HIGH_VOLTAGE, False) is False


@pytest.mark.asyncio
async def test_high_voltage_stays_true_in_hysteresis_band():
    """Once active, high_voltage must remain True while voltage is in the hysteresis band
    (VOLTAGE_PRIORITY_RELEASE <= voltage <= DEFAULT_PRIORITY_VOLTAGE)."""
    coord, rt, sensors = _make_coordinator_mutable_voltage(initial_voltage=251.0)
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)

    # First cycle: voltage above threshold → activates after delay
    await coord._apply_control_logic()
    assert rt[RUNTIME_HIGH_VOLTAGE] is True

    # Second cycle: voltage drops into the band (248 V — between 246 and 250)
    sensors["voltage"] = (DEFAULT_PRIORITY_VOLTAGE + VOLTAGE_PRIORITY_RELEASE) / 2  # 248 V
    await coord._apply_control_logic()

    assert rt[RUNTIME_HIGH_VOLTAGE] is True, (
        "high_voltage must stay True in hysteresis band to prevent rapid cycling"
    )


@pytest.mark.asyncio
async def test_high_voltage_clears_below_release_threshold():
    """high_voltage must clear only when voltage drops below VOLTAGE_PRIORITY_RELEASE."""
    coord, rt, sensors = _make_coordinator_mutable_voltage(initial_voltage=251.0)
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)

    # Activate
    await coord._apply_control_logic()
    assert rt[RUNTIME_HIGH_VOLTAGE] is True

    # Drop below release threshold
    sensors["voltage"] = VOLTAGE_PRIORITY_RELEASE - 1.0  # 245 V
    await coord._apply_control_logic()

    assert rt[RUNTIME_HIGH_VOLTAGE] is False


@pytest.mark.asyncio
async def test_high_voltage_stays_false_in_hysteresis_band_when_not_active():
    """If high_voltage was never activated, voltage in the band must NOT activate it."""
    coord, rt, sensors = _make_coordinator_mutable_voltage(initial_voltage=248.0)

    await coord._apply_control_logic()

    assert rt.get(RUNTIME_HIGH_VOLTAGE, False) is False, (
        "Voltage in hysteresis band from below must not activate high_voltage"
    )

