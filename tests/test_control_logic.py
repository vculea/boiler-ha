"""Exhaustive unit tests for all decision scenarios in BoilerCoordinator.

Each test maps to one row from the decision table in README.md.
Cases already covered by other test files (temperature hysteresis S3-S6,
overvoltage boost/hysteresis S9-S11) are not duplicated here.

S1  — Normal solar heating: sufficient surplus, temp below threshold → ON
S2  — Insufficient surplus → stays OFF
S3  — Temperature protection: temp >= target, relay ON → OFF  [test_temp_hysteresis.py]
S4  — Temp hysteresis in band, relay OFF → stays OFF          [test_temp_hysteresis.py]
S5  — Temp below hysteresis threshold → restart               [test_temp_hysteresis.py]
S6  — Relay ON inside hysteresis band → keeps running         [test_temp_hysteresis.py]
S7  — Low-temp priority: temp < 50% of target, no surplus → forced ON
S8  — Overvoltage priority: voltage > 250V, no surplus → forced ON
S9  — Overvoltage target boost                                [test_voltage_boost.py]
S10 — Overvoltage voltage hysteresis band                     [test_voltage_boost.py]
S11 — Overvoltage cleared, target restored                    [test_voltage_boost.py]
S12 — Auto mode OFF: relay not touched by auto control
S13 — Temperature sensor unavailable: relay not touched
S14 — Boiler 2: surplus insufficient after Boiler 1 → B2 stays OFF
S15 — Boiler 2: surplus sufficient after Boiler 1 → B2 turns ON
S16 — Balance: B1 too hot vs B2 in priority mode → B1 held back
S17 — Balance: B2 too hot vs B1 in priority mode → B2 held back
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
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
    TEMP_BALANCE_MAX_DIFF,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
    DEFAULT_PRIORITY_VOLTAGE,
    RUNTIME_HIGH_VOLTAGE_SINCE,
    OVERVOLTAGE_TRIGGER_DELAY,
    RUNTIME_VOLTAGE_STAGGER_SINCE,
    OVERVOLTAGE_STAGGER_DELAY,
)

MAX_TEMP = 65.0
AMPLE_SURPLUS = DEFAULT_MIN_SURPLUS + 5000.0   # well above threshold
LOW_SURPLUS = DEFAULT_MIN_SURPLUS - 100.0       # below threshold
NORMAL_VOLTAGE = 230.0                          # well below overvoltage threshold
HIGH_VOLTAGE = DEFAULT_PRIORITY_VOLTAGE + 5.0  # above overvoltage threshold


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_coord(
    *,
    temp1: float | None = 50.0,
    temp2: float | None = 50.0,
    max_temp: float = MAX_TEMP,
    relay1_on: bool = False,
    relay2_on: bool = False,
    grid_export: float = AMPLE_SURPLUS,
    voltage: float = NORMAL_VOLTAGE,
    auto_1: bool = True,
    auto_2: bool = True,
) -> tuple[BoilerCoordinator, dict[str, Any]]:
    entry_id = "test_cl"
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
        RUNTIME_AUTO_1: auto_1,
        RUNTIME_AUTO_2: auto_2,
    }

    hass = MagicMock()
    hass.data = {DOMAIN: {entry_id: rt}}

    coord: BoilerCoordinator = object.__new__(BoilerCoordinator)
    coord.hass = hass
    coord.entry = entry
    coord._float_state = lambda eid: {  # type: ignore[method-assign]
        "sensor.temp1": temp1,
        "sensor.temp2": temp2,
        "sensor.solar": 3000.0,
        "sensor.grid": grid_export,
        "sensor.voltage": voltage,
    }.get(eid)
    coord._is_on = lambda eid: {  # type: ignore[method-assign]
        "switch.relay1": relay1_on,
        "switch.relay2": relay2_on,
    }.get(eid, False)
    coord._set_switch = AsyncMock()  # type: ignore[method-assign]

    return coord, rt


def _turned_on(coord: BoilerCoordinator, relay: str) -> bool:
    return any(c.args == (relay, True) for c in coord._set_switch.call_args_list)


def _turned_off(coord: BoilerCoordinator, relay: str) -> bool:
    return any(c.args == (relay, False) for c in coord._set_switch.call_args_list)


def _not_touched(coord: BoilerCoordinator, relay: str) -> bool:
    return not any(c.args[0] == relay for c in coord._set_switch.call_args_list)


# ---------------------------------------------------------------------------
# S1 — Normal solar heating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s1_normal_solar_heating_b1():
    """S1 — Sufficient surplus AND temp well below target → Boiler 1 turns ON."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 5.0  # safely below restart threshold
    coord, _ = _make_coord(temp1=temp_cold, temp2=temp_cold, grid_export=AMPLE_SURPLUS)

    await coord._apply_control_logic()

    assert _turned_on(coord, "switch.relay1"), "B1 must turn ON when surplus is sufficient and temp is low"


