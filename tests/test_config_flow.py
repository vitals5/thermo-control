"""Exercise real HA config and options flow managers."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.thermo_control.const import (
    CONF_ADVANCED,
    CONF_CALIBRATION_MAX,
    CONF_CALIBRATION_MIN,
    CONF_CALIBRATION_STEP,
    CONF_CORRECTED,
    CONF_REGULATED_MODE,
    DEFAULTS,
    DOMAIN,
)


async def test_simple_setup(hass, room):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert flow["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            key: value
            for key, value in {**room, CONF_ADVANCED: False}.items()
            if key in ("name", "trvs", "temperature_sensor", CONF_ADVANCED)
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living room"
    assert result["data"]["calibration_interval"] == 600
    await hass.async_block_till_done()


async def test_advanced_setup(hass, room):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "name": "Office",
            "trvs": room["trvs"],
            "temperature_sensor": room["temperature_sensor"],
            CONF_ADVANCED: True,
        },
    )
    assert result["step_id"] == "advanced"
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            **DEFAULTS,
            "window_sensors": room["window_sensors"],
        },
    )
    assert result["step_id"] == "device"
    data = {
        CONF_CORRECTED: True,
        CONF_REGULATED_MODE: "heat",
        CONF_CALIBRATION_MIN: -5,
        CONF_CALIBRATION_MAX: 5,
        CONF_CALIBRATION_STEP: 0.1,
    }
    for name in ("a", "b"):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                **data,
                "calibration_entity": f"number.{name}_offset",
            },
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert len(result["data"]["devices"]) == 2
    await hass.async_block_till_done()


async def test_duplicate_assignment(hass, room, entry):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "name": "Second",
            "trvs": ["climate.a"],
            "temperature_sensor": "sensor.room",
            CONF_ADVANCED: False,
        },
    )
    assert result["errors"] == {"trvs": "trv_in_use"}


async def test_invalid_room_sensor(hass, room):
    hass.states.async_set("sensor.room", "nan", {"unit_of_measurement": "°C"})
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "name": "Living",
            "trvs": ["climate.a"],
            "temperature_sensor": "sensor.room",
            CONF_ADVANCED: False,
        },
    )
    assert result["errors"] == {"temperature_sensor": "invalid_sensor"}


async def test_options_edit_everything(hass, entry):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "name": "Renamed",
            "trvs": ["climate.b"],
            "temperature_sensor": "sensor.room",
            CONF_ADVANCED: True,
        },
    )
    assert result["step_id"] == "advanced"
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            **DEFAULTS,
            "window_sensors": [],
            "preset_eco": 16,
        },
    )
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            CONF_CORRECTED: False,
            CONF_REGULATED_MODE: "heat",
            CONF_CALIBRATION_MIN: -5,
            CONF_CALIBRATION_MAX: 5,
            CONF_CALIBRATION_STEP: 0.1,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["name"] == "Renamed"
    assert entry.options["window_sensors"] == []
    assert set(entry.options["devices"]) == {"climate.b"}
    assert "calibration_entity" not in entry.options["devices"]["climate.b"]


async def test_invalid_device_topic(hass, room):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "name": "Room",
            "trvs": ["climate.a"],
            "temperature_sensor": "sensor.room",
            CONF_ADVANCED: True,
        },
    )
    await hass.config_entries.flow.async_configure(flow["flow_id"], DEFAULTS)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            CONF_CORRECTED: True,
            CONF_REGULATED_MODE: "heat",
            CONF_CALIBRATION_MIN: -5,
            CONF_CALIBRATION_MAX: 5,
            CONF_CALIBRATION_STEP: 0.1,
            "calibration_topic": "zigbee2mqtt/+/set/local_temperature_calibration",
        },
    )
    assert result["errors"] == {"calibration_topic": "invalid_topic"}
