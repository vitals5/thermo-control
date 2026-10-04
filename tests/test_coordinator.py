"""Control behavior against actual asynchronous HA services and timers."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.thermo_control.const import (
    CONF_CALIBRATION_ENTITY,
    CONF_CALIBRATION_TOPIC,
    CONF_CLOSE_DELAY,
    CONF_OPEN_DELAY,
)
from custom_components.thermo_control.coordinator import ThermoControlCoordinator


async def test_sync_multiple_and_position(coordinator, service_calls):
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=21)
    targets = [data for domain, service, data in service_calls if service == "set_temperature"]
    assert {data["entity_id"] for data in targets} == {"climate.a", "climate.b"}
    assert all(data["temperature"] == 21 for data in targets)
    assert coordinator.data["position"] == 40
    assert coordinator.data["available"]


async def test_calibration_and_interval(coordinator, service_calls, hass, freezer):
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    writes = [data for domain, service, data in service_calls if domain == "number"]
    assert len(writes) == 2
    assert all(data["value"] == -3 for data in writes)
    hass.states.async_set("sensor.room", 16, {"unit_of_measurement": "°C"})
    freezer.tick(timedelta(seconds=599))
    await coordinator._tick()
    assert len([call for call in service_calls if call[0] == "number"]) == 2
    freezer.tick(timedelta(seconds=1))
    await coordinator._tick()
    assert len([call for call in service_calls if call[0] == "number"]) == 4


async def test_threshold(coordinator, service_calls, hass):
    hass.states.async_set("sensor.room", 23.2, {"unit_of_measurement": "°C"})
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    assert not [call for call in service_calls if call[0] == "number"]


async def test_no_offset_oscillation(coordinator, service_calls, hass, freezer):
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    for name in ("a", "b"):
        state = hass.states.get(f"climate.{name}")
        hass.states.async_set(
            f"climate.{name}", "heat", {**state.attributes, "current_temperature": 20}
        )
        hass.states.async_set(f"number.{name}_offset", -3, {"min": -5, "max": 5, "step": 0.1})
    freezer.tick(timedelta(seconds=600))
    await coordinator._tick()
    assert len([call for call in service_calls if call[0] == "number"]) == 2


async def test_window_off_and_latest_intent_restore(coordinator, service_calls, hass):
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=21)
    hass.states.async_set("binary_sensor.window", "on")
    await coordinator._tick()
    assert coordinator.window_blocked
    assert coordinator.data["mode"] == HVACMode.OFF
    assert coordinator.mode == HVACMode.HEAT
    await coordinator.async_set_intent(temperature=22)
    hass.states.async_set("binary_sensor.window", "off")
    await coordinator._tick()
    assert not coordinator.window_blocked
    assert coordinator.target == 22
    assert coordinator.data["mode"] == HVACMode.HEAT


async def test_explicit_off_during_window(coordinator, hass):
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    hass.states.async_set("binary_sensor.window", "on")
    await coordinator._tick()
    await coordinator.async_set_intent(mode=HVACMode.OFF)
    hass.states.async_set("binary_sensor.window", "off")
    await coordinator._tick()
    assert coordinator.data["mode"] == HVACMode.OFF


async def test_window_delays_cancel_and_do_not_reset(coordinator, hass, freezer):
    coordinator.config[CONF_OPEN_DELAY] = 30
    coordinator.config[CONF_CLOSE_DELAY] = 60
    await coordinator.async_start()
    hass.states.async_set("binary_sensor.window", "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=20))
    await coordinator._tick()
    assert not coordinator.window_blocked
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert coordinator.window_blocked
    hass.states.async_set("binary_sensor.window", "off")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=30))
    hass.states.async_set("binary_sensor.window", "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=40))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert coordinator.window_blocked
    hass.states.async_set("binary_sensor.window", "off")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert not coordinator.window_blocked


async def test_all_windows_must_close(coordinator, hass):
    coordinator.config["window_sensors"].append("binary_sensor.door")
    hass.states.async_set("binary_sensor.door", "on")
    await coordinator._tick()
    assert coordinator.window_blocked
    hass.states.async_set("binary_sensor.door", "unavailable")
    await coordinator._tick()
    assert coordinator.window_blocked
    hass.states.async_set("binary_sensor.door", "off")
    await coordinator._tick()
    assert not coordinator.window_blocked


async def test_sensor_loss_stops_heat(coordinator, service_calls, hass):
    hass.states.async_set("sensor.room", "unavailable")
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    assert not coordinator.data["available"]
    assert all(
        data["hvac_mode"] == "off"
        for _, service, data in service_calls
        if service == "set_hvac_mode"
    )
    assert not [call for call in service_calls if call[0] == "number"]


async def test_one_unavailable_trv_does_not_block_room(coordinator, hass, service_calls):
    hass.states.async_set("climate.a", "unavailable")
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=22)
    assert coordinator.data["available"]
    assert [data for _, service, data in service_calls if service == "set_temperature"] == [
        {"entity_id": "climate.b", "temperature": 22}
    ]


async def test_failure_isolated_and_rate_limited(coordinator, hass, service_calls, freezer):
    async def fail(call):
        if call.data["entity_id"] == "number.a_offset":
            raise HomeAssistantError("offline")
        service_calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("number", "set_value", fail)
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    assert coordinator.data["devices"]["climate.a"]["error"] == "offline"
    assert any(data.get("entity_id") == "number.b_offset" for _, _, data in service_calls)
    first_attempt = coordinator._calibration["climate.a"]["attempted_at"]
    freezer.tick(timedelta(seconds=60))
    await coordinator._tick()
    assert coordinator._calibration["climate.a"]["attempted_at"] == first_attempt


async def test_mqtt_nonretained_and_known_baseline(coordinator, hass, service_calls):
    device = coordinator.devices["climate.a"]
    device[CONF_CALIBRATION_ENTITY] = None
    device[CONF_CALIBRATION_TOPIC] = "zigbee2mqtt/a/set/local_temperature_calibration"
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    assert not [call for call in service_calls if call[0] == "mqtt"]
    state = hass.states.get("climate.a")
    hass.states.async_set(
        "climate.a", "heat", {**state.attributes, "local_temperature_calibration": 0}
    )
    await coordinator._tick()
    publish = [data for domain, _, data in service_calls if domain == "mqtt"]
    assert publish[0]["payload"] == "-3.0"
    assert publish[0]["retain"] is False


async def test_frost_fallback_and_manual_preset(coordinator, hass, service_calls):
    state = hass.states.get("climate.a")
    hass.states.async_set(
        "climate.a", "heat", {**state.attributes, "hvac_modes": ["heat"], "preset_mode": "schedule"}
    )
    await coordinator._tick()
    assert (
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.a", "preset_mode": "manual"},
    ) in service_calls
    assert (
        "climate",
        "set_temperature",
        {"entity_id": "climate.a", "temperature": 5.0},
    ) in service_calls


async def test_presets_restore_manual_target(coordinator):
    await coordinator.async_set_intent(temperature=22)
    await coordinator.async_set_intent(preset="eco")
    assert coordinator.target == 17
    await coordinator.async_set_intent(preset="boost")
    assert coordinator.target == 25
    await coordinator.async_set_intent(preset="none")
    assert coordinator.target == 22


async def test_duplicate_suppression(coordinator, service_calls):
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=21)
    before = len(service_calls)
    await coordinator._tick()
    assert len(service_calls) == before


async def test_fahrenheit_source_and_target(coordinator, hass, service_calls):
    hass.states.async_set("sensor.room", 68, {"unit_of_measurement": "°F"})
    state = hass.states.get("climate.a")
    hass.states.async_set(
        "climate.a",
        "heat",
        {
            **state.attributes,
            "temperature_unit": "°F",
            "current_temperature": 73.4,
            "temperature": 68,
            "min_temp": 41,
            "max_temp": 86,
        },
    )
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=21)
    assert coordinator.data["temperature"] == 20
    data = next(
        data
        for _, service, data in service_calls
        if service == "set_temperature" and data["entity_id"] == "climate.a"
    )
    assert data["temperature"] == pytest.approx(69.8)
    assert coordinator._calibration["climate.a"]["value"] == -3


async def test_off_even_when_regulated_mode_is_invalid(coordinator, service_calls):
    coordinator.devices["climate.a"]["regulated_mode"] = "auto"
    await coordinator._tick()
    assert (
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.a", "hvac_mode": "off"},
    ) in service_calls


async def test_timeout_isolated(coordinator, hass, service_calls):
    async def fail(call):
        if call.data["entity_id"] == "climate.a":
            raise TimeoutError("timed out")
        service_calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("climate", "set_temperature", fail)
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=22)
    assert coordinator.data["devices"]["climate.a"]["error"] == "timed out"
    assert any(data.get("entity_id") == "climate.b" for _, _, data in service_calls)


async def test_persisted_rate_limit(hass, entry, service_calls):
    coordinator = ThermoControlCoordinator(hass, entry)
    stored = {
        "calibration": {
            entity_id: {"value": -3, "attempted_at": dt_util.utcnow().isoformat()}
            for entity_id in coordinator.trvs
        }
    }
    with (
        patch.object(coordinator._store, "async_load", AsyncMock(return_value=stored)),
        patch.object(coordinator._store, "async_save", AsyncMock()),
    ):
        await coordinator.async_initialize()
        await coordinator.async_set_intent(mode=HVACMode.HEAT)
        assert not [call for call in service_calls if call[0] == "number"]
        await coordinator.async_shutdown()


async def test_unload_cancels_pending_work(coordinator, hass, freezer):
    coordinator.config[CONF_OPEN_DELAY] = 30
    await coordinator.async_start()
    hass.states.async_set("binary_sensor.window", "on")
    await hass.async_block_till_done()
    await coordinator.async_shutdown()
    freezer.tick(timedelta(seconds=120))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert not coordinator.window_blocked
    assert not coordinator._unsubscribers


async def test_thermostat_measurements_without_external_sensor(coordinator, hass, service_calls):
    coordinator.config["temperature_sensor"] = None
    for entity_id, attributes in {
        "climate.a": {"current_temperature": 19},
        "climate.b": {
            "current_temperature": 77,
            "temperature_unit": "°F",
            "temperature": 68,
            "min_temp": 41,
            "max_temp": 86,
        },
    }.items():
        state = hass.states.get(entity_id)
        hass.states.async_set(entity_id, "heat", {**state.attributes, **attributes})
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=21)
    assert coordinator.data["available"]
    assert coordinator.data["temperature"] == pytest.approx(22)
    assert not [call for call in service_calls if call[0] in ("number", "mqtt")]
    targets = {
        data["entity_id"]: data["temperature"]
        for _, service, data in service_calls
        if service == "set_temperature"
    }
    assert targets == {"climate.a": 21, "climate.b": pytest.approx(69.8)}


@pytest.mark.parametrize("value", [None, "nan", "inf", True, -41, 81])
async def test_invalid_thermostat_readings_excluded_from_mean(
    coordinator, hass, service_calls, value
):
    coordinator.config["temperature_sensor"] = None
    state = hass.states.get("climate.b")
    hass.states.async_set("climate.b", "heat", {**state.attributes, "current_temperature": value})
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    assert coordinator.data["available"]
    assert coordinator.data["temperature"] == 23
    assert not [call for call in service_calls if call[0] in ("number", "mqtt")]


async def test_missing_measurements_stop_heat_and_recover(coordinator, hass, service_calls):
    coordinator.config["temperature_sensor"] = None
    for entity_id in coordinator.trvs:
        state = hass.states.get(entity_id)
        hass.states.async_set(entity_id, "heat", {**state.attributes, "current_temperature": None})
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    assert coordinator.data["temperature"] is None
    assert not coordinator.data["available"]
    assert coordinator.mode == HVACMode.HEAT
    assert {
        data["entity_id"]
        for _, service, data in service_calls
        if service == "set_hvac_mode" and data["hvac_mode"] == "off"
    } == set(coordinator.trvs)
    service_calls.clear()
    state = hass.states.get("climate.a")
    hass.states.async_set("climate.a", "off", {**state.attributes, "current_temperature": 21})
    hass.states.async_set("climate.b", "unavailable")
    await coordinator._tick()
    assert coordinator.data["available"]
    assert coordinator.data["temperature"] == 21
    assert (
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.a", "hvac_mode": "heat"},
    ) in service_calls


async def test_optional_sensor_listeners_and_window_pause(
    coordinator, hass, service_calls, freezer
):
    coordinator.config["temperature_sensor"] = None
    await coordinator.async_start()
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    state = hass.states.get("climate.a")
    hass.states.async_set("climate.a", "heat", {**state.attributes, "current_temperature": 25})
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert coordinator.data["temperature"] == 24
    hass.states.async_set("binary_sensor.window", "on")
    await hass.async_block_till_done()
    assert coordinator.window_blocked
    assert coordinator.data["mode"] == HVACMode.OFF
    assert not [call for call in service_calls if call[0] in ("number", "mqtt")]


async def test_configured_external_sensor_never_falls_back(coordinator, hass, service_calls):
    hass.states.async_set("sensor.room", "unavailable", {"unit_of_measurement": "°C"})
    await coordinator.async_set_intent(mode=HVACMode.HEAT)
    assert coordinator.data["temperature"] is None
    assert not coordinator.data["available"]
    assert not [call for call in service_calls if call[0] in ("number", "mqtt")]
