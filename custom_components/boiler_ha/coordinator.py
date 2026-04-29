"""DataUpdateCoordinator for Boiler Solar Controller.

Control logic:
  virtual_surplus = grid_export
                    + boiler1_rated_power  (if boiler 1 is currently ON)
                    + boiler2_rated_power  (if boiler 2 is currently ON)

  Boiler 1 should run  ← virtual_surplus >= min_surplus  AND  temp1 < max_temp1
  Boiler 2 should run  ← (virtual_surplus - boiler1_rated_power) >= min_surplus
                         AND  temp2 < max_temp2

The "virtual surplus" calculation tells us: if we turned the boilers off,
how much surplus power would be available? This reacts immediately when other
consumers draw power (grid_export drops → virtual_surplus drops → boilers stop).
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
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
    CONF_POWER_SENSOR_1,
    CONF_POWER_SENSOR_2,
    RUNTIME_AUTO_1,
    RUNTIME_AUTO_2,
    RUNTIME_LAST_MAX_TEMP_1,
    RUNTIME_LAST_MAX_TEMP_2,
    RUNTIME_USER_MAX_TEMP_1,
    RUNTIME_USER_MAX_TEMP_2,
    RUNTIME_VOLTAGE_BOOST_SINCE_1,
    RUNTIME_VOLTAGE_BOOST_SINCE_2,
    RUNTIME_HIGH_VOLTAGE,
    RUNTIME_HIGH_VOLTAGE_SINCE,
    DEFAULT_MAX_TEMP,
    VOLTAGE_BOOST_MIN_DURATION,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
    DEFAULT_PRIORITY_VOLTAGE,
    VOLTAGE_PRIORITY_RELEASE,
    TEMP_BALANCE_MAX_DIFF,
    TEMP_HYSTERESIS,
    VOLTAGE_OVERHEAT_BOOST,
    OVERVOLTAGE_TRIGGER_DELAY,
    STATUS_HEATING,
    STATUS_PRIORITY,
    STATUS_STANDBY,
    STATUS_TARGET_REACHED,
    STATUS_NO_SOLAR,
    STATUS_MANUAL,
    STATUS_UNAVAILABLE,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


class BoilerCoordinator(DataUpdateCoordinator):
    """Manages polling + reactive control of two boilers via existing HA entities."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.entry = entry
        self._unsub_listeners: list = []
        self._action_log: deque[str] = deque(maxlen=6)

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_config_entry_first_refresh(self) -> None:
        """Subscribe to relevant entity state-changes and do first update."""
        await super().async_config_entry_first_refresh()
        self._subscribe_state_changes()

    def _subscribe_state_changes(self) -> None:
        """React immediately when key sensors change (solar, grid, temperatures)."""
        cfg = self.entry.data
        watch = [
            cfg[CONF_SOLAR_SENSOR],
            cfg[CONF_GRID_SENSOR],
            cfg[CONF_TEMP_SENSOR_1],
            cfg[CONF_TEMP_SENSOR_2],
        ]
        voltage_sensor = self.entry.options.get(CONF_VOLTAGE_SENSOR) or self.entry.data.get(CONF_VOLTAGE_SENSOR)
        if voltage_sensor:
            watch.append(voltage_sensor)

        @callback
        def _state_changed(event) -> None:  # noqa: ANN001
            self.hass.async_create_task(self.async_refresh())

        unsub = async_track_state_change_event(self.hass, watch, _state_changed)
        self._unsub_listeners.append(unsub)

    @callback
    def async_cancel_subscriptions(self) -> None:
        """Cancel all state-change subscriptions."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Run control logic and return a state snapshot for entities."""
        try:
            await self._apply_control_logic()
        except Exception as exc:  # noqa: BLE001
            raise UpdateFailed(f"Eroare logică control: {exc}") from exc
        return self._build_snapshot()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _runtime(self) -> dict:
        """Return the mutable runtime store for this entry."""
        return self.hass.data[DOMAIN][self.entry.entry_id]

    def _log_action(self, message: str) -> None:
        """Log an action at INFO level and keep it in the rolling 3-entry log."""
        _LOGGER.info(message)
        log = getattr(self, "_action_log", None)
        if log is not None:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log.append(f"[{timestamp}] {message}")

    def _float_state(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == STATE_ON

    # ------------------------------------------------------------------
    # Control logic
    # ------------------------------------------------------------------

    async def _apply_control_logic(self) -> None:
        cfg = self.entry.data
        rt = self._runtime()

        relay_1 = cfg[CONF_RELAY_1]
        relay_2 = cfg[CONF_RELAY_2]
        temp_sensor_1 = cfg[CONF_TEMP_SENSOR_1]
        temp_sensor_2 = cfg[CONF_TEMP_SENSOR_2]
        grid_sensor = cfg[CONF_GRID_SENSOR]

        # options can override the grid convention set during initial setup
        opts = self.entry.options
        grid_convention_override = opts.get("grid_convention_override")
        if grid_convention_override is not None:
            grid_positive_is_export: bool = grid_convention_override == "export"
        else:
            grid_positive_is_export: bool = cfg.get(CONF_GRID_POSITIVE_IS_EXPORT, True)

        # voltage sensor: options take priority over data (allows setting from Configure)
        voltage_sensor = opts.get(CONF_VOLTAGE_SENSOR) or cfg.get(CONF_VOLTAGE_SENSOR)

        temp1 = self._float_state(temp_sensor_1)
        temp2 = self._float_state(temp_sensor_2)
        grid_raw = self._float_state(grid_sensor)
        boiler1_on = self._is_on(relay_1)
        boiler2_on = self._is_on(relay_2)

        max_temp_1: float = rt.get(CONF_MAX_TEMP_1, DEFAULT_MAX_TEMP)
        max_temp_2: float = rt.get(CONF_MAX_TEMP_2, DEFAULT_MAX_TEMP)
        min_surplus: float = rt.get(CONF_MIN_SURPLUS, DEFAULT_MIN_SURPLUS)
        boiler1_power: float = rt.get(CONF_BOILER1_POWER, DEFAULT_BOILER_POWER)
        boiler2_power: float = rt.get(CONF_BOILER2_POWER, DEFAULT_BOILER_POWER)
        auto_1: bool = rt.get(RUNTIME_AUTO_1, True)
        auto_2: bool = rt.get(RUNTIME_AUTO_2, True)

        # --- Safety guards ---
        if temp1 is None:
            _LOGGER.warning("Senzor temperatură Boiler 1 indisponibil — nu se controlează releul")
        if temp2 is None:
            _LOGGER.warning("Senzor temperatură Boiler 2 indisponibil — nu se controlează releul")

        # Normalize grid sensor to: positive = export (surplus), negative = import
        grid_export: float = 0.0
        if grid_raw is not None:
            grid_export = grid_raw if grid_positive_is_export else -grid_raw

        # Virtual surplus: how much solar would be available if boilers were OFF
        virtual_surplus = grid_export
        if boiler1_on:
            virtual_surplus += boiler1_power
        if boiler2_on:
            virtual_surplus += boiler2_power

        _LOGGER.debug(
            "Boiler control — temp1=%.1f°C temp2=%.1f°C grid_export=%.0fW "
            "virtual_surplus=%.0fW B1=%s B2=%s",
            temp1 or 0, temp2 or 0, grid_export, virtual_surplus,
            "ON" if boiler1_on else "OFF",
            "ON" if boiler2_on else "OFF",
        )

        # --- Voltage detection (with hysteresis) ---
        # Activate priority at > DEFAULT_PRIORITY_VOLTAGE, release only when < VOLTAGE_PRIORITY_RELEASE.
        # This prevents rapid on/off oscillation when boilers absorb power and lower the voltage.
        grid_voltage = self._float_state(voltage_sensor) if voltage_sensor else None
        prev_high_voltage: bool = rt.get(RUNTIME_HIGH_VOLTAGE, False)
        if grid_voltage is None:
            high_voltage = False
            rt.pop(RUNTIME_HIGH_VOLTAGE_SINCE, None)
        elif grid_voltage > DEFAULT_PRIORITY_VOLTAGE:
            if prev_high_voltage:
                high_voltage = True  # deja activ, menține
            else:
                # Nu e încă activ — pornește/verifică timer-ul de întârziere
                if RUNTIME_HIGH_VOLTAGE_SINCE not in rt:
                    rt[RUNTIME_HIGH_VOLTAGE_SINCE] = datetime.now()
                elapsed = (datetime.now() - rt[RUNTIME_HIGH_VOLTAGE_SINCE]).total_seconds()
                if elapsed >= OVERVOLTAGE_TRIGGER_DELAY:
                    high_voltage = True
                    rt.pop(RUNTIME_HIGH_VOLTAGE_SINCE, None)
                    self._log_action(f"Supratensiune activată după {elapsed:.0f}s ({grid_voltage:.1f}V)")
                else:
                    high_voltage = False  # așteptăm să expire delay-ul
        elif grid_voltage < VOLTAGE_PRIORITY_RELEASE:
            high_voltage = False
            rt.pop(RUNTIME_HIGH_VOLTAGE_SINCE, None)
        else:
            # Bandă histerezis: menține starea curentă; dacă nu e activ, resetează timer-ul
            high_voltage = prev_high_voltage
            if not high_voltage:
                rt.pop(RUNTIME_HIGH_VOLTAGE_SINCE, None)
        rt[RUNTIME_HIGH_VOLTAGE] = high_voltage

        # --- Overvoltage target boost ---
        # When overvoltage is active and a boiler has already reached its user-set target,
        # raise max_temp by VOLTAGE_OVERHEAT_BOOST (capped at DEFAULT_MAX_TEMP) so the boiler
        # restarts and keeps running to absorb the excess energy.
        # The original target is saved in RUNTIME_USER_MAX_TEMP and restored when voltage normalises.
        if high_voltage:
            if temp1 is not None and temp1 >= max_temp_1 and RUNTIME_USER_MAX_TEMP_1 not in rt:
                rt[RUNTIME_USER_MAX_TEMP_1] = max_temp_1
                rt[RUNTIME_VOLTAGE_BOOST_SINCE_1] = datetime.now()
                max_temp_1 = min(max_temp_1 + VOLTAGE_OVERHEAT_BOOST, DEFAULT_MAX_TEMP)
                rt[CONF_MAX_TEMP_1] = max_temp_1
                self._log_action(f"Supratensiune: target Boiler 1 ridicat la {max_temp_1:.1f}°C")
            if temp2 is not None and temp2 >= max_temp_2 and RUNTIME_USER_MAX_TEMP_2 not in rt:
                rt[RUNTIME_USER_MAX_TEMP_2] = max_temp_2
                rt[RUNTIME_VOLTAGE_BOOST_SINCE_2] = datetime.now()
                max_temp_2 = min(max_temp_2 + VOLTAGE_OVERHEAT_BOOST, DEFAULT_MAX_TEMP)
                rt[CONF_MAX_TEMP_2] = max_temp_2
                self._log_action(f"Supratensiune: target Boiler 2 ridicat la {max_temp_2:.1f}°C")
        else:
            # Restore original target only after the boost has been active long enough.
            # This prevents rapid oscillation: boilers start → voltage drops → target restored
            # immediately → boilers stop → voltage rises → repeat.
            if RUNTIME_USER_MAX_TEMP_1 in rt:
                since = rt.get(RUNTIME_VOLTAGE_BOOST_SINCE_1)
                elapsed = (datetime.now() - since).total_seconds() if since else VOLTAGE_BOOST_MIN_DURATION
                if elapsed >= VOLTAGE_BOOST_MIN_DURATION:
                    max_temp_1 = rt.pop(RUNTIME_USER_MAX_TEMP_1)
                    rt.pop(RUNTIME_VOLTAGE_BOOST_SINCE_1, None)
                    rt[CONF_MAX_TEMP_1] = max_temp_1
                    self._log_action(f"Supratensiune terminată: target Boiler 1 restaurat la {max_temp_1:.1f}°C")
            if RUNTIME_USER_MAX_TEMP_2 in rt:
                since = rt.get(RUNTIME_VOLTAGE_BOOST_SINCE_2)
                elapsed = (datetime.now() - since).total_seconds() if since else VOLTAGE_BOOST_MIN_DURATION
                if elapsed >= VOLTAGE_BOOST_MIN_DURATION:
                    max_temp_2 = rt.pop(RUNTIME_USER_MAX_TEMP_2)
                    rt.pop(RUNTIME_VOLTAGE_BOOST_SINCE_2, None)
                    rt[CONF_MAX_TEMP_2] = max_temp_2
                    self._log_action(f"Supratensiune terminată: target Boiler 2 restaurat la {max_temp_2:.1f}°C")

        # --- Temperature protection (always enforced, ignores auto flag) ---
        if temp1 is not None and temp1 >= max_temp_1 and boiler1_on:
            self._log_action(f"Boiler 1 a atins {max_temp_1:.1f}°C — oprire releu")
            await self._set_switch(relay_1, False)
            boiler1_on = False

        if temp2 is not None and temp2 >= max_temp_2 and boiler2_on:
            self._log_action(f"Boiler 2 a atins {max_temp_2:.1f}°C — oprire releu")
            await self._set_switch(relay_2, False)
            boiler2_on = False

        # --- Priority mode detection ---
        # Condition 1: boiler temp below 50% of target  → force heating regardless of surplus
        # Condition 2: grid voltage > DEFAULT_PRIORITY_VOLTAGE → force heating (overvoltage protection)
        b1_priority = (temp1 is not None and temp1 < max_temp_1 * 0.5) or high_voltage
        b2_priority = (temp2 is not None and temp2 < max_temp_2 * 0.5) or high_voltage

        # Balance: in priority mode, if one boiler is >TEMP_BALANCE_MAX_DIFF°C hotter, hold it back
        b1_held_back = False
        b2_held_back = False
        if temp1 is not None and temp2 is not None:
            diff = temp1 - temp2
            if diff > TEMP_BALANCE_MAX_DIFF:
                b1_held_back = True   # boiler1 too hot vs boiler2 — let boiler2 catch up
            elif diff < -TEMP_BALANCE_MAX_DIFF:
                b2_held_back = True   # boiler2 too hot vs boiler1 — let boiler1 catch up

        _LOGGER.debug(
            "Priority — B1_prio=%s held=%s  B2_prio=%s held=%s  voltage=%.1fV",
            b1_priority, b1_held_back, b2_priority, b2_held_back, grid_voltage or 0,
        )

        # --- Auto control: Boiler 1 (has priority over B2 in solar mode) ---
        # Hysteresis: if boiler is ON keep running until max_temp; if OFF don't start
        # until temp drops TEMP_HYSTERESIS degrees below the target.
        # Bypass hysteresis if target was just changed or high-voltage priority is active.
        last_max_temp_1: float = rt.get(RUNTIME_LAST_MAX_TEMP_1, max_temp_1)
        target_changed_1 = max_temp_1 != last_max_temp_1
        bypass_hyst_1 = target_changed_1 or high_voltage
        rt[RUNTIME_LAST_MAX_TEMP_1] = max_temp_1
        if auto_1 and temp1 is not None:
            temp_ok_1 = temp1 < max_temp_1 if (boiler1_on or bypass_hyst_1) else temp1 < (max_temp_1 - TEMP_HYSTERESIS)
            if b1_priority and not b1_held_back:
                should_run_1 = temp_ok_1   # ignore surplus
            else:
                should_run_1 = (virtual_surplus >= min_surplus) and temp_ok_1
            if should_run_1 and not boiler1_on:
                self._log_action(
                    f"Pornire Boiler 1 — surplus={virtual_surplus:.0f}W temp={temp1:.1f}°C priority={b1_priority}"
                )
                await self._set_switch(relay_1, True)
                boiler1_on = True
            elif not should_run_1 and boiler1_on:
                self._log_action(
                    f"Oprire Boiler 1 — surplus={virtual_surplus:.0f}W temp={temp1:.1f}°C priority={b1_priority}"
                )
                await self._set_switch(relay_1, False)
                boiler1_on = False

        # --- Auto control: Boiler 2 ---
        last_max_temp_2: float = rt.get(RUNTIME_LAST_MAX_TEMP_2, max_temp_2)
        target_changed_2 = max_temp_2 != last_max_temp_2
        bypass_hyst_2 = target_changed_2 or high_voltage
        rt[RUNTIME_LAST_MAX_TEMP_2] = max_temp_2
        if auto_2 and temp2 is not None:
            temp_ok_2 = temp2 < max_temp_2 if (boiler2_on or bypass_hyst_2) else temp2 < (max_temp_2 - TEMP_HYSTERESIS)
            if b2_priority and not b2_held_back:
                should_run_2 = temp_ok_2   # ignore surplus
            else:
                surplus_after_b1 = virtual_surplus - (boiler1_power if boiler1_on else 0)
                should_run_2 = (surplus_after_b1 >= min_surplus) and temp_ok_2
            if should_run_2 and not boiler2_on:
                self._log_action(
                    f"Pornire Boiler 2 — temp={temp2:.1f}°C priority={b2_priority}"
                )
                await self._set_switch(relay_2, True)
            elif not should_run_2 and boiler2_on:
                self._log_action(
                    f"Oprire Boiler 2 — temp={temp2:.1f}°C priority={b2_priority}"
                )
                await self._set_switch(relay_2, False)

    async def _set_switch(self, entity_id: str, turn_on: bool) -> None:
        service = "turn_on" if turn_on else "turn_off"
        await self.hass.services.async_call(
            "switch", service, {"entity_id": entity_id}, blocking=True
        )

    # ------------------------------------------------------------------
    # State snapshot (consumed by sensor/switch/number entities)
    # ------------------------------------------------------------------

    def _build_snapshot(self) -> dict:
        cfg = self.entry.data
        rt = self._runtime()

        temp1 = self._float_state(cfg[CONF_TEMP_SENSOR_1])
        temp2 = self._float_state(cfg[CONF_TEMP_SENSOR_2])
        solar = self._float_state(cfg[CONF_SOLAR_SENSOR])
        grid_raw = self._float_state(cfg[CONF_GRID_SENSOR])
        boiler1_on = self._is_on(cfg[CONF_RELAY_1])
        boiler2_on = self._is_on(cfg[CONF_RELAY_2])
        auto_1 = rt.get(RUNTIME_AUTO_1, True)
        auto_2 = rt.get(RUNTIME_AUTO_2, True)

        opts = self.entry.options
        grid_convention_override = opts.get("grid_convention_override")
        if grid_convention_override is not None:
            grid_positive_is_export = grid_convention_override == "export"
        else:
            grid_positive_is_export = cfg.get(CONF_GRID_POSITIVE_IS_EXPORT, True)
        grid_export: float | None = None
        if grid_raw is not None:
            grid_export = grid_raw if grid_positive_is_export else -grid_raw

        max_temp_1 = rt.get(CONF_MAX_TEMP_1, DEFAULT_MAX_TEMP)
        max_temp_2 = rt.get(CONF_MAX_TEMP_2, DEFAULT_MAX_TEMP)
        boiler1_power: float = rt.get(CONF_BOILER1_POWER, DEFAULT_BOILER_POWER)
        boiler2_power: float = rt.get(CONF_BOILER2_POWER, DEFAULT_BOILER_POWER)
        solar_producing = (solar or 0.0) > 50.0

        # Real power sensor readings (if configured), fallback to rated power when ON
        power_sensor_1 = cfg.get(CONF_POWER_SENSOR_1)
        power_sensor_2 = cfg.get(CONF_POWER_SENSOR_2)
        b1_consumption: float = (
            (self._float_state(power_sensor_1) or 0.0) if power_sensor_1
            else (boiler1_power if boiler1_on else 0.0)
        )
        b2_consumption: float = (
            (self._float_state(power_sensor_2) or 0.0) if power_sensor_2
            else (boiler2_power if boiler2_on else 0.0)
        )

        voltage_sensor = cfg.get(CONF_VOLTAGE_SENSOR)
        grid_voltage = self._float_state(voltage_sensor) if voltage_sensor else None
        high_voltage = rt.get(RUNTIME_HIGH_VOLTAGE, False)

        b1_priority = (temp1 is not None and temp1 < max_temp_1 * 0.5) or high_voltage
        b2_priority = (temp2 is not None and temp2 < max_temp_2 * 0.5) or high_voltage

        def _status(boiler_on: bool, temp: float | None, max_temp: float, auto: bool, priority: bool) -> str:
            if not auto:
                return STATUS_MANUAL
            if temp is None:
                return STATUS_UNAVAILABLE
            if temp >= max_temp:
                return STATUS_TARGET_REACHED
            if boiler_on:
                return STATUS_PRIORITY if priority else STATUS_HEATING
            if not solar_producing and not priority:
                return STATUS_NO_SOLAR
            return STATUS_STANDBY

        return {
            "boiler1_temp": temp1,
            "boiler2_temp": temp2,
            "boiler1_on": boiler1_on,
            "boiler2_on": boiler2_on,
            "boiler1_power_consumption": b1_consumption,
            "boiler2_power_consumption": b2_consumption,
            "solar_power": solar,
            "grid_export": grid_export,
            "grid_voltage": grid_voltage,
            "boiler1_status": _status(boiler1_on, temp1, max_temp_1, auto_1, b1_priority),
            "boiler2_status": _status(boiler2_on, temp2, max_temp_2, auto_2, b2_priority),
            "action_log": list(self._action_log),
        }
