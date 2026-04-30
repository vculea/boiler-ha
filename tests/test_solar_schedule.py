"""Unit tests for the solar-only heating schedule feature.

Scenarios tested:
  SC1  — Schedule active: target temp overrides max_temp, boiler starts on solar surplus
  SC2  — Schedule active: priority mode (grid consumption) is suppressed
  SC3  — Schedule expired (deadline in the past): no override, normal logic applies
  SC4  — Schedule inactive (no deadline set): no override
  SC5  — Boiler 1 reaches schedule target → done_1 flag set, B1 stops heating
  SC6  — Boiler 2 reaches schedule target → done_2 flag set independently
  SC7  — Both done → status sensor shows STATUS_SCHEDULE_DONE
  SC8  — Schedule active, auto OFF: schedule is ignored for that boiler
  SC9  — Schedule active, overvoltage: priority override is NOT suppressed (safety)
  SC10 — Overvoltage boost does NOT corrupt schedule target temp
  SC11 — Snapshot schedule_status reflects correct state (inactive / active / expired / done)
"""
from __future__ import annotations

import sys
from datetime import timezone
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
    RUNTIME_HIGH_VOLTAGE_SINCE,
    RUNTIME_SCHEDULE_TARGET,
    RUNTIME_SCHEDULE_DEADLINE,
    RUNTIME_SCHEDULE_DONE_1,
    RUNTIME_SCHEDULE_DONE_2,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
    DEFAULT_MAX_TEMP,
    DEFAULT_PRIORITY_VOLTAGE,
    OVERVOLTAGE_TRIGGER_DELAY,
    STATUS_SCHEDULE_SOLAR,
    STATUS_SCHEDULE_DONE,
    STATUS_SCHEDULE_EXPIRED,
    STATUS_SCHEDULE_INACTIVE,
)

# ---------------------------------------------------------------------------
# Constants used across tests
# ---------------------------------------------------------------------------

NORMAL_MAX_TEMP = 80.0          # regular user-set target
SCHED_TARGET = 55.0             # schedule target (lower than NORMAL_MAX_TEMP)
AMPLE_SURPLUS = DEFAULT_MIN_SURPLUS + 3000.0
LOW_SURPLUS = DEFAULT_MIN_SURPLUS - 100.0
NORMAL_VOLTAGE = 230.0
HIGH_VOLTAGE = DEFAULT_PRIORITY_VOLTAGE + 5.0
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_coordinator(
    *,
    temp1: float | None = 40.0,
    temp2: float | None = 40.0,
    max_temp: float = NORMAL_MAX_TEMP,
    relay1_on: bool = False,
    relay2_on: bool = False,
    grid_export: float = AMPLE_SURPLUS,
    voltage: float = NORMAL_VOLTAGE,
    auto_1: bool = True,
    auto_2: bool = True,
    sched_target: float | None = None,
    sched_deadline: datetime | None = None,
) -> tuple[BoilerCoordinator, dict[str, Any]]:
    entry_id = "test_sched"
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
    if sched_target is not None:
        rt[RUNTIME_SCHEDULE_TARGET] = sched_target
    if sched_deadline is not None:
        rt[RUNTIME_SCHEDULE_DEADLINE] = sched_deadline

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
    from collections import deque
    coord._action_log = deque(maxlen=6)  # type: ignore[method-assign]

    return coord, rt


