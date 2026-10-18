"""Luxtronik profile control against HA's real state machine and service registry."""

from copy import deepcopy
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.thermo_control.const import HEAT_PUMP_CONTROL_DEFAULTS
from custom_components.thermo_control.heat_pump import (
    HeatPumpController,
    blocked,
    validate_pump_control,
    validate_pump_schedule,
)
from custom_components.thermo_control.schedule import DAYS
from custom_components.thermo_control.websocket import async_register_commands


def night():
    return {"enabled": True, "weekdays": {day: [{"from": "22:00", "to": "10:00"}] for day in DAYS}}


@pytest.fixture
async def pump(manager, hass, freezer, service_calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-10-11T10:00:00+00:00")
    config = deepcopy(HEAT_PUMP_CONTROL_DEFAULTS)
    config.update(enabled=True, pv_delay=0, minimum_hold=60)
    config.update(
        pv_entity="input_boolean.pv_load",
        return_sensor="sensor.pump_return",
        flow_sensor="sensor.pump_flow",
        mixed_sensor="sensor.pump_mixed",
        mixed_end_entity="number.pump_mixed_end",
        mixed_shift_entity="number.pump_mixed_shift",
    )
    config["heating"].update(
        entity="climate.pump_heating",
        end_entity="number.pump_end",
        shift_entity="number.pump_shift",
    )
    config["dhw"].update(entity="water_heater.pump_water", operation_mode="heat_pump")
    hass.states.async_set(config["pv_entity"], "off")
    hass.states.async_set(
        config["heating"]["entity"],
        "heat",
        {
            "temperature": 0,
            "temperature_unit": "°C",
            "min_temp": -5,
            "max_temp": 5,
            "target_temp_step": 0.5,
            "hvac_modes": ["heat", "off"],
        },
    )
    for key, value in [("end_entity", 32), ("shift_entity", 21)]:
        hass.states.async_set(
            config["heating"][key],
            value,
            {"min": 5, "max": 60, "step": 0.5, "unit_of_measurement": "°C"},
        )
    for key, value in [("mixed_end_entity", 32), ("mixed_shift_entity", 21)]:
        hass.states.async_set(
            config[key], value, {"min": 5, "max": 60, "step": 0.5, "unit_of_measurement": "°C"}
        )
    hass.states.async_set(
        config["dhw"]["entity"],
        "heat_pump",
        {
            "temperature": 42,
            "current_temperature": 40,
            "min_temp": 10,
            "max_temp": 60,
            "operation_mode": "heat_pump",
            "operation_list": ["heat_pump", "off", "performance", "electric"],
        },
    )
    for key, value in [("return_sensor", 28), ("flow_sensor", 32), ("mixed_sensor", 30)]:
        hass.states.async_set(config[key], value, {"unit_of_measurement": "°C"})

    async def acknowledge(call):
        data = dict(call.data)
        service_calls.append((call.domain, call.service, data))
        state = hass.states.get(data["entity_id"])
        if call.service == "set_value":
            hass.states.async_set(state.entity_id, data["value"], state.attributes)
        elif call.service == "set_temperature":
            hass.states.async_set(
                state.entity_id,
                state.state,
                {**state.attributes, "temperature": data["temperature"]},
            )
        elif call.service == "set_hvac_mode":
            hass.states.async_set(state.entity_id, data["hvac_mode"], state.attributes)
        else:
            hass.states.async_set(
                state.entity_id,
                data["operation_mode"],
                {**state.attributes, "operation_mode": data["operation_mode"]},
            )

    for domain, services in {
        "number": ["set_value"],
        "climate": ["set_temperature", "set_hvac_mode"],
        "water_heater": ["set_temperature", "set_operation_mode"],
    }.items():
        for service in services:
            hass.services.async_register(domain, service, acknowledge)
    settings = deepcopy(manager.settings)
    settings["heat_pump_control"] = config
    await manager.async_save_settings(settings, manager.revision)
    await hass.async_block_till_done()
    service_calls.clear()
    return manager.heat_pump


def values(pump):
    config, hass = pump.config, pump.hass
    return tuple(
        float(hass.states.get(config["heating"][key]).state)
        for key in ("end_entity", "shift_entity")
    ) + (
        hass.states.get(config["heating"]["entity"]).attributes["temperature"],
        hass.states.get(config["dhw"]["entity"]).attributes["temperature"],
    )


async def boost(pump, hass, freezer):
    freezer.tick(61)
    hass.states.async_set(pump.config["pv_entity"], "on")
    await hass.async_block_till_done()


async def test_standard_boost_standard_and_no_mixed_writes(pump, hass, freezer, service_calls):
    assert values(pump) == (32, 21, 0, 42)
    assert not service_calls
    await boost(pump, hass, freezer)
    assert values(pump) == (50, 30, 5, 55)
    assert all("circuit1" not in call[2]["entity_id"] for call in service_calls)
    assert all(call[1] != "set_preset_mode" for call in service_calls)
    service_calls.clear()
    await pump.async_reconcile()
    assert not service_calls
    freezer.tick(61)
    hass.states.async_set(pump.config["pv_entity"], "off")
    await hass.async_block_till_done()
    assert values(pump) == (32, 21, 0, 42)
    assert pump.snapshot()["return"] == 28
    assert pump.snapshot()["mixed_flow"] == 30


async def test_existing_configuration_keeps_entities_and_gains_generic_name(pump, hass):
    config = deepcopy(pump.config)
    config.pop("name")
    validated = validate_pump_control(hass, config)
    assert validated == {**config, "name": "Wärmepumpe"}
    configured = validate_pump_control(hass, {**config, "name": "  Hausanlage  "})
    assert configured["name"] == "Hausanlage"
    pump.manager.settings["heat_pump_control"] = configured
    from custom_components.thermo_control.sensor import PumpControlSensor

    sensor = PumpControlSensor(pump.manager, "heating")
    assert sensor.name == "Thermo Control Hausanlage Heizung"
    assert pump.snapshot()["name"] == "Hausanlage"


async def test_generic_reported_operation_modes_and_no_pv_signal(pump, hass, service_calls):
    settings = deepcopy(pump.manager.settings)
    config = settings["heat_pump_control"]
    config["pv_entity"] = None
    config["heating"]["automatic_mode"] = "auto"
    config["dhw"]["operation_mode"] = "vendor_automatic"
    heating = hass.states.get(config["heating"]["entity"])
    hass.states.async_set(
        heating.entity_id,
        heating.state,
        {**heating.attributes, "hvac_modes": ["heat", "auto", "off"]},
    )
    dhw = hass.states.get(config["dhw"]["entity"])
    hass.states.async_set(
        dhw.entity_id,
        dhw.state,
        {**dhw.attributes, "operation_list": ["heat_pump", "vendor_automatic", "off"]},
    )
    await pump.manager.async_save_settings(settings, pump.manager.revision)
    await hass.async_block_till_done()
    assert hass.states.get(heating.entity_id).state == "auto"
    assert hass.states.get(dhw.entity_id).state == "vendor_automatic"
    assert pump.status["heating"]["pv"] is False
    assert not pump.status["dhw"]["errors"]
    service_calls.clear()
    pump.config["dhw"]["operation_mode"] = "unsupported"
    pump.config["dhw"]["profiles"]["standard"] = 43
    await pump.async_reconcile()
    assert pump.status["dhw"]["errors"]
    assert not service_calls
    pump.config["dhw"]["operation_mode"] = ""
    await pump.async_reconcile()
    await hass.async_block_till_done()
    assert any(call[1] == "set_temperature" for call in service_calls)
    assert [
        call[2]["operation_mode"] for call in service_calls if call[1] == "set_operation_mode"
    ] == ["heat_pump"]
    service_calls.clear()
    await pump.async_reconcile()
    assert not any(call[1] == "set_operation_mode" for call in service_calls)


async def test_separate_overnight_blocks_and_priority(pump, hass, freezer):
    pump.config["schedules"]["heating"] = night()
    freezer.move_to("2026-10-12T07:59:00+00:00")
    hass.states.async_set(pump.config["pv_entity"], "on")
    await hass.async_block_till_done()
    assert values(pump) == (20, 15, -5, 55)
    assert pump.status["heating"]["blocked"]
    freezer.tick(60)
    await pump.async_reconcile()
    await hass.async_block_till_done()
    assert values(pump) == (50, 30, 5, 55)
    freezer.move_to("2026-10-12T20:00:00+00:00")
    pump.config["priority"] = "pv"
    await pump.async_reconcile()
    assert pump.status["heating"]["profile"] == "boost"
    pump.config["priority"] = "block"
    pump.config["heating"]["blocked_mode"] = "off"
    await pump.async_reconcile()
    await hass.async_block_till_done()
    assert hass.states.get(pump.config["heating"]["entity"]).state == "off"
    assert values(pump) == (20, 15, -5, 55)
    pump.config["heating_mode"] = "off"
    await pump.async_reconcile()
    assert pump.status["heating"]["profile"] == "off"


async def test_pv_delay_hold_and_unavailable_fallback(pump, hass, freezer):
    pump.config["pv_delay"] = 180
    await boost(pump, hass, freezer)
    freezer.tick(179)
    await pump.async_reconcile()
    assert values(pump) == (32, 21, 0, 42)
    freezer.tick(1)
    await pump.async_reconcile()
    await hass.async_block_till_done()
    assert values(pump) == (50, 30, 5, 55)
    hass.states.async_set(pump.config["pv_entity"], "off")
    await hass.async_block_till_done()
    assert values(pump) == (50, 30, 5, 55)
    hass.states.async_set(pump.config["pv_entity"], "unavailable")
    await hass.async_block_till_done()
    assert values(pump) == (32, 21, 0, 42)
    assert pump.status["heating"]["pv"] is None


@pytest.mark.parametrize(
    "invalid", ["range", "step", "unavailable", "room_target", "unknown_target", "mode"]
)
async def test_preflight_withholds_entire_invalid_channel(
    pump, hass, freezer, service_calls, invalid
):
    entity_id = pump.config["heating"]["entity"]
    state = hass.states.get(entity_id)
    if invalid == "range":
        pump.config["heating"]["profiles"]["boost"]["end"] = 65
    elif invalid == "step":
        pump.config["heating"]["profiles"]["boost"]["shift"] = 30.1
    elif invalid == "unavailable":
        hass.states.async_set(pump.config["heating"]["shift_entity"], "unavailable")
    else:
        attrs = dict(state.attributes)
        if invalid == "room_target":
            attrs.update(min_temp=8, max_temp=28, temperature=21)
        elif invalid == "unknown_target":
            attrs["temperature"] = None
        else:
            attrs["hvac_modes"] = ["off"]
        hass.states.async_set(entity_id, state.state, attrs)
    await hass.async_block_till_done()
    service_calls.clear()
    await boost(pump, hass, freezer)
    assert pump.status["heating"]["errors"]
    assert not any(call[0] in ("number", "climate") for call in service_calls)
    assert hass.states.get(pump.config["dhw"]["entity"]).attributes["temperature"] == 55


async def test_optional_correction_number(pump, hass, freezer):
    entity_id = pump.config["heating"]["entity"]
    state = hass.states.get(entity_id)
    hass.states.async_set(
        entity_id,
        state.state,
        {**state.attributes, "temperature": 21, "min_temp": 8, "max_temp": 28},
    )
    hass.states.async_set(
        "number.pump_correction", 0, {"min": -5, "max": 5, "step": 0.5, "unit_of_measurement": "°C"}
    )
    pump.config["heating"]["correction_entity"] = "number.pump_correction"
    await boost(pump, hass, freezer)
    assert not pump.status["heating"]["errors"]
    assert hass.states.get("number.pump_correction").state == "5.0"
    assert hass.states.get(entity_id).attributes["temperature"] == 21


async def test_storage_failure_withholds_writes(pump, hass, freezer, service_calls):
    with patch.object(pump._store, "async_save", AsyncMock(side_effect=OSError("full"))):
        await boost(pump, hass, freezer)
    assert not service_calls
    assert values(pump) == (32, 21, 0, 42)
    assert pump.status["heating"]["errors"]
    assert pump.runtime["channels"]["heating"]["profile"] == "standard"


async def test_failed_command_rate_limit(pump, hass, freezer, service_calls):
    failed_calls = []

    async def failed(call):
        failed_calls.append(dict(call.data))
        raise HomeAssistantError("disconnected")

    hass.services.async_register("number", "set_value", failed)
    await boost(pump, hass, freezer)
    await pump.async_reconcile()
    assert (
        len(
            [
                call
                for call in failed_calls
                if call["entity_id"] == pump.config["heating"]["end_entity"]
            ]
        )
        == 1
    )
    freezer.tick(60)
    await pump.async_reconcile()
    assert (
        len(
            [
                call
                for call in failed_calls
                if call["entity_id"] == pump.config["heating"]["end_entity"]
            ]
        )
        == 2
    )


async def test_restart_and_disable_restore_original_targets(pump, hass, freezer):
    await boost(pump, hass, freezer)
    await pump.async_shutdown()
    restored = HeatPumpController(pump.manager)
    await restored.async_initialize()
    assert restored.runtime["channels"]["heating"]["profile"] == "boost"
    assert restored.runtime["baseline"]
    pump.config["enabled"] = False
    await restored.async_reconcile()
    await restored.async_reconcile()
    assert values(pump) == (32, 21, 0, 42)
    assert not restored.runtime["baseline"]


async def test_disable_one_channel_restores_only_its_targets(pump, hass, freezer):
    await boost(pump, hass, freezer)
    pump.config["heating"]["enabled"] = False
    await pump.async_reconcile()
    await hass.async_block_till_done()
    assert values(pump) == (32, 21, 0, 55)
    assert pump.status["heating"]["profile"] == "disabled"


async def test_restore_errors_remain_visible(pump, hass, freezer):
    await boost(pump, hass, freezer)
    pump.config["enabled"] = False
    hass.states.async_set(pump.config["heating"]["end_entity"], "unavailable")
    await hass.async_block_till_done()
    assert pump.status["heating"]["errors"]
    assert pump.status["heating"]["pending"]


async def test_restore_storage_failure_keeps_ownership(pump, hass, freezer):
    await boost(pump, hass, freezer)
    pump.close()
    pump.config["enabled"] = False
    await pump.async_reconcile()
    await hass.async_block_till_done()
    with patch.object(pump._store, "async_save", AsyncMock(side_effect=OSError("full"))):
        await pump.async_reconcile()
    assert pump.runtime["baseline"]
    assert pump.status["heating"]["errors"]
    await pump.async_reconcile()
    assert not pump.runtime["baseline"]


async def test_preflight_rejects_wrong_unit_and_unknown_mode(pump, hass, freezer, service_calls):
    eid = pump.config["heating"]["end_entity"]
    state = hass.states.get(eid)
    hass.states.async_set(eid, state.state, {**state.attributes, "unit_of_measurement": "W"})
    dhw = hass.states.get(pump.config["dhw"]["entity"])
    hass.states.async_set(dhw.entity_id, dhw.state, {**dhw.attributes, "operation_mode": None})
    await hass.async_block_till_done()
    await boost(pump, hass, freezer)
    assert not service_calls
    assert all(pump.status[channel]["errors"] for channel in ("heating", "dhw"))


async def test_manual_mixed_curve_preflight_and_revision(pump, hass, freezer, service_calls):
    await pump.async_set_mixed_curve(35, 22, pump.manager.revision)
    assert float(hass.states.get(pump.config["mixed_end_entity"]).state) == 35
    await boost(pump, hass, freezer)
    assert float(hass.states.get(pump.config["mixed_end_entity"]).state) == 35
    service_calls.clear()
    with pytest.raises(ServiceValidationError):
        await pump.async_set_mixed_curve(34, 65, pump.manager.revision)
    with pytest.raises(ServiceValidationError):
        await pump.async_set_mixed_curve(34, 22, -1)
    assert not service_calls


async def test_timer_without_rooms(pump, hass, freezer):
    pump.config["schedules"]["dhw"] = night()
    freezer.move_to("2026-10-11T19:59:00+00:00")
    await pump.async_reconcile()
    freezer.tick(60)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert values(pump)[-1] == 30
    assert not pump.manager.rooms


async def test_fahrenheit_device_conversion(pump, hass, freezer):
    eid = pump.config["dhw"]["entity"]
    state = hass.states.get(eid)
    hass.states.async_set(
        eid,
        state.state,
        {
            **state.attributes,
            "temperature_unit": "°F",
            "temperature": 107.6,
            "current_temperature": 104,
            "min_temp": 50,
            "max_temp": 140,
        },
    )
    await boost(pump, hass, freezer)
    assert hass.states.get(eid).attributes["temperature"] == 131
    assert pump.snapshot()["dhw_temperature"] == 40
    assert pump.snapshot()["dhw_target"] == 55
    pump.config["enabled"] = False
    await pump.async_reconcile()
    assert hass.states.get(eid).attributes["temperature"] == 107.6


@pytest.mark.parametrize(
    "local,expected",
    [
        ("2026-10-12T09:59:00+02:00", True),
        ("2026-10-12T10:00:00+02:00", False),
        ("2026-10-12T21:59:00+02:00", False),
        ("2026-10-12T22:00:00+02:00", True),
    ],
)
async def test_schedule_boundaries(hass, local, expected):
    await hass.config.async_set_time_zone("Europe/Berlin")
    assert blocked(validate_pump_schedule(night()), datetime.fromisoformat(local)) is expected


async def test_dst_and_week_wrap(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")
    plan = validate_pump_schedule(
        {
            "enabled": True,
            "weekdays": {
                "saturday": [{"from": "22:00", "to": "04:00"}],
                "sunday": [{"from": "22:00", "to": "10:00"}],
            },
        }
    )
    for fold in (0, 1):
        assert blocked(
            plan, datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"), fold=fold)
        )
    assert blocked(plan, datetime.fromisoformat("2026-10-26T09:30:00+01:00"))
    plan["enabled"] = False
    assert not blocked(plan, datetime.fromisoformat("2026-10-26T09:30:00+01:00"))


@pytest.mark.parametrize(
    "plan",
    [
        None,
        {"enabled": 1, "weekdays": {}},
        {"enabled": True, "weekdays": {"wrong": []}},
        {"enabled": True, "weekdays": {"monday": [{"from": "22:00", "to": "22:00"}]}},
        {
            "enabled": True,
            "weekdays": {
                "sunday": [{"from": "22:00", "to": "10:00"}],
                "monday": [{"from": "08:00", "to": "09:00"}],
            },
        },
        {"enabled": True, "weekdays": {"monday": [{}]}},
        {"enabled": True, "weekdays": {"monday": [{}] * 49}},
        {"enabled": True, "weekdays": {"monday": [{"from": "bad", "to": "10:00"}]}},
    ],
)
def test_invalid_schedule(plan):
    with pytest.raises(ServiceValidationError):
        validate_pump_schedule(plan)


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": 3},
        {"name": " "},
        {"name": "a" * 81},
        {"name": None},
        {"enabled": "yes"},
        {"priority": "wrong"},
        {"pv_delay": 1.5},
        {"minimum_hold": 0},
        {"heating": {"bad": 3}},
        {"heating": {"profiles": None}},
        {"dhw": {"operation_mode": None}},
        {"dhw": {"profiles": {"standard": 70, "boost": 55, "blocked": 30}}},
        {"heating": {"automatic_mode": None}},
        {"heating": {"blocked_mode": "cool"}},
        {"schedules": {}},
        {"pv_entity": "sensor.bad"},
        {"mixed_end_entity": "number.shared", "heating": {"end_entity": "number.shared"}},
        {"enabled": True},
    ],
)
def test_invalid_configuration(hass, change):
    with pytest.raises(ServiceValidationError):
        validate_pump_control(hass, change)


