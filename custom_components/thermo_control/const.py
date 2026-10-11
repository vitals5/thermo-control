"""Constants for Thermo Control. Temperatures are stored in Celsius."""

DOMAIN = "thermo_control"
NAME = "Thermo Control"
CONF_TRVS = "trvs"
CONF_SENSOR = "temperature_sensor"
CONF_WINDOWS = "window_sensors"
CONF_DEVICES = "devices"
CONF_CALIBRATION_ENTITY = "calibration_entity"
CONF_CALIBRATION_TOPIC = "calibration_topic"
CONF_POSITION_ENTITY = "position_entity"
CONF_INTERNAL_SENSOR = "internal_sensor"
CONF_CORRECTED = "temperature_is_calibrated"
CONF_REGULATED_MODE = "regulated_mode"
CONF_CALIBRATION_MIN = "calibration_min"
CONF_CALIBRATION_MAX = "calibration_max"
CONF_CALIBRATION_STEP = "calibration_step"
CONF_INTERVAL = "calibration_interval"
CONF_THRESHOLD = "calibration_threshold"
CONF_OPEN_DELAY = "window_open_delay"
CONF_CLOSE_DELAY = "window_close_delay"
CONF_TOLERANCE = "tolerance"
CONF_FROST = "frost_temperature"
PRESETS = ("none", "eco", "comfort", "boost", "away")
PRESET_DEFAULTS = {"none": 20.0, "eco": 17.0, "comfort": 21.0, "boost": 25.0, "away": 15.0}
CONTROL_DEFAULTS = {
    "trend_window": 45,
    "inertia": 1.0,
    "lookahead": 180,
    "cycle_minutes": 45,
    "minimum_on": 300,
    "minimum_off": 300,
    "proportional_band": 2.0,
    "integral_hours": 6.0,
    "tolerance": 0.2,
}
MAINTENANCE_DEFAULTS = {"enabled": False, "time": "12:00", "duration": 180}
HEAT_PUMP_CONTROL_DEFAULTS = {
    "enabled": False,
    "pv_entity": "input_boolean.wp_laden_evcc",
    "priority": "block",
    "pv_delay": 180,
    "minimum_hold": 600,
    "heating_mode": "automatic",
    "heating": {
        "enabled": True,
        "entity": "climate.luxtronik_0_00_heating",
        "correction_entity": None,
        "end_entity": "number.luxtronik_0_00_heating_curve_end_temperature",
        "shift_entity": "number.luxtronik_0_00_heating_curve_parallel_shift_temperature",
        "automatic_mode": "heat",
        "blocked_mode": "keep",
        "profiles": {
            "standard": {"end": 32, "shift": 21, "correction": 0},
            "boost": {"end": 50, "shift": 30, "correction": 5},
            "blocked": {"end": 20, "shift": 15, "correction": -5},
        },
    },
    "dhw": {
        "enabled": True,
        "entity": "water_heater.luxtronik_0_00_domestic_water",
        "operation_mode": "heat_pump",
        "profiles": {"standard": 42, "boost": 55, "blocked": 30},
    },
    "return_sensor": "sensor.luxtronik_0_00_flow_out_temperature",
    "flow_sensor": "sensor.luxtronik_0_00_flow_in_temperature",
    "mixed_sensor": "sensor.luxtronik_0_00_flow_in_circuit1_temperature",
    "mixed_end_entity": "number.luxtronik_0_00_heating_curve_circuit1_end_temperature",
    "mixed_shift_entity": "number.luxtronik_0_00_heating_curve_circuit1_parallel_shift_temperature",
    "schedules": {
        "heating": {"enabled": False, "weekdays": {}},
        "dhw": {"enabled": False, "weekdays": {}},
    },
}
SYSTEM_DEFAULTS = {
    "master_offset": 0.0,
    "control": CONTROL_DEFAULTS,
    "calibration_interval": 600,
    "groups": [],
    "valve_maintenance": MAINTENANCE_DEFAULTS,
    "heat_pump_control": HEAT_PUMP_CONTROL_DEFAULTS,
    "heat_pump": {
        "flow_sensor": None,
        "target_sensor": None,
        "mode_entity": None,
        "compressor_entity": None,
        "automatic_states": ["automatic", "automatik", "automatisch", "auto"],
        "interlock": False,
        "minimum_flow": 25.0,
        "flow_margin": 2.0,
    },
}
DEFAULTS = {
    "heating_type": "radiator",
    "floor": "",
    "group_id": None,
    "use_global_control": True,
    "use_global_calibration": False,
    "valve_maintenance": True,
    **CONTROL_DEFAULTS,
    CONF_SENSOR: None,
    CONF_WINDOWS: [],
    CONF_INTERVAL: 600,
    CONF_THRESHOLD: 0.5,
    CONF_OPEN_DELAY: 30,
    CONF_CLOSE_DELAY: 60,
    CONF_TOLERANCE: 0.3,
    CONF_FROST: 5.0,
    **{f"preset_{name}": value for name, value in PRESET_DEFAULTS.items()},
}
DEVICE_DEFAULTS = {
    CONF_CORRECTED: True,
    CONF_REGULATED_MODE: "heat",
    CONF_CALIBRATION_MIN: -9.0,
    CONF_CALIBRATION_MAX: 9.0,
    CONF_CALIBRATION_STEP: 0.5,
}
RETRY_SECONDS = 60
SERVICE_TIMEOUT = 10