@pytest.mark.asyncio
async def test_s1_normal_solar_heating_b2():
    """S1 — With enough surplus for both boilers, Boiler 2 also turns ON."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 5.0
    # Surplus must cover B1 + B2 (two boiler powers above minimum)
    surplus = DEFAULT_MIN_SURPLUS + DEFAULT_BOILER_POWER * 2 + 100.0
    coord, _ = _make_coord(temp1=temp_cold, temp2=temp_cold, grid_export=surplus)

    await coord._apply_control_logic()

    assert _turned_on(coord, "switch.relay1"), "B1 must turn ON"
    assert _turned_on(coord, "switch.relay2"), "B2 must turn ON when surplus covers both boilers"


# ---------------------------------------------------------------------------
# S2 — Insufficient surplus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s2_insufficient_surplus_b1_stays_off():
    """S2 — Surplus below minimum threshold → Boiler 1 stays OFF."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 5.0
    coord, _ = _make_coord(temp1=temp_cold, temp2=temp_cold, grid_export=LOW_SURPLUS)

    await coord._apply_control_logic()

    assert not _turned_on(coord, "switch.relay1"), "B1 must NOT start when surplus is below threshold"


@pytest.mark.asyncio
async def test_s2_insufficient_surplus_b1_turns_off():
    """S2 — When B1 is ON, virtual_surplus = grid_export + B1_power.
    B1 turns OFF only when even the virtual surplus drops below the threshold,
    i.e. grid_export < min_surplus - B1_power (grid is importing enough to cancel B1's contribution)."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 5.0
    # virtual_surplus = grid_export + B1_power < min_surplus
    # → grid_export < min_surplus - B1_power  (negative = importing from grid)
    grid_export_too_low = DEFAULT_MIN_SURPLUS - DEFAULT_BOILER_POWER - 100.0  # e.g. -800 W
    coord, _ = _make_coord(
        temp1=temp_cold, temp2=temp_cold,
        relay1_on=True, grid_export=grid_export_too_low,
    )

    await coord._apply_control_logic()

    assert _turned_off(coord, "switch.relay1"), (
        f"B1 must turn OFF when virtual_surplus ({grid_export_too_low + DEFAULT_BOILER_POWER:.0f}W) "
        f"drops below min_surplus ({DEFAULT_MIN_SURPLUS:.0f}W)"
    )


# ---------------------------------------------------------------------------
# S7 — Low-temp priority (temp < 50% of target)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s7_low_temp_priority_ignores_surplus():
    """S7 — When temp < 50% of target, boiler starts even with zero surplus."""
    temp_very_cold = MAX_TEMP * 0.5 - 1.0  # below 50% of target
    coord, _ = _make_coord(
        temp1=temp_very_cold, temp2=temp_very_cold,
        grid_export=LOW_SURPLUS,  # surplus below normal threshold
    )

    await coord._apply_control_logic()

    assert _turned_on(coord, "switch.relay1"), (
        f"B1 must start in low-temp priority mode (temp={temp_very_cold} < 50% of {MAX_TEMP})"
        " even without sufficient surplus"
    )


@pytest.mark.asyncio
async def test_s7_no_priority_when_temp_above_half_target():
    """S7 inverse — temp above 50% threshold, no priority, low surplus → stays OFF."""
    temp_above_half = MAX_TEMP * 0.5 + 1.0  # above 50%
    # Temp also above hysteresis restart threshold
    temp = max(temp_above_half, MAX_TEMP - TEMP_HYSTERESIS + 1.0)
    coord, _ = _make_coord(temp1=temp, temp2=temp, grid_export=LOW_SURPLUS)

    await coord._apply_control_logic()

    assert not _turned_on(coord, "switch.relay1"), (
        "B1 must NOT start without priority when surplus is insufficient"
    )


# ---------------------------------------------------------------------------
# S8 — Overvoltage priority: forced ON regardless of surplus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s8_overvoltage_forces_start_with_low_surplus():
    """S8 — Overvoltage (>250V) forces both boilers ON (once stagger expires) even when
    surplus is below threshold."""
    temp_below_target = MAX_TEMP - TEMP_HYSTERESIS - 5.0
    coord, rt = _make_coord(
        temp1=temp_below_target, temp2=temp_below_target,
        grid_export=LOW_SURPLUS,
        voltage=HIGH_VOLTAGE,
    )
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)
    # Simulate stagger already expired so both boilers are allowed to start
    rt[RUNTIME_VOLTAGE_STAGGER_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_STAGGER_DELAY + 1)

    await coord._apply_control_logic()

    assert _turned_on(coord, "switch.relay1"), "B1 must start during overvoltage regardless of surplus"
    assert _turned_on(coord, "switch.relay2"), "B2 must also start during overvoltage regardless of surplus"


@pytest.mark.asyncio
async def test_s8_overvoltage_stagger_cooler_boiler_starts_first():
    """S8 stagger — When overvoltage activates, the cooler boiler starts immediately
    and the warmer one waits for the stagger delay."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 10.0
    temp_warm = temp_cold + 3.0   # B1 is warmer by 3°C (within balance threshold)
    coord, rt = _make_coord(
        temp1=temp_warm, temp2=temp_cold,
        grid_export=LOW_SURPLUS,
        voltage=HIGH_VOLTAGE,
    )
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)
    # No stagger timer set — first cycle, stagger just started

    await coord._apply_control_logic()

    assert _turned_on(coord, "switch.relay2"), "Cooler boiler (B2) must start immediately"
    assert not _turned_on(coord, "switch.relay1"), "Warmer boiler (B1) must wait for stagger delay"