async def test_mixed_websocket_errors_and_admin(
    pump, hass, hass_ws_client, hass_read_only_access_token
):
    async_register_commands(hass)
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "thermo_control/set_mixed_curve",
            "end": 35,
            "shift": 22,
            "revision": pump.manager.revision,
        }
    )
    assert (await client.receive_json())["success"]
    await client.send_json(
        {
            "id": 2,
            "type": "thermo_control/set_mixed_curve",
            "end": 65,
            "shift": 22,
            "revision": pump.manager.revision,
        }
    )
    assert (await client.receive_json())["error"]["code"] == "invalid_configuration"
    with patch.object(
        pump, "async_set_mixed_curve", AsyncMock(side_effect=HomeAssistantError("offline"))
    ):
        await client.send_json(
            {
                "id": 3,
                "type": "thermo_control/set_mixed_curve",
                "end": 35,
                "shift": 22,
                "revision": pump.manager.revision,
            }
        )
        assert (await client.receive_json())["error"]["code"] == "device_error"
    reader = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await reader.send_json(
        {
            "id": 4,
            "type": "thermo_control/set_mixed_curve",
            "end": 35,
            "shift": 22,
            "revision": pump.manager.revision,
        }
    )
    assert (await reader.receive_json())["error"]["code"] == "unauthorized"
    await client.close()
    await reader.close()


