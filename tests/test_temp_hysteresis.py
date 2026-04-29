"""Unit tests for temperature hysteresis logic in BoilerCoordinator.

After a boiler reaches its target temperature and the relay is turned off,
it must NOT restart until the temperature drops at least TEMP_HYSTERESIS degrees
below the target. While the boiler is still ON it may keep running all the way
up to max_temp (no early cut-off from hysteresis).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

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
    TEMP_HYSTERESIS,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_coord(
    *,
    temp1: float,
    temp2: float,
    max_temp: float,
    relay1_on: bool = False,
    relay2_on: bool = False,
    grid_export: float = 5000.0,   # ample surplus so surplus is never the limiting factor
    voltage: float = 230.0,        # well below overvoltage threshold
) -> tuple[BoilerCoordinator, dict[str, Any], dict]:
    """Build a minimal BoilerCoordinator with a mutable sensor-state dict."""
    entry_id = "test_hyst"
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

    sensors: dict = {
        "sensor.temp1": temp1,
        "sensor.temp2": temp2,
        "sensor.solar": 3000.0,
        "sensor.grid": grid_export,
        "sensor.voltage": voltage,
    }
    switches: dict = {
        "switch.relay1": relay1_on,
        "switch.relay2": relay2_on,
    }

    coord: BoilerCoordinator = object.__new__(BoilerCoordinator)
    coord.hass = hass
    coord.entry = entry
    coord._float_state = lambda eid: sensors.get(eid)  # type: ignore[method-assign]
    coord._is_on = lambda eid: switches.get(eid, False)  # type: ignore[method-assign]
    coord._set_switch = AsyncMock()  # type: ignore[method-assign]

    return coord, rt, sensors


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boiler_does_not_restart_just_below_target():
    """After switching OFF, boiler must NOT restart if temp is just below max_temp
    but still above (max_temp - TEMP_HYSTERESIS)."""
    max_temp = 65.0
    # Boiler was ON, reached target → protection code already turned it off.
    # Simulate: relay is now OFF, temp has cooled only 1 °C below target.
    temp_just_below = max_temp - 1.0  # 64 °C — inside hysteresis band

    coord, rt, sensors = _make_coord(temp1=temp_just_below, temp2=temp_just_below, max_temp=max_temp)

    await coord._apply_control_logic()

    # Boiler should NOT have been turned on
    for call in coord._set_switch.call_args_list:
        entity, state = call.args
        if entity == "switch.relay1":
            assert state is False, (
                f"Boiler 1 must not restart at {temp_just_below} °C "
                f"(hysteresis requires < {max_temp - TEMP_HYSTERESIS} °C)"
            )
        if entity == "switch.relay2":
            assert state is False, (
                f"Boiler 2 must not restart at {temp_just_below} °C "
                f"(hysteresis requires < {max_temp - TEMP_HYSTERESIS} °C)"
            )


@pytest.mark.asyncio
async def test_boiler_does_not_restart_at_exact_hysteresis_boundary():
    """Boiler must NOT restart when temp equals exactly (max_temp - TEMP_HYSTERESIS).
    The condition is strict less-than, so the boundary itself must not trigger a restart."""
    max_temp = 65.0
    temp_at_boundary = max_temp - TEMP_HYSTERESIS  # exactly 60 °C

    coord, rt, sensors = _make_coord(temp1=temp_at_boundary, temp2=temp_at_boundary, max_temp=max_temp)

    await coord._apply_control_logic()

    for call in coord._set_switch.call_args_list:
        entity, state = call.args
        if entity in ("switch.relay1", "switch.relay2"):
            assert state is False, (
                f"Boiler must not restart at exactly the hysteresis boundary "
                f"({temp_at_boundary} °C)"
            )


@pytest.mark.asyncio
async def test_boiler_restarts_below_hysteresis_threshold():
    """Boiler MUST restart once temp drops strictly below (max_temp - TEMP_HYSTERESIS)."""
    max_temp = 65.0
    temp_below = max_temp - TEMP_HYSTERESIS - 0.1  # 59.9 °C — just past the threshold

    coord, rt, sensors = _make_coord(temp1=temp_below, temp2=temp_below, max_temp=max_temp)

    await coord._apply_control_logic()

    turn_on_calls = [
        call for call in coord._set_switch.call_args_list
        if call.args[0] == "switch.relay1" and call.args[1] is True
    ]
    assert turn_on_calls, (
        f"Boiler 1 must restart when temp ({temp_below} °C) drops below "
        f"hysteresis threshold ({max_temp - TEMP_HYSTERESIS} °C)"
    )


@pytest.mark.asyncio
async def test_boiler_keeps_running_up_to_target_while_on():
    """While the relay is already ON, hysteresis must not apply — boiler keeps
    running all the way up to max_temp."""
    max_temp = 65.0
    # Temp is in the zone where a just-OFF boiler would be blocked by hysteresis,
    # but the relay is currently ON — it should keep running.
    temp_in_band = max_temp - TEMP_HYSTERESIS + 1.0  # 61 °C

    coord, rt, sensors = _make_coord(
        temp1=temp_in_band, temp2=temp_in_band, max_temp=max_temp,
        relay1_on=True, relay2_on=True,
    )

    await coord._apply_control_logic()

    # Must NOT have been turned off (no turn_off call for relay1)
    turn_off_calls = [
        call for call in coord._set_switch.call_args_list
        if call.args[0] == "switch.relay1" and call.args[1] is False
    ]
    assert not turn_off_calls, (
        f"Boiler 1 must keep running at {temp_in_band} °C while relay is ON "
        f"(hysteresis only blocks restart, not continued operation)"
    )


@pytest.mark.asyncio
async def test_two_cycle_sequence_off_then_restart():
    """Full lifecycle: boiler is ON → reaches target → turns OFF → temp drops →
    must not restart until below (max_temp - TEMP_HYSTERESIS)."""
    max_temp = 65.0

    # --- Cycle 1: relay ON, temp at target → protection turns it off ---
    coord, rt, sensors = _make_coord(
        temp1=max_temp, temp2=max_temp, max_temp=max_temp,
        relay1_on=True, relay2_on=True,
    )

    await coord._apply_control_logic()

    turn_off_b1 = [c for c in coord._set_switch.call_args_list if c.args == ("switch.relay1", False)]
    assert turn_off_b1, "Cycle 1: boiler must be turned OFF when temp reaches max_temp"

    # --- Cycle 2: relay OFF, temp cooled to just inside hysteresis band → no restart ---
    coord._set_switch.reset_mock()
    coord._is_on = lambda eid: False  # type: ignore[method-assign]
    sensors["sensor.temp1"] = max_temp - 1.0
    sensors["sensor.temp2"] = max_temp - 1.0

    await coord._apply_control_logic()

    turn_on_in_band = [c for c in coord._set_switch.call_args_list if c.args[1] is True]
    assert not turn_on_in_band, "Cycle 2: must NOT restart inside hysteresis band"

    # --- Cycle 3: temp drops below threshold → restart allowed ---
    coord._set_switch.reset_mock()
    sensors["sensor.temp1"] = max_temp - TEMP_HYSTERESIS - 0.1
    sensors["sensor.temp2"] = max_temp - TEMP_HYSTERESIS - 0.1

    await coord._apply_control_logic()

    turn_on_after = [c for c in coord._set_switch.call_args_list if c.args == ("switch.relay1", True)]
    assert turn_on_after, "Cycle 3: boiler must restart once temp drops below hysteresis threshold"