@pytest.mark.asyncio
async def test_s8_overvoltage_stagger_second_boiler_starts_after_delay():
    """S8 stagger — After the stagger delay, the warmer boiler also starts."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 10.0
    temp_warm = temp_cold + 3.0   # within balance threshold so balance doesn't interfere
    coord, rt = _make_coord(
        temp1=temp_warm, temp2=temp_cold,
        grid_export=LOW_SURPLUS,
        voltage=HIGH_VOLTAGE,
    )
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)
    rt[RUNTIME_VOLTAGE_STAGGER_SINCE] = datetime.now() - timedelta(seconds=OVERVOLTAGE_STAGGER_DELAY + 1)

    await coord._apply_control_logic()

    assert _turned_on(coord, "switch.relay1"), "B1 (warmer) must start after stagger delay"
    assert _turned_on(coord, "switch.relay2"), "B2 (cooler) must still be running"


# ---------------------------------------------------------------------------
# S12 — Auto mode OFF
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s12_auto_off_boiler_not_started():
    """S12 — When auto is OFF, a boiler that would otherwise start is not touched."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 5.0
    coord, _ = _make_coord(
        temp1=temp_cold, temp2=temp_cold,
        grid_export=AMPLE_SURPLUS,
        auto_1=False, auto_2=False,
    )

    await coord._apply_control_logic()

    assert _not_touched(coord, "switch.relay1"), "B1 relay must not be touched when auto is OFF"
    assert _not_touched(coord, "switch.relay2"), "B2 relay must not be touched when auto is OFF"


@pytest.mark.asyncio
async def test_s12_auto_off_running_boiler_not_stopped():
    """S12 — When auto is OFF, a boiler that would otherwise stop (low surplus) is not touched."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 5.0
    coord, _ = _make_coord(
        temp1=temp_cold, temp2=temp_cold,
        relay1_on=True, relay2_on=True,
        grid_export=LOW_SURPLUS,
        auto_1=False, auto_2=False,
    )

    await coord._apply_control_logic()

    assert _not_touched(coord, "switch.relay1"), "B1 relay must not be touched when auto is OFF"
    assert _not_touched(coord, "switch.relay2"), "B2 relay must not be touched when auto is OFF"


@pytest.mark.asyncio
async def test_s12_temp_protection_still_fires_when_auto_off():
    """S12 exception — temperature protection always fires, even when auto is OFF."""
    coord, _ = _make_coord(
        temp1=MAX_TEMP, temp2=MAX_TEMP,
        relay1_on=True, relay2_on=True,
        auto_1=False, auto_2=False,
    )

    await coord._apply_control_logic()

    assert _turned_off(coord, "switch.relay1"), "B1 must be turned OFF by protection even when auto is OFF"
    assert _turned_off(coord, "switch.relay2"), "B2 must be turned OFF by protection even when auto is OFF"


# ---------------------------------------------------------------------------
# S13 — Temperature sensor unavailable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s13_sensor_unavailable_boiler_not_started():
    """S13 — When temp sensor returns None, relay must not be touched."""
    coord, _ = _make_coord(temp1=None, temp2=None, grid_export=AMPLE_SURPLUS)

    await coord._apply_control_logic()

    assert _not_touched(coord, "switch.relay1"), "B1 relay must not be touched when sensor is unavailable"
    assert _not_touched(coord, "switch.relay2"), "B2 relay must not be touched when sensor is unavailable"


@pytest.mark.asyncio
async def test_s13_sensor_unavailable_running_boiler_not_stopped():
    """S13 — With unavailable sensor, a running boiler is not stopped (cannot confirm safety)."""
    coord, _ = _make_coord(
        temp1=None, temp2=None,
        relay1_on=True, relay2_on=True,
        grid_export=AMPLE_SURPLUS,
    )

    await coord._apply_control_logic()

    assert _not_touched(coord, "switch.relay1"), "B1 relay must not be touched when sensor is unavailable"
    assert _not_touched(coord, "switch.relay2"), "B2 relay must not be touched when sensor is unavailable"


# ---------------------------------------------------------------------------
# S14 — Boiler 2: surplus insufficient after Boiler 1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s14_b2_blocked_when_surplus_consumed_by_b1():
    """S14 — Surplus is just enough for B1 but not enough left for B2."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 5.0
    # Surplus = min_surplus + B1_power - 100 W  →  after B1 consumes its power, remainder < min_surplus
    surplus = DEFAULT_MIN_SURPLUS + DEFAULT_BOILER_POWER - 100.0
    coord, _ = _make_coord(temp1=temp_cold, temp2=temp_cold, grid_export=surplus)

    await coord._apply_control_logic()

    assert _turned_on(coord, "switch.relay1"), "B1 must start (sufficient surplus)"
    assert not _turned_on(coord, "switch.relay2"), (
        "B2 must NOT start — remaining surplus after B1 is below minimum threshold"
    )