async def test_manual_dhw_boost_sets_boost_profile_and_clears_when_target_reached(
    pump, hass, service_calls
):
    assert not pump.runtime.get("manual_dhw_boost")
    assert pump.snapshot()["manual_dhw_boost"] is False

    await pump.async_trigger_dhw_boost(True)
    assert pump.runtime.get("manual_dhw_boost") is True
    assert pump.snapshot()["manual_dhw_boost"] is True

    await pump.async_reconcile()
    assert pump.status["dhw"]["profile"] == "boost"
    assert pump.status["dhw"]["manual_boost"] is True

    dhw_entity = pump.config["dhw"]["entity"]
    # Boost target is 55 °C. Set current DHW temperature to 55 °C.
    hass.states.async_set(
        dhw_entity,
        "heat_pump",
        {
            "temperature": 55,
            "current_temperature": 55,
            "min_temp": 10,
            "max_temp": 60,
            "operation_mode": "heat_pump",
            "operation_list": ["heat_pump", "off", "performance", "electric"],
        },
    )

    await pump.async_reconcile()
    # Boost has reached target and auto-cleared!
    assert pump.runtime.get("manual_dhw_boost") is False
    assert pump.snapshot()["manual_dhw_boost"] is False
    assert pump.status["dhw"]["profile"] == "standard"
    assert pump.status["dhw"]["manual_boost"] is False


