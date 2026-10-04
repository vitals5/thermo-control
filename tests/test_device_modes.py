"""Physical displays stay active; native schedules remain outside external control."""

from copy import deepcopy
from datetime import timedelta

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.thermo_control.climate import ThermoControlClimate
from custom_components.thermo_control.const import SYSTEM_DEFAULTS


def set_device(hass, entity_id, mode, **attributes):
    old = hass.states.get(entity_id)
    hass.states.async_set(
        entity_id,
        mode,
        {**old.attributes, "hvac_modes": ["off", "heat", "auto"], **attributes},
    )


@pytest.mark.parametrize("reason", ["pause", "window", "sensor"])
async def test_pause_retains_heat_display_and_virtual_target(
    coordinator, hass, service_calls, reason
):
    entity = ThermoControlClimate(coordinator)
    await entity.async_set_temperature(temperature=22, hvac_mode="heat")
    service_calls.clear()
    if reason == "pause":
        await entity.async_turn_off()
    else:
        hass.states.async_set(
            "binary_sensor.window" if reason == "window" else "sensor.room",
            "on" if reason == "window" else "unavailable",
        )
        await coordinator._tick()
    assert entity.target_temperature == 22
    assert coordinator.manual_target == 22
    assert {
        data["entity_id"]
        for _, service, data in service_calls
        if service == "set_temperature" and data["temperature"] == 5
    } == set(coordinator.trvs)
    assert not [call for call in service_calls if call[1] == "set_hvac_mode"]
    assert all(hass.states.get(entity_id).state == "heat" for entity_id in coordinator.trvs)


async def test_pwm_feedback_cycles_only_setpoint_and_keeps_display(
    manager, room, hass, service_calls, freezer
):
    async def acknowledge(call):
        data = dict(call.data)
        service_calls.append((call.domain, call.service, data))
        entity_id = data["entity_id"]
        state = hass.states.get(entity_id)
        if call.service == "set_temperature":
            target = data["temperature"]
            hass.states.async_set(
                entity_id,
                state.state,
                {
                    **state.attributes,
                    "temperature": target,
                    "hvac_action": "heating" if target > 20 else "idle",
                },
            )
        else:
            hass.states.async_set(entity_id, data["hvac_mode"], state.attributes)

    for service in ("set_temperature", "set_hvac_mode"):
        hass.services.async_register("climate", service, acknowledge)
    for entity_id in room["trvs"]:
        set_device(hass, entity_id, "heat", current_temperature=20)
    room_id = await manager.async_save_room(
        {**room, "heating_type": "floor", "temperature_sensor": None}, 0
    )
    entity = manager.entities[room_id]
    await entity.async_set_temperature(temperature=21, hvac_mode="heat")
    assert entity.hvac_action == "heating"
    freezer.tick(timedelta(minutes=23))
    await entity.coordinator._tick()
    assert entity.hvac_action == "idle"
    assert entity.target_temperature == 21
    assert all(hass.states.get(id).attributes["temperature"] == 5 for id in room["trvs"])
    freezer.tick(timedelta(minutes=22))
    await entity.coordinator._tick()
    assert entity.hvac_action == "heating"
    assert all(hass.states.get(id).state == "heat" for id in room["trvs"])
    assert not [call for call in service_calls if call[1] == "set_hvac_mode"]


async def test_native_auto_has_no_writes_even_with_window_sensor_loss_or_offset(
    manager, room, hass, service_calls, freezer
):
    for entity_id, target, action in [("climate.a", 22, "idle"), ("climate.b", 23, "heating")]:
        set_device(
            hass, entity_id, "auto", temperature=target, hvac_action=action, preset_mode="schedule"
        )
    room_id = await manager.async_save_room({**room, "heating_type": "floor"}, 0)
    entity = manager.entities[room_id]
    await entity.coordinator._tick()
    assert entity.hvac_mode == "auto"
    assert entity.target_temperature == 22.5
    assert entity.hvac_action == "heating"
    assert entity.coordinator.heat_demand == 100
    assert not entity.coordinator.controller.active
    assert entity.extra_state_attributes["native_auto"]
    assert entity.extra_state_attributes["auto_devices"] == room["trvs"]
    for temperature in (20, 24):
        freezer.tick(timedelta(hours=1))
        hass.states.async_set("sensor.room", temperature, {"unit_of_measurement": "°C"})
        await entity.coordinator._tick()
    await manager.async_set_master_offset(-2)
    hass.states.async_set("binary_sensor.window", "on")
    await entity.coordinator._tick()
    assert entity.hvac_mode == "auto"
    hass.states.async_set("sensor.room", "unavailable")
    await entity.coordinator._tick()
    assert entity.target_temperature == 22.5
    assert not service_calls
    for operation in (
        entity.async_set_temperature(temperature=21),
        entity.async_set_preset_mode("eco"),
        entity.async_set_temperature(temperature=21, hvac_mode="auto"),
    ):
        with pytest.raises(ServiceValidationError):
            await operation
    assert not service_calls


