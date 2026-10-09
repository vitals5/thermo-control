"""Daily exercise, interruption and persisted recovery against real HA services."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.thermo_control.configuration import validate_settings
from custom_components.thermo_control.coordinator import ThermoControlCoordinator
from custom_components.thermo_control.manager import RoomConfig
from custom_components.thermo_control.schedule import DAYS


@pytest.fixture
async def exercise(manager, room, hass, freezer, service_calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-10-09T09:55:00+00:00")
    settings = deepcopy(manager.settings)
    settings["valve_maintenance"] = {"enabled": True, "time": "12:00", "duration": 60}
    await manager.async_save_settings(settings, manager.revision)

    async def acknowledge(call):
        data = dict(call.data)
        service_calls.append((call.domain, call.service, data))
        state = hass.states.get(data["entity_id"])
        if call.service == "set_temperature":
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
                state.state,
                {**state.attributes, "preset_mode": data["preset_mode"]},
            )

    for service in ("set_temperature", "set_hvac_mode", "set_preset_mode"):
        hass.services.async_register("climate", service, acknowledge)
    rid = await manager.async_save_room(room, manager.revision)
    coordinator = manager.entities[rid].coordinator
    yield coordinator


def targets(calls):
    return [data["temperature"] for _, service, data in calls if service == "set_temperature"]


async def due(coordinator, freezer):
    freezer.move_to("2026-10-09T10:00:00+00:00")
    await coordinator._tick()


async def next_phase(coordinator, freezer):
    freezer.tick(timedelta(seconds=61))
    await coordinator._tick()


async def test_daily_summer_exercise_keeps_display_intent_and_zero_demand(
    exercise, freezer, service_calls
):
    await exercise._tick()
    assert exercise.maintenance.phase is None
    service_calls.clear()
    await due(exercise, freezer)
    assert exercise.maintenance.phase == "close"
    assert all(
        exercise.hass.states.get(eid).attributes["temperature"] == 5 for eid in exercise.trvs
    )
    await next_phase(exercise, freezer)
    assert exercise.maintenance.phase == "open"
    assert targets(service_calls)[-2:] == [30, 30]
    assert exercise.mode == "off" and exercise.preset == "none" and exercise.target == 20
    assert exercise.heat_demand == 0
    assert not exercise.manager.system.snapshot()["heat_requested"]
    await next_phase(exercise, freezer)
    assert exercise.maintenance.phase is None
    assert exercise.maintenance.state["last_result"] == "completed"
    assert targets(service_calls)[-2:] == [5, 5]
    assert not [call for call in service_calls if call[1] == "set_hvac_mode"]
    service_calls.clear()
    freezer.tick(timedelta(hours=4))
    await exercise._tick()
    assert exercise.maintenance.phase is None
    assert not targets(service_calls)
    freezer.move_to("2026-10-10T10:00:00+00:00")
    await exercise._tick()
    assert exercise.maintenance.phase == "close"
    assert exercise.maintenance.state["last_date"] == "2026-10-10"


@pytest.mark.parametrize("heating_type", ["radiator", "floor"])
async def test_winter_restores_latest_preset_without_rewriting_intent(
    exercise, freezer, service_calls, heating_type
):
    exercise.config["heating_type"] = heating_type
    entity = exercise.manager.entities[exercise.entry.entry_id]
    await entity.async_set_temperature(temperature=22, hvac_mode="heat")
    await entity.async_set_preset_mode("comfort")
    await due(exercise, freezer)
    await next_phase(exercise, freezer)
    await next_phase(exercise, freezer)
    assert exercise.mode == "heat" and exercise.preset == "comfort"
    assert exercise.target == 21 and exercise.manual_target == 22
    assert targets(service_calls)[-2:] == [21, 21]


async def test_user_override_cancels_exercise_and_keeps_schedule(exercise, freezer, service_calls):
    manager = exercise.manager
    rid = exercise.entry.entry_id
    await manager.schedules.async_save(
        {
            "room_id": rid,
            "enabled": True,
            "weekdays": {day: [{"from": "00:00", "to": "24:00", "temp": 22}] for day in DAYS},
        },
        manager.schedules.revision,
    )
    await due(exercise, freezer)
    await next_phase(exercise, freezer)
    await manager.entities[rid].async_set_temperature(temperature=23)
    assert exercise.maintenance.phase is None
    assert exercise.maintenance.state["last_result"] == "cancelled"
    assert exercise.schedule_state["schedule_override"]
    assert exercise.preset == "schedule" and exercise.mode == "heat"
    assert targets(service_calls)[-2:] == [23, 23]


@pytest.mark.parametrize(
    "reason", ["window", "sensor", "device", "auto", "room_disabled", "global_disabled"]
)
async def test_ineligible_rooms_are_not_exercised(exercise, hass, freezer, service_calls, reason):
    if reason == "window":
        hass.states.async_set("binary_sensor.window", "on")
    elif reason == "sensor":
        hass.states.async_set("sensor.room", "unavailable")
    elif reason == "device":
        hass.states.async_set("climate.b", "unavailable")
    elif reason == "auto":
        state = hass.states.get("climate.a")
        hass.states.async_set(
            state.entity_id, "auto", {**state.attributes, "hvac_modes": ["heat", "off", "auto"]}
        )
    elif reason == "room_disabled":
        exercise.config["valve_maintenance"] = False
    else:
        exercise.manager.settings["valve_maintenance"]["enabled"] = False
    await due(exercise, freezer)
    assert exercise.maintenance.phase is None
    assert not exercise.maintenance.state.get("last_date")
    assert 30 not in targets(service_calls)


@pytest.mark.parametrize("reason", ["window", "sensor", "auto", "disabled"])
async def test_opening_is_interrupted_without_restart_same_day(
    exercise, hass, freezer, service_calls, reason
):
    await due(exercise, freezer)
    await next_phase(exercise, freezer)
    service_calls.clear()
    if reason == "window":
        hass.states.async_set("binary_sensor.window", "on")
    elif reason == "sensor":
        hass.states.async_set("sensor.room", "unavailable")
    elif reason == "auto":
        for eid in exercise.trvs:
            state = hass.states.get(eid)
            hass.states.async_set(
                eid, "auto", {**state.attributes, "hvac_modes": ["heat", "off", "auto"]}
            )
    else:
        exercise.manager.settings["valve_maintenance"]["enabled"] = False
    await exercise._tick()
    assert exercise.maintenance.phase is None
    assert exercise.maintenance.state["last_result"] == "interrupted"
    assert 30 not in targets(service_calls)
    if reason == "auto":
        assert not service_calls
    else:
        assert targets(service_calls) == [5, 5]


async def test_persistence_failure_withholds_maintenance_commands(exercise, freezer, service_calls):
    service_calls.clear()
    with patch.object(exercise._store, "async_save", AsyncMock(side_effect=OSError("disk full"))):
        with pytest.raises(OSError):
            await due(exercise, freezer)
    assert exercise.maintenance.phase is None
    assert not service_calls
    assert not exercise.maintenance.state


async def test_device_failure_restores_already_opened_valve(exercise, hass, freezer, service_calls):
    async def fail_second(call):
        if call.data["entity_id"] == "climate.b" and call.data["temperature"] == 30:
            raise HomeAssistantError("disconnected")
        service_calls.append((call.domain, call.service, dict(call.data)))
        state = hass.states.get(call.data["entity_id"])
        hass.states.async_set(
            state.entity_id,
            state.state,
            {**state.attributes, "temperature": call.data["temperature"]},
        )

    hass.services.async_register("climate", "set_temperature", fail_second)
    await due(exercise, freezer)
    await next_phase(exercise, freezer)
    assert exercise.maintenance.phase is None
    assert exercise.maintenance.state["last_result"] == "failed"
    assert hass.states.get("climate.a").attributes["temperature"] == 5
    assert hass.states.get("climate.b").attributes["temperature"] == 5


async def test_restored_cycle_returns_to_normal_without_reopening(exercise, freezer, service_calls):
    await due(exercise, freezer)
    await next_phase(exercise, freezer)
    replacement = ThermoControlCoordinator(
        exercise.hass,
        RoomConfig(exercise.entry.entry_id, exercise.config),
        manager=exercise.manager,
    )
    await replacement.async_initialize()
    assert replacement.maintenance.phase == "restore"
    service_calls.clear()
    await replacement._tick()
    assert replacement.maintenance.phase is None
    assert replacement.maintenance.state["last_result"] == "interrupted"
    assert targets(service_calls) == [5, 5]
    await replacement._tick()
    assert replacement.maintenance.phase is None
    await replacement.async_shutdown()


async def test_unload_restores_normal_setpoints(exercise, hass, freezer):
    await due(exercise, freezer)
    await next_phase(exercise, freezer)
    await exercise.async_shutdown()
    assert all(hass.states.get(eid).attributes["temperature"] == 5 for eid in exercise.trvs)
    assert exercise.maintenance.phase is None


async def test_rooms_exercise_sequentially_even_with_simultaneous_ticks(exercise, room, freezer):
    manager = exercise.manager
    rid = exercise.entry.entry_id
    await manager.async_save_room(
        {**room, "trvs": ["climate.a"], "devices": {"climate.a": room["devices"]["climate.a"]}},
        manager.revision,
        rid,
    )
    second = await manager.async_save_room(
        {
            **room,
            "name": "Second",
            "trvs": ["climate.b"],
            "devices": {"climate.b": room["devices"]["climate.b"]},
        },
        manager.revision,
    )
    first, other = manager.entities[rid].coordinator, manager.entities[second].coordinator
    freezer.move_to("2026-10-09T10:00:00+00:00")
    await asyncio.gather(first._tick(), other._tick())
    assert [first.maintenance.phase, other.maintenance.phase].count("close") == 1
    active, waiting = (first, other) if first.maintenance.phase else (other, first)
    await next_phase(active, freezer)
    await next_phase(active, freezer)
    await waiting._tick()
    assert active.maintenance.phase is None and waiting.maintenance.phase == "close"


async def test_late_tick_does_not_extend_extreme_setpoints(exercise, freezer, service_calls):
    await due(exercise, freezer)
    service_calls.clear()
    freezer.tick(timedelta(hours=1))
    await exercise._tick()
    assert exercise.maintenance.phase is None
    assert 30 not in targets(service_calls)


async def test_daily_timer_and_dst_repeated_hour(exercise, hass, freezer):
    exercise.manager.settings["valve_maintenance"]["time"] = "02:30"
    freezer.move_to("2026-10-25T00:29:00+00:00")
    await exercise.async_start()
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert exercise.maintenance.phase == "close"
    await next_phase(exercise, freezer)
    await next_phase(exercise, freezer)
    freezer.move_to("2026-10-25T01:30:00+00:00")
    await exercise._tick()
    assert exercise.maintenance.phase is None
    assert exercise.maintenance.state["last_date"] == "2026-10-25"


async def test_summer_exercise_without_external_sensor_or_pump_heat(
    exercise, freezer, service_calls
):
    exercise.config["temperature_sensor"] = None
    exercise.manager.settings["heat_pump"]["interlock"] = True
    await due(exercise, freezer)
    await next_phase(exercise, freezer)
    assert exercise.maintenance.phase == "open"
    assert targets(service_calls)[-2:] == [30, 30]
    assert not exercise.heat_permitted
    assert exercise.heat_demand == 0
    assert not exercise.manager.system.snapshot()["heat_requested"]


@pytest.mark.parametrize("maximum,opening", [(86, 86), (85.5, 85)])
async def test_hardware_temperature_unit_and_limits_are_respected(
    exercise, hass, freezer, service_calls, maximum, opening
):
    for eid in exercise.trvs:
        state = hass.states.get(eid)
        hass.states.async_set(
            eid,
            state.state,
            {
                **state.attributes,
                "temperature_unit": "°F",
                "temperature": 68,
                "min_temp": 41,
                "max_temp": maximum,
                "target_temp_step": 1,
            },
        )
    await due(exercise, freezer)
    assert targets(service_calls)[-2:] == [41, 41]
    await next_phase(exercise, freezer)
    assert targets(service_calls)[-2:] == [opening, opening]
    await next_phase(exercise, freezer)
    assert targets(service_calls)[-2:] == [41, 41]


async def test_spring_dst_gap_runs_once_when_local_time_passes_due(exercise, freezer):
    exercise.manager.settings["valve_maintenance"]["time"] = "02:30"
    freezer.move_to("2027-03-28T00:59:00+00:00")
    await exercise._tick()
    assert exercise.maintenance.phase is None
    freezer.move_to("2027-03-28T01:00:00+00:00")
    await exercise._tick()
    assert exercise.maintenance.phase == "close"
    assert exercise.maintenance.state["last_date"] == "2027-03-28"


@pytest.mark.parametrize(
    "changes",
    [
        {"time": "24:00"},
        {"time": "6:00"},
        {"duration": 59},
        {"duration": 601},
        {"duration": 60.5},
        {"duration": True},
        {"enabled": "yes"},
    ],
)
async def test_maintenance_configuration_validation(manager, changes):
    settings = deepcopy(manager.settings)
    settings["valve_maintenance"].update(changes)
    with pytest.raises(ServiceValidationError):
        validate_settings(manager.hass, settings)


async def test_old_settings_gain_disabled_maintenance_defaults(manager):
    settings = deepcopy(manager.settings)
    settings.pop("valve_maintenance")
    assert validate_settings(manager.hass, settings)["valve_maintenance"] == {
        "enabled": False,
        "time": "12:00",
        "duration": 180,
    }
