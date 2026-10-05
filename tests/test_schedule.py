"""Weekly boundaries, DST, persistent overrides, group priority and schedule API."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.thermo_control.const import SYSTEM_DEFAULTS
from custom_components.thermo_control.manager import RoomManager
from custom_components.thermo_control.schedule import DAYS, evaluate, templates, validate_plan
from custom_components.thermo_control.websocket import async_register_commands


def plan(rid, **changes):
    return {
        "room_id": rid,
        "enabled": True,
        "weekdays": {
            day: [
                {"from": "00:00", "to": "06:00", "temp": 18},
                {"from": "06:00", "to": "22:00", "temp": 21.5},
                {"from": "22:00", "to": "24:00", "temp": 18},
            ]
            for day in DAYS
        },
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": "yes"},
        {"preheat": 1},
        {"room_id": "missing"},
        {"room_id": 1},
        {"group_id": "g"},
        {"weekdays": {"foo": []}},
        {"weekdays": {"monday": True}},
        {"weekdays": {"monday": [{"from": "24:00", "to": "06:00", "temp": 21}]}},
        {"weekdays": {"monday": [{"from": "06:00", "to": "06:00", "temp": 21}]}},
        {"weekdays": {"monday": [{"from": "06:00", "to": "07:00", "temp": 21.2}]}},
        {"weekdays": {"monday": [{"from": "06:00", "to": "07:00", "temp": True}]}},
        {"weekdays": {"monday": [{"from": "6:00", "to": "07:00", "temp": 21}]}},
        {"weekdays": {"monday": [{"from": "06:00", "to": "07:00", "temp": 21, "extra": 0}]}},
        {"override_hours": float("nan")},
        {"override_hours": 49},
        {"fallback_temp": 18.2},
        {"heating_rate": 0},
        {"max_preheat_minutes": 500},
        {"extra": "value"},
        {"weekdays": {"monday": [{"from": "00:00", "to": "01:00", "temp": 21}] * 49}},
    ],
)
async def test_plan_validation_before_storage_or_hardware(manager, room, changes, service_calls):
    rid = await manager.async_save_room(room, 0)
    service_calls.clear()
    with pytest.raises(ServiceValidationError):
        await manager.schedules.async_save(plan(rid, **changes), 0)
    assert not manager.schedules.plans
    assert not service_calls


@pytest.mark.parametrize("day,next_day", [("monday", "tuesday"), ("sunday", "monday")])
async def test_overnight_overlaps_are_rejected(manager, room, day, next_day):
    rid = await manager.async_save_room(room, 0)
    with pytest.raises(ServiceValidationError, match="überschneiden"):
        validate_plan(
            plan(
                rid,
                weekdays={
                    day: [{"from": "22:00", "to": "06:00", "temp": 18}],
                    next_day: [{"from": "00:00", "to": "02:00", "temp": 21}],
                },
            ),
            manager,
        )


async def test_overnight_week_wrap_and_fallback(manager, room, hass):
    await hass.config.async_set_time_zone("UTC")
    rid = await manager.async_save_room(room, 0)
    value = validate_plan(
        plan(
            rid,
            weekdays={
                "sunday": [{"from": "22:00", "to": "06:00", "temp": 19}],
                "monday": [{"from": "06:00", "to": "08:00", "temp": 22}],
            },
        ),
        manager,
    )
    assert evaluate(value, datetime(2026, 10, 5, 2, tzinfo=UTC))["target"] == 19
    assert evaluate(value, datetime(2026, 10, 5, 6, tzinfo=UTC))["target"] == 22
    assert evaluate(value, datetime(2026, 10, 5, 8, tzinfo=UTC))["target"] == 18
    assert (
        evaluate(value, datetime(2026, 10, 4, 23, tzinfo=UTC))["next_change"]
        == "2026-10-05T06:00:00+00:00"
    )
    for profile in templates().values():
        validate_plan(plan(rid, weekdays=profile["weekdays"]), manager)


@pytest.mark.parametrize(
    "stamp,target,next_change",
    [
        ("2026-03-29T00:45:00+00:00", 18, "2026-03-29T01:00:00+00:00"),
        ("2026-03-29T01:00:00+00:00", 22, "2026-03-29T04:00:00+00:00"),
        ("2026-10-25T00:45:00+00:00", 22, "2026-10-25T05:00:00+00:00"),
        ("2026-10-25T01:10:00+00:00", 22, "2026-10-25T05:00:00+00:00"),
    ],
)
async def test_dst_has_ordered_switches_and_does_not_repeat_fall_transition(
    manager, room, hass, stamp, target, next_change
):
    await hass.config.async_set_time_zone("Europe/Berlin")
    rid = await manager.async_save_room(room, 0)
    value = validate_plan(
        plan(
            rid,
            weekdays={
                "sunday": [
                    {"from": "00:00", "to": "02:30", "temp": 18},
                    {"from": "02:30", "to": "06:00", "temp": 22},
                ]
            },
        ),
        manager,
    )
    result = evaluate(value, datetime.fromisoformat(stamp))
    assert result["target"] == target
    assert result["next_change"] == next_change


@pytest.mark.freeze_time("2026-10-05T04:59:00+00:00")
async def test_schedule_switch_override_and_manual_toggle(
    manager, room, hass, freezer, service_calls
):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-05T05:00:00+00:00")
    rid = await manager.async_save_room(room, 0)
    entity = manager.entities[rid]
    await manager.schedules.async_save(plan(rid), 0)
    assert entity.hvac_mode == "heat"
    assert entity.preset_mode == "schedule"
    assert entity.target_temperature == 18
    await entity.async_set_temperature(temperature=20)
    assert entity.target_temperature == 20
    assert entity.extra_state_attributes["schedule_override"]
    assert entity.extra_state_attributes["schedule_until"] == "2026-10-05T06:00:00+00:00"
    freezer.move_to("2026-10-05T06:00:00+00:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert entity.target_temperature == 21.5
    assert not entity.extra_state_attributes["schedule_override"]
    assert not [
        data
        for _, service, data in service_calls
        if service == "set_hvac_mode" and data["hvac_mode"] in ("off", "auto")
    ]
    await entity.async_set_preset_mode("none")
    assert entity.target_temperature == 20  # Original manual target, not the override.
    freezer.tick(timedelta(hours=1))
    await entity.coordinator._tick()
    assert entity.preset_mode == "none"
    await entity.async_set_preset_mode("schedule")
    assert entity.preset_mode == "schedule"
    assert entity.target_temperature == 21.5


async def test_fixed_override_survives_reload_and_expires(manager, room, hass, freezer):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-05T05:30:00+00:00")
    rid = await manager.async_save_room(room, 0)
    entity = manager.entities[rid]
    await manager.schedules.async_save(plan(rid, override_hours=2), 0)
    await entity.async_set_temperature(temperature=23)
    restored = RoomManager(hass)
    await restored.async_initialize()
    assert restored.schedules.runtime[rid]["until"] == "2026-10-05T07:30:00+00:00"
    original = entity.coordinator.manager
    entity.coordinator.manager = restored
    freezer.move_to("2026-10-05T06:30:00+00:00")
    await entity.coordinator._tick()
    assert entity.target_temperature == 23
    freezer.move_to("2026-10-05T07:30:00+00:00")
    await entity.coordinator._tick()
    assert entity.target_temperature == 21.5
    entity.coordinator.manager = original
    await restored.async_shutdown()


async def test_preheat_uses_delta_rate_cap_and_never_overrides_manual_override(
    manager, room, hass, freezer
):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-05T03:59:00+00:00")
    hass.states.async_set("sensor.room", 20, {"unit_of_measurement": "°C"})
    rid = await manager.async_save_room({**room, "heating_type": "floor"}, 0)
    entity = manager.entities[rid]
    await manager.schedules.async_save(
        plan(rid, preheat=True, heating_rate=1, max_preheat_minutes=120), 0
    )
    assert entity.target_temperature == 18
    freezer.move_to("2026-10-05T04:30:00+00:00")
    await entity.coordinator._tick()
    assert entity.target_temperature == 21.5
    assert entity.extra_state_attributes["preheating"]
    assert entity.coordinator.controller.active
    freezer.move_to("2026-10-05T05:00:00+00:00")
    hass.states.async_set("sensor.room", 20.7, {"unit_of_measurement": "°C"})
    await entity.coordinator._tick()
    assert entity.target_temperature == 21.5  # Don't withdraw preheating as the room warms.
    assert entity.extra_state_attributes["preheating"]
    from custom_components.thermo_control.coordinator import ThermoControlCoordinator
    from custom_components.thermo_control.manager import RoomConfig

    restored = ThermoControlCoordinator(hass, RoomConfig(rid, manager.rooms[rid]), manager=manager)
    await restored.async_initialize()
    restored.mode = "heat"
    await restored._tick()
    assert restored.target == 21.5
    assert restored.schedule_state["preheating"]
    await restored.async_shutdown()
    await entity.async_set_temperature(temperature=19)
    assert not entity.extra_state_attributes["preheating"]
    assert entity.target_temperature == 19
    assert entity.extra_state_attributes["schedule_until"] == "2026-10-05T06:00:00+00:00"


async def test_group_inheritance_room_priority_and_group_schedule_preset(
    manager, room, hass, freezer
):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-05T10:00:00+00:00")
    settings = deepcopy(SYSTEM_DEFAULTS)
    settings["groups"] = [{"id": "ground", "name": "Ground", "control": {}}]
    await manager.async_save_settings(settings, 0)
    ids = []
    for name in ("a", "b"):
        ids.append(
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
        )
    group_plan = plan(ids[0])
    group_plan.pop("room_id")
    group_plan["group_id"] = "ground"
    await manager.schedules.async_save(group_plan, 0)
    assert all(entity.target_temperature == 21.5 for entity in manager.entities.values())
    await manager.schedules.async_save(
        plan(
            ids[0], weekdays={day: [{"from": "00:00", "to": "24:00", "temp": 23}] for day in DAYS}
        ),
        manager.schedules.revision,
    )
    assert manager.entities[ids[0]].target_temperature == 23
    assert manager.entities[ids[1]].target_temperature == 21.5
    await manager.groups["ground"].async_set_preset_mode("eco")
    assert all(entity.preset_mode == "eco" for entity in manager.entities.values())
    await manager.groups["ground"].async_set_preset_mode("schedule")
    assert [manager.entities[id].target_temperature for id in ids] == [23, 21.5]


async def test_window_frost_and_device_auto_remain_authoritative(
    manager, room, hass, freezer, service_calls
):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-05T10:00:00+00:00")
    rid = await manager.async_save_room(room, 0)
    entity = manager.entities[rid]
    await manager.schedules.async_save(plan(rid), 0)
    hass.states.async_set("binary_sensor.window", "on")
    await entity.coordinator._tick()
    assert entity.target_temperature == 21.5
    assert entity.hvac_mode == "off"
    assert any(
        service == "set_temperature" and data["temperature"] == 5
        for _, service, data in service_calls
    )
    for id in room["trvs"]:
        state = hass.states.get(id)
        hass.states.async_set(
            id,
            "auto",
            {**state.attributes, "hvac_modes": ["off", "heat", "auto"], "temperature": 19},
        )
    service_calls.clear()
    await entity.coordinator._tick()
    assert entity.hvac_mode == "auto"
    assert not entity.extra_state_attributes["schedule_active"]
    assert not service_calls


async def test_save_failure_stale_revision_and_copy_are_atomic(manager, room):
    rid = await manager.async_save_room(room, 0)
    schedules = manager.schedules
    with patch.object(schedules._store, "async_save", AsyncMock(side_effect=OSError("full"))):
        with pytest.raises(OSError):
            await schedules.async_save(plan(rid), 0)
    assert not schedules.plans
    await schedules.async_save(
        plan(
            rid, enabled=False, weekdays={"monday": [{"from": "09:00", "to": "17:00", "temp": 21}]}
        ),
        0,
    )
    with pytest.raises(ServiceValidationError):
        await schedules.async_save(plan(rid), 0)
    await schedules.async_copy(
        f"room:{rid}", [f"room:{rid}"], 1, source_day="monday", target_days=["tuesday", "wednesday"]
    )
    assert (
        schedules.plans[f"room:{rid}"]["weekdays"]["tuesday"]
        == schedules.plans[f"room:{rid}"]["weekdays"]["monday"]
    )
    before = deepcopy(schedules.plans)
    with pytest.raises(ServiceValidationError):
        await schedules.async_copy(
            f"room:{rid}",
            [f"room:{rid}", "room:missing"],
            schedules.revision,
            source_day="monday",
            target_days=["thursday"],
        )
    assert schedules.plans == before
    with pytest.raises(ServiceValidationError):
        await schedules.async_copy(
            f"room:{rid}", [f"room:{rid}"], schedules.revision, source_day="monday"
        )


@pytest.mark.parametrize("command", ["get_schedules", "save_schedule", "copy_schedule"])
async def test_schedule_websocket_requires_admin(
    hass, hass_ws_client, hass_read_only_access_token, manager, room, command
):
    rid = await manager.async_save_room(room, 0)
    async_register_commands(hass)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    message = {"id": 1, "type": f"thermo_control/{command}"}
    if command == "save_schedule":
        message.update(schedule=plan(rid), revision=0)
    if command == "copy_schedule":
        message.update(source=f"room:{rid}", targets=[f"room:{rid}"], revision=0)
    await client.send_json(message)
    assert (await client.receive_json())["error"]["code"] == "unauthorized"


async def test_real_schedule_websocket_read_save_copy_and_storage_error(
    hass, hass_ws_client, manager, room
):
    rid = await manager.async_save_room(room, 0)
    settings = deepcopy(SYSTEM_DEFAULTS)
    settings["groups"] = [{"id": "target", "name": "Target", "control": {}}]
    await manager.async_save_settings(settings, manager.revision)
    async_register_commands(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "thermo_control/get_schedules"})
    assert (await client.receive_json())["result"]["schedules"] == []
    await client.send_json(
        {"id": 2, "type": "thermo_control/save_schedule", "schedule": plan(rid), "revision": 0}
    )
    assert (await client.receive_json())["result"]["schedule_revision"] == 1
    await client.send_json(
        {
            "id": 3,
            "type": "thermo_control/copy_schedule",
            "source": f"room:{rid}",
            "targets": ["group:target"],
            "revision": 1,
        }
    )
    assert (await client.receive_json())["success"]
    assert not manager.schedules.plans["group:target"]["enabled"]
    await client.send_json(
        {"id": 4, "type": "thermo_control/save_schedule", "schedule": plan(rid), "revision": 0}
    )
    assert (await client.receive_json())["error"]["code"] == "invalid_configuration"
    with patch.object(
        manager.schedules._store, "async_save", AsyncMock(side_effect=OSError("full"))
    ):
        await client.send_json(
            {
                "id": 5,
                "type": "thermo_control/save_schedule",
                "schedule": plan(rid),
                "revision": manager.schedules.revision,
            }
        )
        assert (await client.receive_json())["error"]["code"] == "storage_error"
        await client.send_json(
            {
                "id": 6,
                "type": "thermo_control/copy_schedule",
                "source": f"room:{rid}",
                "targets": ["group:target"],
                "revision": manager.schedules.revision,
            }
        )
        assert (await client.receive_json())["error"]["code"] == "storage_error"


async def test_constant_plan_override_is_bounded_without_edit_revision_change(
    manager, room, hass, freezer
):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-05T10:00:00+00:00")
    rid = await manager.async_save_room(room, 0)
    entity = manager.entities[rid]
    await manager.schedules.async_save(plan(rid, weekdays=templates()["away"]["weekdays"]), 0)
    revision = manager.schedules.revision
    await entity.async_set_temperature(temperature=20.5)
    assert manager.schedules.revision == revision
    assert entity.extra_state_attributes["schedule_until"] == "2026-10-06T10:00:00+00:00"
    freezer.tick(timedelta(hours=24))
    await entity.coordinator._tick()
    assert entity.target_temperature == 18


async def test_plan_requires_heat_and_valid_hardware_bounds_before_persistence(manager, room, hass):
    rid = await manager.async_save_room(room, 0)
    for entity_id in room["trvs"]:
        state = hass.states.get(entity_id)
        hass.states.async_set(
            entity_id, "auto", {**state.attributes, "hvac_modes": ["off", "auto"]}
        )
    with pytest.raises(ServiceValidationError, match="heat"):
        await manager.schedules.async_save(plan(rid), 0)
    assert manager.schedules.plans == {}
    await manager.schedules.async_save(plan(rid, enabled=False), 0)
    with pytest.raises(ServiceValidationError, match="heat"):
        await manager.entities[rid].async_set_preset_mode("schedule")
    for entity_id in room["trvs"]:
        state = hass.states.get(entity_id)
        hass.states.async_set(
            entity_id, "heat", {**state.attributes, "hvac_modes": ["off", "heat"], "min_temp": 20}
        )
    with pytest.raises(ServiceValidationError, match="Temperaturgrenzen"):
        await manager.schedules.async_save(plan(rid), manager.schedules.revision)


async def test_copy_rejects_unknown_and_self_week_targets(manager, room):
    rid = await manager.async_save_room(room, 0)
    schedules = manager.schedules
    await schedules.async_save(plan(rid, enabled=False), 0)
    for source, targets in [
        ("room:missing", [f"room:{rid}"]),
        (f"room:{rid}", [f"room:{rid}"]),
        (f"room:{rid}", ["sensor:a"]),
    ]:
        with pytest.raises(ServiceValidationError):
            await schedules.async_copy(source, targets, schedules.revision)
    assert schedules.revision == 1


async def test_missing_schedule_and_group_member_are_rejected(manager, room):
    rid = await manager.async_save_room(room, 0)
    with pytest.raises(ServiceValidationError, match="Zuerst"):
        await manager.entities[rid].async_set_preset_mode("schedule")
    await manager.schedules.async_override(manager.entities[rid].coordinator, 21)
    assert not manager.schedules.runtime
    settings = deepcopy(SYSTEM_DEFAULTS)
    settings["groups"] = [{"id": "g", "name": "Group", "control": {}}]
    await manager.async_save_settings(settings, manager.revision)
    await manager.async_save_room({**manager.rooms[rid], "group_id": "g"}, manager.revision, rid)
    with pytest.raises(ServiceValidationError, match="Zuerst"):
        await manager.groups["g"].async_set_preset_mode("schedule")