async def test_explicit_auto_and_manual_takeover_preserve_manual_target(
    coordinator, hass, service_calls
):
    entity = ThermoControlClimate(coordinator)
    for entity_id in coordinator.trvs:
        set_device(hass, entity_id, "heat")
    await entity.async_set_temperature(temperature=21, hvac_mode="heat")
    service_calls.clear()
    await entity.async_set_hvac_mode(HVACMode.AUTO)
    assert [data for _, service, data in service_calls if service == "set_hvac_mode"] == [
        {"entity_id": id, "hvac_mode": "auto"} for id in coordinator.trvs
    ]
    assert len(service_calls) == 2
    for entity_id in coordinator.trvs:
        set_device(hass, entity_id, "auto", temperature=19, preset_mode="schedule")
    await coordinator._tick()
    assert entity.target_temperature == 19
    assert coordinator.target == 21
    service_calls.clear()

    async def acknowledge(call):
        service_calls.append((call.domain, call.service, dict(call.data)))
        set_device(
            hass,
            call.data["entity_id"],
            call.data["hvac_mode"],
            temperature=19,
            preset_mode="schedule",
        )

    hass.services.async_register("climate", "set_hvac_mode", acknowledge)
    await entity.async_set_hvac_mode(HVACMode.HEAT)
    assert entity.hvac_mode == "heat"
    assert entity.target_temperature == 21
    assert {
        data["entity_id"]
        for _, service, data in service_calls
        if service == "set_temperature" and data["temperature"] == 21
    } == set(coordinator.trvs)
    assert all(
        data["hvac_mode"] == "heat"
        for _, service, data in service_calls
        if service == "set_hvac_mode"
    )


async def test_mixed_room_leaves_auto_device_untouched(coordinator, hass, service_calls):
    set_device(hass, "climate.a", "auto", preset_mode="schedule")
    await coordinator.async_set_intent(temperature=22)
    assert not coordinator.native_auto
    assert coordinator.auto_devices == ["climate.a"]
    assert all(
        data.get("entity_id") in ("climate.b", "number.b_offset") for _, _, data in service_calls
    )


async def test_device_auto_change_during_service_await_stops_remaining_writes(
    coordinator, hass, service_calls
):
    async def auto_during_write(call):
        service_calls.append((call.domain, call.service, dict(call.data)))
        set_device(hass, call.data["entity_id"], "auto", preset_mode="schedule")

    hass.services.async_register("climate", "set_temperature", auto_during_write)
    for entity_id in coordinator.trvs:
        set_device(hass, entity_id, "off")
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=22)
    assert all(service == "set_temperature" for _, service, _ in service_calls)
    assert coordinator.native_auto


async def test_physical_manual_mode_resumes_after_explicit_auto(
    coordinator, hass, service_calls, freezer
):
    for entity_id in coordinator.trvs:
        set_device(hass, entity_id, "auto")
    coordinator.mode = HVACMode.AUTO
    await coordinator.async_start()
    service_calls.clear()
    set_device(hass, "climate.a", "heat", temperature=19)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert coordinator.mode == HVACMode.HEAT
    assert coordinator.auto_devices == ["climate.b"]
    assert all(
        data.get("entity_id") in ("climate.a", "number.a_offset") for _, _, data in service_calls
    )


async def test_auto_only_device_never_accepts_external_mode(coordinator, hass, service_calls):
    for entity_id in coordinator.trvs:
        set_device(hass, entity_id, "auto", hvac_modes=["off", "auto"])
    entity = ThermoControlClimate(coordinator)
    assert entity.hvac_modes == [HVACMode.AUTO]
    with pytest.raises(ServiceValidationError):
        await entity.async_turn_on()
    await coordinator._tick()
    assert not service_calls


async def test_failed_explicit_mode_does_not_change_intent(coordinator, hass):
    for entity_id in coordinator.trvs:
        set_device(hass, entity_id, "heat")

    async def fail(call):
        raise HomeAssistantError("device unreachable")

    hass.services.async_register("climate", "set_hvac_mode", fail)
    previous = coordinator.mode
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_intent(mode=HVACMode.AUTO)
    assert coordinator.mode == previous


async def test_group_auto_blocks_partial_target_and_preset_changes(
    manager, room, hass, service_calls
):
    settings = deepcopy(SYSTEM_DEFAULTS)
    settings["groups"] = [{"id": "ground", "name": "Ground", "control": {}}]
    await manager.async_save_settings(settings, 0)
    for name in ("a", "b"):
        await manager.async_save_room(
            {
                **room,
                "name": name,
                "trvs": [f"climate.{name}"],
                "devices": {f"climate.{name}": room["devices"][f"climate.{name}"]},
                "group_id": "ground",
            },
            manager.revision,
        )
    group = manager.groups["ground"]
    set_device(hass, "climate.b", "auto", temperature=19)
    for entity in group.members:
        await entity.coordinator._tick()
    service_calls.clear()
    before = [member.coordinator.target for member in group.members]
    for operation in (
        group.async_set_temperature(temperature=22),
        group.async_set_preset_mode("eco"),
        group.async_set_hvac_mode("auto"),
    ):
        with pytest.raises(ServiceValidationError):
            await operation
    assert [member.coordinator.target for member in group.members] == before
    assert not service_calls
    assert group.extra_state_attributes["auto_rooms"]