async def test_manual_dhw_boost_cancel(pump):
    await pump.async_trigger_dhw_boost(True)
    assert pump.runtime.get("manual_dhw_boost") is True

    await pump.async_trigger_dhw_boost(False)
    assert pump.runtime.get("manual_dhw_boost") is False
    assert pump.snapshot()["manual_dhw_boost"] is False


async def test_manual_dhw_boost_requires_enabled(pump):
    pump.config["enabled"] = False
    with pytest.raises(ServiceValidationError, match="Wärmepumpensteuerung ist nicht aktiviert"):
        await pump.async_trigger_dhw_boost(True)

    pump.config["enabled"] = True
    pump.config["dhw"]["enabled"] = False
    with pytest.raises(ServiceValidationError, match="Warmwasser-Kanal ist nicht aktiviert"):
        await pump.async_trigger_dhw_boost(True)


async def test_manual_dhw_boost_websocket_command(pump, hass, hass_ws_client):
    async_register_commands(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "thermo_control/trigger_dhw_boost", "enable": True})
    result = await client.receive_json()
    assert result["success"]
    assert pump.runtime.get("manual_dhw_boost") is True

    await client.send_json({"id": 2, "type": "thermo_control/trigger_dhw_boost", "enable": False})
    result = await client.receive_json()
    assert result["success"]
    assert pump.runtime.get("manual_dhw_boost") is False