def _future(seconds: int = 3600) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def _past(seconds: int = 3600) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# SC1 — Schedule active: boiler turns ON from solar surplus at schedule target
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc1_schedule_active_boiler_starts_on_surplus():
    """When schedule is active and surplus is available, boiler starts even if
    temp is below the schedule target (but would be below normal max_temp anyway)."""
    coord, rt = _make_coordinator(
        temp1=40.0, temp2=40.0, max_temp=NORMAL_MAX_TEMP,
        grid_export=AMPLE_SURPLUS,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    await coord._apply_control_logic()

    # Boiler 1 should have been turned ON (temp 40 < sched_target 55, ample surplus)
    calls = [str(c) for c in coord._set_switch.call_args_list]
    assert any("relay1" in c and "True" in c for c in calls), (
        "Boiler 1 should turn ON when schedule is active and surplus available"
    )


# ---------------------------------------------------------------------------
# SC2 — Schedule active: priority mode (grid draw) is suppressed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc2_schedule_suppresses_priority_mode():
    """When schedule is active, temp < 50% of schedule target should NOT force
    the boiler ON (which would draw from the grid). Only solar surplus triggers start."""
    # temp1=5 is way below 50% of sched_target=55 (27.5°C) → would normally trigger priority
    # but LOW_SURPLUS means no solar → boiler must stay OFF
    coord, rt = _make_coordinator(
        temp1=5.0, temp2=5.0, max_temp=NORMAL_MAX_TEMP,
        grid_export=LOW_SURPLUS,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    await coord._apply_control_logic()

    coord._set_switch.assert_not_called()


# ---------------------------------------------------------------------------
# SC3 — Schedule expired: normal logic resumes (max_temp from runtime, not schedule)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc3_expired_schedule_does_not_override_max_temp():
    """Expired deadline → sched_active is False → max_temp stays at NORMAL_MAX_TEMP."""
    coord, rt = _make_coordinator(
        temp1=56.0, temp2=56.0, max_temp=NORMAL_MAX_TEMP,
        grid_export=AMPLE_SURPLUS,
        sched_target=SCHED_TARGET,    # 55°C — if active, boiler would stop (56 >= 55)
        sched_deadline=_past(),       # expired
    )
    await coord._apply_control_logic()

    # With expired schedule, max_temp is NORMAL_MAX_TEMP (80°C), temp=56 < 80 → should start
    calls = [str(c) for c in coord._set_switch.call_args_list]
    assert any("relay1" in c and "True" in c for c in calls), (
        "Boiler 1 should turn ON — expired schedule must not suppress heating"
    )


# ---------------------------------------------------------------------------
# SC4 — No schedule set: no override
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc4_no_schedule_no_override():
    """Without any schedule data, normal logic runs and respects NORMAL_MAX_TEMP."""
    coord, rt = _make_coordinator(
        temp1=40.0, temp2=40.0, max_temp=NORMAL_MAX_TEMP,
        grid_export=AMPLE_SURPLUS,
        # no sched_target, no sched_deadline
    )
    await coord._apply_control_logic()

    assert rt[CONF_MAX_TEMP_1] == NORMAL_MAX_TEMP
    assert rt[CONF_MAX_TEMP_2] == NORMAL_MAX_TEMP


# ---------------------------------------------------------------------------
# SC5 — Boiler 1 reaches schedule target → done_1 set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc5_boiler1_done_flag_set_when_target_reached():
    """Once temp1 >= sched_target, RUNTIME_SCHEDULE_DONE_1 must be set to True."""
    coord, rt = _make_coordinator(
        temp1=SCHED_TARGET + 1.0,   # already above target
        temp2=40.0,
        relay1_on=False,
        max_temp=NORMAL_MAX_TEMP,
        grid_export=AMPLE_SURPLUS,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    await coord._apply_control_logic()

    assert rt.get(RUNTIME_SCHEDULE_DONE_1) is True, "done_1 must be set when B1 reaches target"


# ---------------------------------------------------------------------------
# SC6 — Boiler 2 reaches target independently from Boiler 1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc6_boiler2_done_flag_independent():
    """done_2 is set when temp2 >= sched_target, regardless of B1 state."""
    coord, rt = _make_coordinator(
        temp1=40.0,
        temp2=SCHED_TARGET + 2.0,
        max_temp=NORMAL_MAX_TEMP,
        grid_export=AMPLE_SURPLUS,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    await coord._apply_control_logic()

    assert rt.get(RUNTIME_SCHEDULE_DONE_2) is True
    assert rt.get(RUNTIME_SCHEDULE_DONE_1) is not True, "done_1 must remain unset"


# ---------------------------------------------------------------------------
# SC7 — Both done → done_1 and done_2 both True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc7_both_done_when_both_reach_target():
    """When both boilers exceed sched_target in the same cycle, both flags are set."""
    coord, rt = _make_coordinator(
        temp1=SCHED_TARGET + 1.0,
        temp2=SCHED_TARGET + 1.0,
        max_temp=NORMAL_MAX_TEMP,
        grid_export=AMPLE_SURPLUS,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    await coord._apply_control_logic()

    assert rt.get(RUNTIME_SCHEDULE_DONE_1) is True
    assert rt.get(RUNTIME_SCHEDULE_DONE_2) is True


# ---------------------------------------------------------------------------
# SC8 — Auto OFF: schedule is ignored for that boiler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc8_schedule_ignored_when_auto_off():
    """If auto_1 is OFF, the schedule must not affect Boiler 1."""
    coord, rt = _make_coordinator(
        temp1=40.0, temp2=40.0,
        max_temp=NORMAL_MAX_TEMP,
        grid_export=AMPLE_SURPLUS,
        auto_1=False,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    await coord._apply_control_logic()

    # Boiler 1 relay must NOT be turned ON (auto is OFF)
    calls = [str(c) for c in coord._set_switch.call_args_list]
    assert not any("relay1" in c and "True" in c for c in calls), (
        "Boiler 1 must not be started when auto is OFF"
    )
    # max_temp_1 must remain the user's value (schedule should not have changed it)
    assert rt[CONF_MAX_TEMP_1] == NORMAL_MAX_TEMP


# ---------------------------------------------------------------------------
# SC9 — Overvoltage still forces heating even during schedule (safety)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc9_overvoltage_overrides_schedule_solar_only_restriction():
    """Overvoltage priority must still force boilers ON even when schedule is active.
    The schedule suppresses the *low-temp comfort* priority, not the voltage safety one."""
    coord, rt = _make_coordinator(
        temp1=40.0, temp2=40.0,
        max_temp=NORMAL_MAX_TEMP,
        grid_export=LOW_SURPLUS,    # not enough surplus for normal solar start
        voltage=HIGH_VOLTAGE,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    # Trigger overvoltage immediately (no delay)
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = (
        datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)
    )
    await coord._apply_control_logic()

    # Overvoltage should have forced B1 ON despite low surplus
    calls = [str(c) for c in coord._set_switch.call_args_list]
    assert any("relay1" in c and "True" in c for c in calls), (
        "Overvoltage must force boiler ON even during solar-only schedule"
    )


# ---------------------------------------------------------------------------
# SC10 — Overvoltage boost does NOT write schedule target into CONF_MAX_TEMP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc10_overvoltage_boost_skipped_when_schedule_active():
    """When a schedule is active, the overvoltage target-boost is skipped to avoid
    corrupting CONF_MAX_TEMP with the schedule's lower target."""
    # Both boilers are at exactly sched_target → would trigger boost if allowed
    coord, rt = _make_coordinator(
        temp1=SCHED_TARGET,
        temp2=SCHED_TARGET,
        max_temp=NORMAL_MAX_TEMP,
        relay1_on=True,
        relay2_on=True,
        voltage=HIGH_VOLTAGE,
        grid_export=AMPLE_SURPLUS,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = (
        datetime.now() - timedelta(seconds=OVERVOLTAGE_TRIGGER_DELAY + 1)
    )
    await coord._apply_control_logic()

    # CONF_MAX_TEMP_1/2 must still reflect the user's original max, not sched_target ± boost
    assert rt[CONF_MAX_TEMP_1] == NORMAL_MAX_TEMP, (
        f"Expected NORMAL_MAX_TEMP={NORMAL_MAX_TEMP}, got {rt[CONF_MAX_TEMP_1]}"
    )
    assert rt[CONF_MAX_TEMP_2] == NORMAL_MAX_TEMP


# ---------------------------------------------------------------------------
# SC11 — _build_snapshot schedule_status reflects correct states
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sc11_snapshot_status_inactive_when_no_schedule():
    """schedule_status must be STATUS_SCHEDULE_INACTIVE when no deadline is set."""
    coord, rt = _make_coordinator(temp1=40.0, temp2=40.0)
    coord._action_log  # ensure attribute exists
    await coord._apply_control_logic()
    snap = coord._build_snapshot()
    assert snap["schedule_status"] == STATUS_SCHEDULE_INACTIVE


@pytest.mark.asyncio
async def test_sc11_snapshot_status_active_when_schedule_running():
    """schedule_status must be STATUS_SCHEDULE_SOLAR when deadline is in the future."""
    coord, rt = _make_coordinator(
        temp1=40.0, temp2=40.0,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    await coord._apply_control_logic()
    snap = coord._build_snapshot()
    assert snap["schedule_status"] == STATUS_SCHEDULE_SOLAR


@pytest.mark.asyncio
async def test_sc11_snapshot_status_expired_when_deadline_passed():
    """schedule_status must be STATUS_SCHEDULE_EXPIRED when deadline is in the past."""
    coord, rt = _make_coordinator(
        temp1=40.0, temp2=40.0,
        sched_target=SCHED_TARGET,
        sched_deadline=_past(),
    )
    await coord._apply_control_logic()
    snap = coord._build_snapshot()
    assert snap["schedule_status"] == STATUS_SCHEDULE_EXPIRED


@pytest.mark.asyncio
async def test_sc11_snapshot_status_done_when_both_boilers_finished():
    """schedule_status must be STATUS_SCHEDULE_DONE once both done flags are True."""
    coord, rt = _make_coordinator(
        temp1=SCHED_TARGET + 5.0,
        temp2=SCHED_TARGET + 5.0,
        sched_target=SCHED_TARGET,
        sched_deadline=_future(),
    )
    await coord._apply_control_logic()
    snap = coord._build_snapshot()
    assert snap["schedule_status"] == STATUS_SCHEDULE_DONE
    assert snap["schedule_done_1"] is True
    assert snap["schedule_done_2"] is True