# ---------------------------------------------------------------------------
# S15 — Boiler 2: surplus sufficient after Boiler 1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s15_b2_starts_when_surplus_covers_both():
    """S15 — Surplus covers B1 + B2 → both turn ON."""
    temp_cold = MAX_TEMP - TEMP_HYSTERESIS - 5.0
    # surplus_virtual = export + B1_power (since B1 will be ON after cycle)
    # For B2: surplus_after_b1 = virtual_surplus - B1_power = export >= min_surplus
    surplus = DEFAULT_MIN_SURPLUS + DEFAULT_BOILER_POWER + 100.0
    coord, _ = _make_coord(temp1=temp_cold, temp2=temp_cold, grid_export=surplus)

    await coord._apply_control_logic()

    assert _turned_on(coord, "switch.relay1"), "B1 must start"
    assert _turned_on(coord, "switch.relay2"), "B2 must also start when surplus covers both"


# ---------------------------------------------------------------------------
# S16 — Balance: B1 too hot vs B2, priority mode active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s16_b1_held_back_when_too_hot_vs_b2():
    """S16 — In priority mode, if B1 is more than TEMP_BALANCE_MAX_DIFF°C hotter than B2,
    B1 is held back so B2 can catch up."""
    # B2 is cold enough to trigger low-temp priority
    temp2_cold = MAX_TEMP * 0.5 - 5.0
    # B1 is much hotter than B2
    temp1_hot = temp2_cold + TEMP_BALANCE_MAX_DIFF + 2.0

    coord, _ = _make_coord(
        temp1=temp1_hot, temp2=temp2_cold,
        grid_export=LOW_SURPLUS,  # no solar → priority must drive decisions
    )

    await coord._apply_control_logic()

    assert not _turned_on(coord, "switch.relay1"), (
        f"B1 must be held back (temp1={temp1_hot} is >{TEMP_BALANCE_MAX_DIFF}°C "
        f"hotter than temp2={temp2_cold})"
    )
    assert _turned_on(coord, "switch.relay2"), "B2 must run (it triggered low-temp priority)"


# ---------------------------------------------------------------------------
# S17 — Balance: B2 too hot vs B1, priority mode active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s17_b2_held_back_when_too_hot_vs_b1():
    """S17 — In priority mode, if B2 is more than TEMP_BALANCE_MAX_DIFF°C hotter than B1,
    B2 is held back so B1 can catch up."""
    temp1_cold = MAX_TEMP * 0.5 - 5.0
    temp2_hot = temp1_cold + TEMP_BALANCE_MAX_DIFF + 2.0

    coord, _ = _make_coord(
        temp1=temp1_cold, temp2=temp2_hot,
        grid_export=LOW_SURPLUS,
    )

    await coord._apply_control_logic()

    assert _turned_on(coord, "switch.relay1"), "B1 must run (it triggered low-temp priority)"
    assert not _turned_on(coord, "switch.relay2"), (
        f"B2 must be held back (temp2={temp2_hot} is >{TEMP_BALANCE_MAX_DIFF}°C "
        f"hotter than temp1={temp1_cold})"
    )