async def test_validate_pump_control_demand_regulation(hass):
    config = deepcopy(HEAT_PUMP_CONTROL_DEFAULTS)
    heating = config["heating"]
    assert "demand_regulation" in heating

    # Invalid target_position
    bad = deepcopy(config)
    bad["heating"]["demand_regulation"]["target_position"] = 99.0
    with pytest.raises(ServiceValidationError, match="Ungültiger Wert für target_position"):
        validate_pump_control(hass, bad, check_entities=False)

    # Invalid deadband
    bad = deepcopy(config)
    bad["heating"]["demand_regulation"]["deadband"] = 50.0
    with pytest.raises(ServiceValidationError, match="Ungültiger Wert für deadband"):
        validate_pump_control(hass, bad, check_entities=False)

    # min_correction >= max_correction
    bad = deepcopy(config)
    bad["heating"]["demand_regulation"]["min_correction"] = 2.0
    bad["heating"]["demand_regulation"]["max_correction"] = 1.0
    with pytest.raises(ServiceValidationError, match="Ungültiger Wert für min_correction"):
        validate_pump_control(hass, bad, check_entities=False)

    bad = deepcopy(config)
    bad["heating"]["demand_regulation"]["min_correction"] = 0.0
    bad["heating"]["demand_regulation"]["max_correction"] = 0.0
    with pytest.raises(
        ServiceValidationError, match="Minimale Korrektur muss kleiner als maximale"
    ):
        validate_pump_control(hass, bad, check_entities=False)

    # Invalid dwell_minutes
    bad = deepcopy(config)
    bad["heating"]["demand_regulation"]["dwell_minutes"] = 0
    with pytest.raises(ServiceValidationError, match="Ungültige Verweilzeit"):
        validate_pump_control(hass, bad, check_entities=False)


