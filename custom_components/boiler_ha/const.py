"""Constants for the Boiler Solar Controller integration."""

DOMAIN = "boiler_ha"

# Config entry keys (entity selection)
CONF_RELAY_1 = "relay_1"
CONF_RELAY_2 = "relay_2"
CONF_TEMP_SENSOR_1 = "temp_sensor_1"
CONF_TEMP_SENSOR_2 = "temp_sensor_2"
CONF_SOLAR_SENSOR = "solar_sensor"
CONF_GRID_SENSOR = "grid_sensor"
CONF_VOLTAGE_SENSOR = "voltage_sensor"      # optional — for overvoltage priority
CONF_GRID_POSITIVE_IS_EXPORT = "grid_positive_is_export"
CONF_BOILER1_NAME = "boiler1_name"
CONF_BOILER2_NAME = "boiler2_name"
CONF_POWER_SENSOR_1 = "power_sensor_1"   # optional — real power sensor for boiler 1
CONF_POWER_SENSOR_2 = "power_sensor_2"   # optional — real power sensor for boiler 2

# Options keys (runtime-adjustable settings)
CONF_MAX_TEMP_1 = "max_temp_1"
CONF_MAX_TEMP_2 = "max_temp_2"
CONF_MIN_SURPLUS = "min_surplus"
CONF_BOILER1_POWER = "boiler1_power"
CONF_BOILER2_POWER = "boiler2_power"

# hass.data runtime keys
RUNTIME_AUTO_1 = "auto_1"
RUNTIME_AUTO_2 = "auto_2"
RUNTIME_LAST_MAX_TEMP_1 = "last_max_temp_1"
RUNTIME_LAST_MAX_TEMP_2 = "last_max_temp_2"
RUNTIME_USER_MAX_TEMP_1 = "user_max_temp_1"  # saves original target during voltage boost
RUNTIME_USER_MAX_TEMP_2 = "user_max_temp_2"
RUNTIME_HIGH_VOLTAGE = "high_voltage_active"  # persistent hysteresis state for overvoltage detection

# Default values
DEFAULT_MAX_TEMP = 90.0          # °C
DEFAULT_MIN_SURPLUS = 800.0      # W — minimum surplus before starting any boiler
DEFAULT_BOILER_POWER = 1500.0    # W — estimated rated power of one resistance
DEFAULT_PRIORITY_VOLTAGE = 250.0 # V — grid voltage above which priority heating is forced
VOLTAGE_PRIORITY_RELEASE = 245.0 # V — voltage must drop below this to exit priority mode (hysteresis)
TEMP_BALANCE_MAX_DIFF = 5.0      # °C — max allowed temperature difference between boilers in priority mode
TEMP_HYSTERESIS = 5.0            # °C — boiler won't restart until temp drops this far below target
VOLTAGE_OVERHEAT_BOOST = 5.0   # °C — effective target increase during overvoltage (capped at DEFAULT_MAX_TEMP)

# Platforms
PLATFORMS = ["switch", "number", "sensor"]

# Status strings (used by sensor entities)
STATUS_HEATING = "Încălzire"
STATUS_PRIORITY = "Prioritate încălzire"
STATUS_STANDBY = "Standby"
STATUS_TARGET_REACHED = "Temperatură atinsă"
STATUS_NO_SOLAR = "Fără producție solară"
STATUS_MANUAL = "Control manual"
STATUS_UNAVAILABLE = "Senzor indisponibil"
