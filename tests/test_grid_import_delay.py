"""Grid import timing, daily reset and dashboard entity regression tests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.boiler_ha import coordinator as coordinator_module
from custom_components.boiler_ha.const import (
    DEFAULT_GRID_IMPORT_DELAY,
    RUNTIME_GRID_IMPORT_DELAY,
    RUNTIME_GRID_IMPORT_DELAY_DATE,
    RUNTIME_GRID_IMPORT_SINCE,
    RUNTIME_SOLAR_WINDOW_START,
    RUNTIME_SOLAR_WINDOW_END,
    RUNTIME_HIGH_VOLTAGE,
    CONF_GRID_POSITIVE_IS_EXPORT,
    RUNTIME_SCHEDULE_TARGET,
    RUNTIME_SCHEDULE_DEADLINE,
)
from custom_components.boiler_ha.number import BoilerGridImportDelayNumber
from tests.test_control_logic import _make_coord, _turned_off, _turned_on


@pytest.fixture
def clock(monkeypatch):
    now = [datetime(2026, 10, 21, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now[0])
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: now[0])
    monkeypatch.setattr(coordinator_module.dt_util, "as_local", lambda value: value)
    return now


@pytest.mark.asyncio
@pytest.mark.parametrize("boiler", [1, 2])
async def test_import_waits_until_exact_deadline_even_with_virtual_surplus(clock, boiler):
    coord, rt = _make_coord(
        relay1_on=boiler == 1, relay2_on=boiler == 2,
        temp1=50 if boiler == 1 else 55, temp2=50 if boiler == 2 else 55,
        grid_export=-10,
    )
    await coord._apply_control_logic()
    assert rt[RUNTIME_GRID_IMPORT_DELAY] == 5
    assert not _turned_off(coord, f"switch.relay{boiler}")
    clock[0] += timedelta(seconds=4.999)
    await coord._apply_control_logic()
    assert not _turned_off(coord, f"switch.relay{boiler}")
    clock[0] += timedelta(milliseconds=1)
    await coord._apply_control_logic()
    assert _turned_off(coord, f"switch.relay{boiler}")


@pytest.mark.asyncio
async def test_export_cancels_timer_and_new_import_starts_again(clock):
    coord, rt = _make_coord(relay1_on=True, grid_export=-10)
    await coord._apply_control_logic()
    clock[0] += timedelta(seconds=4)
    read_sensor = coord._float_state
    coord._float_state = lambda eid: 100 if eid == "sensor.grid" else read_sensor(eid)
    await coord._apply_control_logic()
    assert RUNTIME_GRID_IMPORT_SINCE not in rt
    coord._float_state = read_sensor
    clock[0] += timedelta(seconds=2)
    await coord._apply_control_logic()
    assert rt[RUNTIME_GRID_IMPORT_SINCE] == clock[0]
    assert not _turned_off(coord, "switch.relay1")


@pytest.mark.asyncio
async def test_custom_delay_changes_live_without_restarting_import_timer(clock):
    coord, rt = _make_coord(relay1_on=True, grid_export=-10)
    await coord._apply_control_logic()
    rt[RUNTIME_GRID_IMPORT_DELAY] = 60
    clock[0] += timedelta(seconds=5)
    await coord._apply_control_logic()
    assert not _turned_off(coord, "switch.relay1")
    rt[RUNTIME_GRID_IMPORT_DELAY] = 0
    await coord._apply_control_logic()
    assert _turned_off(coord, "switch.relay1")


@pytest.mark.asyncio
async def test_no_solar_start_during_import(clock):
    coord, _ = _make_coord(relay1_on=True, grid_export=-10)
    await coord._apply_control_logic()
    assert not _turned_on(coord, "switch.relay2")


@pytest.mark.asyncio
async def test_positive_import_sensor_convention(clock):
    coord, _ = _make_coord(relay1_on=True, grid_export=10)
    coord.entry.data[CONF_GRID_POSITIVE_IS_EXPORT] = False
    await coord._apply_control_logic()
    assert not _turned_off(coord, "switch.relay1")
    clock[0] += timedelta(seconds=5)
    await coord._apply_control_logic()
    assert _turned_off(coord, "switch.relay1")


@pytest.mark.asyncio
async def test_solar_schedule_uses_delay_but_never_overrides_deadline(clock):
    coord, rt = _make_coord(relay1_on=True, grid_export=-10)
    rt[RUNTIME_SCHEDULE_TARGET] = 60
    rt[RUNTIME_SCHEDULE_DEADLINE] = clock[0] + timedelta(seconds=2)
    rt[RUNTIME_SOLAR_WINDOW_START] = 13
    rt[RUNTIME_SOLAR_WINDOW_END] = 15
    await coord._apply_control_logic()
    assert not _turned_off(coord, "switch.relay1")
    clock[0] += timedelta(seconds=2)
    await coord._apply_control_logic()
    assert _turned_off(coord, "switch.relay1")


@pytest.mark.asyncio
async def test_unavailable_grid_clears_import_timer(clock):
    coord, rt = _make_coord(relay1_on=True, grid_export=-10)
    await coord._apply_control_logic()
    read_sensor = coord._float_state
    coord._float_state = lambda eid: None if eid == "sensor.grid" else read_sensor(eid)
    await coord._apply_control_logic()
    assert RUNTIME_GRID_IMPORT_SINCE not in rt


@pytest.mark.asyncio
async def test_clouds_do_not_skip_delay(clock):
    coord, _ = _make_coord(relay1_on=True, grid_export=-1600, solar_power=0)
    await coord._apply_control_logic()
    assert not _turned_off(coord, "switch.relay1")
    clock[0] += timedelta(seconds=5)
    await coord._apply_control_logic()
    assert _turned_off(coord, "switch.relay1")


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["temperature", "vacation", "window"])
async def test_safety_and_time_restrictions_are_immediate(clock, reason):
    kwargs = {"relay1_on": True, "grid_export": -10}
    if reason == "temperature":
        kwargs["temp1"] = 65
    elif reason == "vacation":
        kwargs["vacation_start"] = clock[0] - timedelta(days=1)
        kwargs["vacation_end"] = clock[0] + timedelta(days=1)
    coord, rt = _make_coord(**kwargs)
    if reason == "window":
        rt[RUNTIME_SOLAR_WINDOW_START] = 13
        rt[RUNTIME_SOLAR_WINDOW_END] = 15
    await coord._apply_control_logic()
    assert _turned_off(coord, "switch.relay1")


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["manual", "temperature_priority", "overvoltage"])
async def test_existing_grid_heating_modes_are_not_stopped(clock, reason):
    coord, rt = _make_coord(
        relay1_on=True, grid_export=-1600,
        temp1=20 if reason == "temperature_priority" else 50,
        temp2=20 if reason == "temperature_priority" else 50,
        auto_1=reason != "manual",
        voltage=255 if reason == "overvoltage" else 230,
    )
    if reason == "overvoltage":
        rt[RUNTIME_HIGH_VOLTAGE] = True
    await coord._apply_control_logic()
    clock[0] += timedelta(seconds=10)
    await coord._apply_control_logic()
    assert not _turned_off(coord, "switch.relay1")


def test_midnight_reset_and_missed_midnight(clock):
    coord, rt = _make_coord()
    coord._reset_grid_import_delay()
    rt[RUNTIME_GRID_IMPORT_DELAY] = 60
    coord._reset_grid_import_delay()
    assert rt[RUNTIME_GRID_IMPORT_DELAY] == 60
    clock[0] = clock[0].replace(hour=0) + timedelta(days=1)
    coord.async_refresh = MagicMock(return_value="refresh")
    coord._midnight_reset(clock[0])
    assert rt[RUNTIME_GRID_IMPORT_DELAY] == DEFAULT_GRID_IMPORT_DELAY
    coord.hass.async_create_task.assert_called_once_with("refresh")
    rt[RUNTIME_GRID_IMPORT_DELAY] = 120
    clock[0] += timedelta(days=1)
    coord._reset_grid_import_delay()
    assert rt[RUNTIME_GRID_IMPORT_DELAY] == DEFAULT_GRID_IMPORT_DELAY


def test_deadline_schedules_refresh_and_unload_cancels_it(clock, monkeypatch):
    coord, _ = _make_coord()
    coord._debounce_unsub = None
    coord._unsub_listeners = []
    coord.async_refresh = MagicMock(return_value="refresh")
    schedule = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(coordinator_module, "async_call_later", schedule)
    assert coord._grid_import_waiting(True)
    assert schedule.call_args.args[1] == 5
    schedule.call_args.args[2](None)
    coord.hass.async_create_task.assert_called_once_with("refresh")
    coord._grid_import_waiting(True)
    cancel = schedule.return_value
    coord.async_cancel_subscriptions()
    cancel.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("days_ago, expected", [(0, 60), (1, 5)])
async def test_number_restores_only_same_local_day(clock, days_ago, expected):
    coord, rt = _make_coord()
    coord._reset_grid_import_delay()
    coord.async_refresh = AsyncMock()
    number = BoilerGridImportDelayNumber(coord, coord.entry, DEFAULT_GRID_IMPORT_DELAY)
    saved_date = (clock[0] - timedelta(days=days_ago)).date().isoformat()
    number.async_get_last_state = AsyncMock(
        return_value=SimpleNamespace(state="60", attributes={"override_date": saved_date})
    )
    await number.async_added_to_hass()
    assert number.native_value == expected
    await number.async_set_native_value(30)
    assert rt[RUNTIME_GRID_IMPORT_DELAY] == 30
    assert number.extra_state_attributes["override_date"] == clock[0].date().isoformat()
    assert rt[RUNTIME_GRID_IMPORT_DELAY_DATE] == clock[0].date().isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [-1, 3601, float("nan"), float("inf")])
async def test_number_rejects_invalid_delay(clock, value):
    coord, _ = _make_coord()
    number = BoilerGridImportDelayNumber(coord, coord.entry, DEFAULT_GRID_IMPORT_DELAY)
    with pytest.raises(ValueError):
        await number.async_set_native_value(value)