async def test_demand_regulation_closed_valves_dials_back(pump, hass, freezer, service_calls):
    # Enable demand regulation with 15 min dwell
    settings = deepcopy(pump.manager.settings)
    settings["heat_pump_control"]["heating"]["demand_regulation"].update(
        enabled=True,
        target_position=55.0,
        deadband=15.0,
        min_correction=-3.0,
        max_correction=2.0,
        dwell_minutes=15,
        step_size=0.5,
    )
    await pump.manager.async_save_settings(settings, pump.manager.revision)
    await hass.async_block_till_done()
    service_calls.clear()

    # Create a mock room coordinator with closed valves
    room_mock = MagicMock()
    room_mock.entity_id = "climate.living"
    coord_mock = MagicMock()
    coord_mock.window_blocked = False
    coord_mock.config = {"name": "Wohnzimmer"}
    coord_mock.data = {
        "available": True,
        "mode": "heat",
        "position": 5.0,
        "temperature": 22.0,
        "target": 20.0,
        "temperature_rate": 0.0,
    }
    coord_mock._tick = AsyncMock()
    coord_mock.async_shutdown = AsyncMock()
    room_mock.coordinator = coord_mock
    pump.manager.entities = {"living": room_mock}

    # Initial reconcile filters the load
    await pump.async_reconcile()
    snap = pump.snapshot()
    assert snap["demand_regulation"]["enabled"] is True
    assert snap["demand_regulation"]["critical_room"] == "Wohnzimmer"

    # Fast forward past dwell time (15 min)
    freezer.tick(901)
    await pump.async_reconcile()

    # Dynamic correction stepped down by 0.5 °C
    assert pump.runtime["demand_regulation"]["correction"] == -0.5
    snap = pump.snapshot()
    assert snap["demand_regulation"]["correction"] == -0.5
    # Verify command was sent to correction entity (0 + (-0.5) = -0.5)
    last_climate_call = [
        c for c in service_calls if c[2]["entity_id"] == pump.config["heating"]["entity"]
    ]
    assert last_climate_call[-1][2]["temperature"] == -0.5

    # Fast forward another 15 min
    freezer.tick(901)
    await pump.async_reconcile()
    assert pump.runtime["demand_regulation"]["correction"] == -1.0


