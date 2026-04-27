"""Config flow for Boiler Solar Controller.

Step 1 — boilers:   name + relay entity + temperature sensor (per boiler)
Step 2 — solar:     solar production sensor + grid import/export sensor
Step 3 — settings:  max temperature, min surplus, rated power
Options flow mirrors Step 3 to allow editing settings after setup.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    DOMAIN,
    CONF_RELAY_1,
    CONF_RELAY_2,
    CONF_TEMP_SENSOR_1,
    CONF_TEMP_SENSOR_2,
    CONF_SOLAR_SENSOR,
    CONF_GRID_SENSOR,
    CONF_GRID_POSITIVE_IS_EXPORT,
    CONF_BOILER1_NAME,
    CONF_BOILER2_NAME,
    CONF_MAX_TEMP_1,
    CONF_MAX_TEMP_2,
    CONF_MIN_SURPLUS,
    CONF_BOILER1_POWER,
    CONF_BOILER2_POWER,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_BOILER_POWER,
)


# ── Config Flow ───────────────────────────────────────────────────────────────

class BoilerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup wizard (3 steps)."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Step 1: Boiler names, relay entities, temperature sensors."""
        errors: dict = {}

        if user_input is not None:
            if user_input[CONF_RELAY_1] == user_input[CONF_RELAY_2]:
                errors["base"] = "same_relay"
            elif user_input[CONF_TEMP_SENSOR_1] == user_input[CONF_TEMP_SENSOR_2]:
                errors["base"] = "same_temp_sensor"
            else:
                self._data.update(user_input)
                return await self.async_step_solar()

        schema = vol.Schema(
            {
                vol.Required(CONF_BOILER1_NAME, default="Boiler 1"): TextSelector(TextSelectorConfig()),
                vol.Required(CONF_RELAY_1): EntitySelector(EntitySelectorConfig(domain="switch")),
                vol.Required(CONF_TEMP_SENSOR_1): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="temperature")),
                vol.Required(CONF_BOILER2_NAME, default="Boiler 2"): TextSelector(TextSelectorConfig()),
                vol.Required(CONF_RELAY_2): EntitySelector(EntitySelectorConfig(domain="switch")),
                vol.Required(CONF_TEMP_SENSOR_2): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="temperature")),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={},
        )

    async def async_step_solar(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Step 2: Solar production + grid import/export sensors."""
        errors: dict = {}

        if user_input is not None:
            if user_input[CONF_SOLAR_SENSOR] == user_input[CONF_GRID_SENSOR]:
                errors["base"] = "same_sensor"
            else:
                self._data[CONF_SOLAR_SENSOR] = user_input[CONF_SOLAR_SENSOR]
                self._data[CONF_GRID_SENSOR] = user_input[CONF_GRID_SENSOR]
                self._data[CONF_GRID_POSITIVE_IS_EXPORT] = (
                    user_input["grid_convention"] == "export"
                )
                return await self.async_step_settings()

        schema = vol.Schema(
            {
                vol.Required(CONF_SOLAR_SENSOR): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(CONF_GRID_SENSOR): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required("grid_convention", default="export"): SelectSelector(
                    SelectSelectorConfig(
                        options=["export", "import"],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="solar",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Step 3: Temperature limits, power thresholds, rated wattages."""
        if user_input is not None:
            title = (
                f"{self._data.get(CONF_BOILER1_NAME, 'Boiler 1')} + "
                f"{self._data.get(CONF_BOILER2_NAME, 'Boiler 2')}"
            )
            return self.async_create_entry(
                title=title,
                data=self._data,
                options={
                    CONF_MAX_TEMP_1: user_input[CONF_MAX_TEMP_1],
                    CONF_MAX_TEMP_2: user_input[CONF_MAX_TEMP_2],
                    CONF_MIN_SURPLUS: user_input[CONF_MIN_SURPLUS],
                    CONF_BOILER1_POWER: user_input[CONF_BOILER1_POWER],
                    CONF_BOILER2_POWER: user_input[CONF_BOILER2_POWER],
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_MAX_TEMP_1, default=DEFAULT_MAX_TEMP): NumberSelector(
                    NumberSelectorConfig(min=30, max=95, step=1, unit_of_measurement="°C", mode=NumberSelectorMode.SLIDER)
                ),
                vol.Required(CONF_MAX_TEMP_2, default=DEFAULT_MAX_TEMP): NumberSelector(
                    NumberSelectorConfig(min=30, max=95, step=1, unit_of_measurement="°C", mode=NumberSelectorMode.SLIDER)
                ),
                vol.Required(CONF_MIN_SURPLUS, default=DEFAULT_MIN_SURPLUS): NumberSelector(
                    NumberSelectorConfig(min=0, max=10000, step=50, unit_of_measurement="W", mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_BOILER1_POWER, default=DEFAULT_BOILER_POWER): NumberSelector(
                    NumberSelectorConfig(min=0, max=10000, step=50, unit_of_measurement="W", mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_BOILER2_POWER, default=DEFAULT_BOILER_POWER): NumberSelector(
                    NumberSelectorConfig(min=0, max=10000, step=50, unit_of_measurement="W", mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(
            step_id="settings",
            data_schema=schema,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> BoilerOptionsFlow:
        """Return options flow for editing settings after initial setup."""
        return BoilerOptionsFlow(config_entry)


# ── Options Flow ──────────────────────────────────────────────────────────────

class BoilerOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to edit power settings without re-running the full wizard."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Single page: edit thresholds and max temperatures."""
        opts = self._entry.options

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # grid convention: prefer options override, fall back to original data
        current_convention = opts.get(
            "grid_convention_override",
            "export" if self._entry.data.get(CONF_GRID_POSITIVE_IS_EXPORT, True) else "import",
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MAX_TEMP_1,
                    default=opts.get(CONF_MAX_TEMP_1, DEFAULT_MAX_TEMP),
                ): NumberSelector(NumberSelectorConfig(min=30, max=95, step=1, unit_of_measurement="°C", mode=NumberSelectorMode.SLIDER)),
                vol.Required(
                    CONF_MAX_TEMP_2,
                    default=opts.get(CONF_MAX_TEMP_2, DEFAULT_MAX_TEMP),
                ): NumberSelector(NumberSelectorConfig(min=30, max=95, step=1, unit_of_measurement="°C", mode=NumberSelectorMode.SLIDER)),
                vol.Required(
                    CONF_MIN_SURPLUS,
                    default=opts.get(CONF_MIN_SURPLUS, DEFAULT_MIN_SURPLUS),
                ): NumberSelector(NumberSelectorConfig(min=0, max=10000, step=50, unit_of_measurement="W", mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BOILER1_POWER,
                    default=opts.get(CONF_BOILER1_POWER, DEFAULT_BOILER_POWER),
                ): NumberSelector(NumberSelectorConfig(min=0, max=10000, step=50, unit_of_measurement="W", mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BOILER2_POWER,
                    default=opts.get(CONF_BOILER2_POWER, DEFAULT_BOILER_POWER),
                ): NumberSelector(NumberSelectorConfig(min=0, max=10000, step=50, unit_of_measurement="W", mode=NumberSelectorMode.BOX)),
                vol.Required(
                    "grid_convention_override",
                    default=current_convention,
                ): SelectSelector(SelectSelectorConfig(
                    options=["export", "import"],
                    mode=SelectSelectorMode.LIST,
                )),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