async def test_demand_regulation_starving_valves_boosts(pump, hass, freezer, service_calls):
    settings = deepcopy(pump.manager.settings)
    settings["heat_pump_control"]["heating"]["demand_regulation"].update(
        enabled=True,
        target_position=55.0,
        deadband=15.0,
        min_correction=-3.0,
        max_correction=2.0,
        dwell_minutes=15,
        step_size=0.5,
    )
    await pump.manager.async_save_settings(settings, pump.manager.revision)
    await hass.async_block_till_done()
    service_calls.clear()

    # Room is starving: valve at 100%, temperature below target
    room_mock = MagicMock()
    room_mock.entity_id = "climate.living"
    coord_mock = MagicMock()
    coord_mock.window_blocked = False
    coord_mock.config = {"name": "Wohnzimmer"}
    coord_mock.data = {
        "available": True,
        "mode": "heat",
        "position": 100.0,
        "temperature": 18.0,
        "target": 21.0,
        "temperature_rate": 0.0,
    }
    coord_mock._tick = AsyncMock()
    coord_mock.async_shutdown = AsyncMock()
    room_mock.coordinator = coord_mock
    pump.manager.entities = {"living": room_mock}

    await pump.async_reconcile()
    freezer.tick(901)
    await pump.async_reconcile()

    assert pump.runtime["demand_regulation"]["correction"] == 0.5
    last_call = [c for c in service_calls if c[2]["entity_id"] == pump.config["heating"]["entity"]][
        -1
    ]
    assert last_call[2]["temperature"] == 0.5


async def test_demand_regulation_anti_hunting_prevents_boost_when_satisfied_or_warming(
    pump, hass, freezer, service_calls
):
    settings = deepcopy(pump.manager.settings)
    settings["heat_pump_control"]["heating"]["demand_regulation"].update(
        enabled=True,
        target_position=55.0,
        deadband=15.0,
        dwell_minutes=15,
        step_size=0.5,
    )
    await pump.manager.async_save_settings(settings, pump.manager.revision)
    await hass.async_block_till_done()

    # Valve is open (90%), but room is already at setpoint (21.5 >= 21.0)
    room_mock = MagicMock()
    room_mock.entity_id = "climate.living"
    coord_mock = MagicMock()
    coord_mock.window_blocked = False
    coord_mock.config = {"name": "Wohnzimmer"}
    coord_mock.data = {
        "available": True,
        "mode": "heat",
        "position": 90.0,
        "temperature": 21.5,
        "target": 21.0,
        "temperature_rate": 0.0,
    }
    coord_mock._tick = AsyncMock()
    coord_mock.async_shutdown = AsyncMock()
    room_mock.coordinator = coord_mock
    pump.manager.entities = {"living": room_mock}

    await pump.async_reconcile()
    freezer.tick(901)
    await pump.async_reconcile()

    # Correction should NOT boost because room is satisfied!
    assert pump.runtime["demand_regulation"]["correction"] == 0.0

    # Valve is open (90%), temperature below setpoint (20.0 < 21.0), but warming rapidly (+0.5 °C/h)
    coord_mock.data["temperature"] = 20.0
    coord_mock.data["temperature_rate"] = 0.5

    freezer.tick(901)
    await pump.async_reconcile()

    # Correction still should NOT boost to prevent overshoot!
    assert pump.runtime["demand_regulation"]["correction"] == 0.0


async def test_demand_regulation_deadband_and_pv_override(pump, hass, freezer, service_calls):
    settings = deepcopy(pump.manager.settings)
    settings["heat_pump_control"]["heating"]["demand_regulation"].update(
        enabled=True,
        target_position=55.0,
        deadband=15.0,
        dwell_minutes=15,
        step_size=0.5,
    )
    await pump.manager.async_save_settings(settings, pump.manager.revision)
    await hass.async_block_till_done()

    # Valve at 55% (deadband is 40% to 70%)
    room_mock = MagicMock()
    room_mock.entity_id = "climate.living"
    coord_mock = MagicMock()
    coord_mock.window_blocked = False
    coord_mock.config = {"name": "Wohnzimmer"}
    coord_mock.data = {
        "available": True,
        "mode": "heat",
        "position": 55.0,
        "temperature": 20.0,
        "target": 20.0,
        "temperature_rate": 0.0,
    }
    coord_mock._tick = AsyncMock()
    coord_mock.async_shutdown = AsyncMock()
    room_mock.coordinator = coord_mock
    pump.manager.entities = {"living": room_mock}

    await pump.async_reconcile()
    freezer.tick(901)
    await pump.async_reconcile()

    assert pump.runtime["demand_regulation"]["correction"] == 0.0

    # When PV boost triggers, boost profile (+5) overrides
    service_calls.clear()
    await boost(pump, hass, freezer)
    last_call = [c for c in service_calls if c[2]["entity_id"] == pump.config["heating"]["entity"]][
        -1
    ]
    assert last_call[2]["temperature"] == 5.0
