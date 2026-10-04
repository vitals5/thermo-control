"""System settings, Luxtronik interlock and real device status aggregation."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.exceptions import ServiceValidationError

from custom_components.thermo_control.configuration import validate_settings
from custom_components.thermo_control.const import SYSTEM_DEFAULTS
from custom_components.thermo_control.manager import RoomManager
from custom_components.thermo_control.sensor import DemandSensor
from custom_components.thermo_control.services import async_register_services


@pytest.fixture
def pump_config(hass):
    hass.states.async_set("sensor.flow", "33", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.flow_target", "35", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.pump_mode", "Automatik")
    hass.states.async_set("binary_sensor.compressor", "on")
    result = deepcopy(SYSTEM_DEFAULTS)
    result["heat_pump"].update(
        flow_sensor="sensor.flow",
        target_sensor="sensor.flow_target",
        mode_entity="sensor.pump_mode",
        compressor_entity="binary_sensor.compressor",
        interlock=True,
    )
    return result


async def test_pump_telemetry_interlock_and_demand_signal(
    manager, room, hass, pump_config, service_calls
):
    await manager.async_save_settings(pump_config, 0)
    room_id = await manager.async_save_room({**room, "heating_type": "floor"}, manager.revision)
    coordinator = manager.entities[room_id].coordinator
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=22)
    assert coordinator.data["heat_demand"] == 100
    assert coordinator.data["heat_permitted"]
    assert manager.system.snapshot()["heat_requested"]
    assert manager.system.snapshot()["flow"] == 33
    assert manager.system.snapshot()["target"] == 35
    assert manager.system.snapshot()["compressor"]
    hass.states.async_set("sensor.pump_mode", "Standby")
    await coordinator._tick()
    assert coordinator.data["heat_demand"] == 100
    assert not coordinator.data["heat_permitted"]
    assert coordinator.interlock_reason == "not_automatic"
    assert manager.system.snapshot()["eligible_demand"] == 0
    assert manager.system.snapshot()["demand"] == 100
    assert not coordinator.controller.active
    assert all(domain in ("climate", "number") for domain, _, _ in service_calls)
    hass.states.async_set("sensor.pump_mode", "unavailable")
    await coordinator._tick()
    assert coordinator.interlock_reason == "mode_unavailable"
    hass.states.async_set("sensor.pump_mode", "automatic")
    hass.states.async_set("sensor.flow", "20", {"unit_of_measurement": "°C"})
    await coordinator._tick()
    assert coordinator.interlock_reason == "no_flow_heat"
    hass.states.async_set("sensor.flow", "unavailable", {"unit_of_measurement": "°C"})
    await coordinator._tick()
    assert not coordinator.heat_permitted
    await coordinator.async_set_intent(mode=HVACMode.OFF)
    assert manager.system.snapshot()["demand"] == 0


async def test_hvac_action_uses_real_hardware_not_room_error(coordinator, hass):
    await coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=25)
    assert coordinator.data["action"] is None
    for name, action in [("a", "idle"), ("b", "heating")]:
        state = hass.states.get(f"climate.{name}")
        hass.states.async_set(
            f"climate.{name}", "heat", {**state.attributes, "hvac_action": action}
        )
    await coordinator._tick()
    assert coordinator.data["action"] == HVACAction.HEATING
    await coordinator.async_set_intent(mode=HVACMode.OFF)
    assert coordinator.data["action"] == HVACAction.HEATING  # Device has not acknowledged stop.
    state = hass.states.get("climate.b")
    hass.states.async_set("climate.b", "off", {**state.attributes, "hvac_action": "off"})
    await coordinator._tick()
    assert coordinator.data["action"] == HVACAction.IDLE  # a is still idle, not heating.
    assert coordinator.data["devices"]["climate.b"]["hvac_action"] == "off"


async def test_floor_controller_sends_pulses_and_window_overrides_minimum(
    manager, room, hass, freezer, service_calls
):
    hass.states.async_set("sensor.room", 20, {"unit_of_measurement": "°C"})
    room_id = await manager.async_save_room({**room, "heating_type": "floor"}, 0)
    c = manager.entities[room_id].coordinator
    await c.async_set_intent(mode=HVACMode.HEAT, temperature=21)
    assert c.controller.active
    assert c.heat_demand == 50
    freezer.tick(timedelta(minutes=23))
    await c._tick()
    assert not c.controller.active
    assert any(
        call[1] == "set_temperature" and call[2]["temperature"] == 5 for call in service_calls
    )
    freezer.tick(timedelta(minutes=22))
    await c._tick()
    assert c.controller.active
    hass.states.async_set("binary_sensor.window", "on")
    await c._tick()
    assert c.window_blocked
    assert not c.controller.active
    assert c.heat_demand == 0
    assert "control" in c._storage_data()


async def test_master_offset_is_reversible_persistent_and_clamped(manager, room, hass):
    room_id = await manager.async_save_room(room, 0)
    entity = manager.entities[room_id]
    await entity.async_set_temperature(temperature=21)
    await manager.async_set_master_offset(-2)
    await hass.async_block_till_done()
    assert entity.target_temperature == 19
    assert entity.coordinator.target == 21
    await entity.async_set_temperature(temperature=20)
    assert entity.coordinator.target == 22
    await manager.async_set_master_offset(0)
    await hass.async_block_till_done()
    assert entity.target_temperature == 22
    restored = RoomManager(hass)
    await restored.async_initialize()
    assert restored.settings["master_offset"] == 0
    async_register_services(hass)
    await hass.services.async_call(
        "thermo_control", "set_master_offset", {"offset": 5}, blocking=True
    )
    await hass.async_block_till_done()
    await entity.coordinator.async_set_intent(temperature=30)
    assert entity.target_temperature == 30  # Clamp to physical maximum.
    assert entity.coordinator.target == 30
    sensor = DemandSensor(manager, "demand", "Demand")
    assert sensor.native_value == manager.system.snapshot()["demand"]
    assert sensor.extra_state_attributes["eligible_demand"] >= 0
    restored.system.close()


async def test_settings_storage_error_revision_and_global_group_precedence(manager, room, hass):
    config = deepcopy(SYSTEM_DEFAULTS)
    config["control"]["lookahead"] = 120
    config["groups"] = [
        {"id": "ground", "name": "Erdgeschoss", "control": {**config["control"], "lookahead": 60}}
    ]
    await manager.async_save_settings(config, 0)
    room_id = await manager.async_save_room(
        {**room, "heating_type": "floor", "group_id": "ground", "lookahead": 30}, 1
    )
    assert manager.entities[room_id].coordinator.control_config()["lookahead"] == 60
    with pytest.raises(ServiceValidationError, match="inzwischen"):
        await manager.async_save_settings(config, 0)
    with patch.object(manager._store, "async_save", AsyncMock(side_effect=OSError("disk full"))):
        with pytest.raises(OSError):
            await manager.async_save_settings({**config, "master_offset": 1}, manager.revision)
    assert manager.settings["master_offset"] == 0
    assert manager.revision == 2
    with pytest.raises(ServiceValidationError, match="neu zuordnen"):
        await manager.async_save_settings({**config, "groups": []}, manager.revision)
    await manager.async_save_room(
        {**manager.rooms[room_id], "group_id": None, "use_global_control": False},
        manager.revision,
        room_id,
    )
    assert manager.entities[room_id].coordinator.control_config()["lookahead"] == 30
    await manager.async_save_room(
        {**manager.rooms[room_id], "use_global_control": True}, manager.revision, room_id
    )
    assert manager.entities[room_id].coordinator.control_config()["lookahead"] == 120
    await manager.async_save_settings({**config, "groups": []}, manager.revision)
    assert not manager.groups


@pytest.mark.parametrize(
    "change",
    [
        {"master_offset": float("nan")},
        {"master_offset": 6},
        {"calibration_interval": 1},
        {"groups": [{"id": "same", "name": "A"}, {"id": "same", "name": "B"}]},
        {"groups": [{"id": "bad space", "name": "A"}]},
        {"groups": [{"id": "a", "name": "  "}]},
        {"control": {**SYSTEM_DEFAULTS["control"], "cycle_minutes": 10}},
        {"control": {**SYSTEM_DEFAULTS["control"], "minimum_on": 1800, "minimum_off": 1800}},
        {"heat_pump": {**SYSTEM_DEFAULTS["heat_pump"], "interlock": True}},
        {"heat_pump": {**SYSTEM_DEFAULTS["heat_pump"], "flow_sensor": "binary_sensor.compressor"}},
        {"heat_pump": {**SYSTEM_DEFAULTS["heat_pump"], "automatic_states": ["  "]}},
    ],
)
async def test_settings_reject_invalid_values(hass, change):
    with pytest.raises(ServiceValidationError):
        validate_settings(hass, {**deepcopy(SYSTEM_DEFAULTS), **change})


async def test_pump_fahrenheit_mode_alias_and_unknown_compressor(hass, manager, pump_config):
    hass.states.async_set("sensor.flow", 86, {"unit_of_measurement": "°F"})
    hass.states.async_set("binary_sensor.compressor", "unknown")
    pump_config["heat_pump"]["automatic_states"] = [" AUTOMATIK "]
    await manager.async_save_settings(pump_config, 0)
    assert manager.system.telemetry()["flow"] == pytest.approx(30)
    assert manager.system.telemetry()["automatic"]
    assert manager.system.telemetry()["compressor"] is None
    assert manager.system.permit(29) == (False, "no_flow_heat")
    assert manager.system.permit(20) == (True, None)


async def test_mode_listener_reconciles_rooms_and_removes_subscriptions(
    hass, manager, room, pump_config
):
    await manager.async_save_settings(pump_config, 0)
    room_id = await manager.async_save_room({**room, "temperature_sensor": None}, manager.revision)
    c = manager.entities[room_id].coordinator
    await c.async_set_intent(mode=HVACMode.HEAT, temperature=25)
    hass.states.async_set("sensor.pump_mode", "Off")
    await hass.async_block_till_done()
    assert not c.heat_permitted
    await manager.async_shutdown()
    assert manager.system._unsubscribe is None


async def test_control_persistence_failure_withholds_valve_commands(manager, room, service_calls):
    room_id = await manager.async_save_room({**room, "heating_type": "floor"}, 0)
    c = manager.entities[room_id].coordinator
    service_calls.clear()
    with patch.object(c._store, "async_save", AsyncMock(side_effect=OSError("disk"))):
        with pytest.raises(OSError):
            await c.async_set_intent(mode=HVACMode.HEAT, temperature=25)
    assert not service_calls
    assert not c.controller.active


async def test_service_before_setup_and_invalid_offset(hass, manager):
    async_register_services(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "thermo_control", "set_master_offset", {"offset": float("inf")}, blocking=True
        )
    await manager.async_shutdown()
    with pytest.raises(ServiceValidationError, match="nicht bereit"):
        await hass.services.async_call(
            "thermo_control", "set_master_offset", {"offset": 1}, blocking=True
        )


async def test_real_group_climates_sensors_and_restart(hass, hass_storage, room, service_calls):
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="thermo_control", data={}, unique_id="thermo_control")
    entry.add_to_hass(hass)
    with patch("homeassistant.components.frontend.async_setup", AsyncMock(return_value=True)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        manager = entry.runtime_data
        settings = deepcopy(SYSTEM_DEFAULTS)
        settings["groups"] = [{"id": "ground", "name": "Ground", "control": {}}]
        await manager.async_save_settings(settings, 0)
        await hass.async_block_till_done()
        room_id = await manager.async_save_room({**room, "group_id": "ground"}, manager.revision)
        await hass.async_block_till_done()
        group = manager.groups["ground"]
        group_id = group.entity_id
        assert er.async_get(hass).async_get(group_id).config_entry_id == entry.entry_id
        assert group.current_temperature == 20
        assert group.target_temperature == 20
        assert group.available
        await group.async_set_temperature(temperature=22, hvac_mode="heat")
        assert group.hvac_mode == "heat"
        assert group.target_temperature == 22
        await group.async_set_preset_mode("eco")
        assert group.preset_mode == "eco"
        assert group.target_temperature == 17
        state = hass.states.get("climate.a")
        hass.states.async_set("climate.a", "heat", {**state.attributes, "hvac_action": "heating"})
        await manager.entities[room_id].coordinator._tick()
        await hass.async_block_till_done()
        assert hass.states.get(group_id).attributes["hvac_action"] == "heating"
        assert not group.extra_state_attributes["mixed_targets"]
        await group.async_set_hvac_mode("off")
        assert group.hvac_mode == "off"
        for operation in (
            group.async_set_temperature(temperature=99),
            group.async_set_temperature(temperature=22, hvac_mode="cool"),
            group.async_set_hvac_mode("cool"),
            group.async_set_preset_mode("invalid"),
        ):
            with pytest.raises(ServiceValidationError):
                await operation
        demand_id = er.async_get(hass).async_get_entity_id(
            "sensor", "thermo_control", "thermo_control_demand"
        )
        assert demand_id
        assert hass.states.get(demand_id).state == "0.0"
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        manager = entry.runtime_data
        assert manager.groups["ground"].entity_id == group_id
        assert manager.rooms[room_id]["group_id"] == "ground"
        assert manager.groups["ground"].hvac_mode == "off"
        # Unassign first, then remove the group and its entity registry entry.
        await manager.async_save_room(
            {**manager.rooms[room_id], "group_id": None}, manager.revision, room_id
        )
        await manager.async_save_settings({**manager.settings, "groups": []}, manager.revision)
        await hass.async_block_till_done()
        assert er.async_get(hass).async_get(group_id) is None
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_global_calibration_interval_is_applied(manager, room, service_calls, hass, freezer):
    settings = deepcopy(SYSTEM_DEFAULTS)
    settings["calibration_interval"] = 3600
    await manager.async_save_settings(settings, 0)
    room_id = await manager.async_save_room(
        {**room, "use_global_calibration": True}, manager.revision
    )
    c = manager.entities[room_id].coordinator
    await c.async_set_intent(mode=HVACMode.HEAT)
    assert len([call for call in service_calls if call[0] == "number"]) == 2
    hass.states.async_set("sensor.room", 18, {"unit_of_measurement": "°C"})
    freezer.tick(timedelta(minutes=15))
    await c._tick()
    assert len([call for call in service_calls if call[0] == "number"]) == 2
    freezer.tick(timedelta(minutes=45))
    await c._tick()
    assert len([call for call in service_calls if call[0] == "number"]) == 4


async def test_settings_validates_temperature_and_control_room_entities(hass, manager, room):
    hass.states.async_set("sensor.not_temperature", 4, {"unit_of_measurement": "%"})
    config = deepcopy(SYSTEM_DEFAULTS)
    config["heat_pump"]["flow_sensor"] = "sensor.not_temperature"
    with pytest.raises(ServiceValidationError, match="Temperatureinheit"):
        await manager.async_save_settings(config, 0)
    with pytest.raises(ServiceValidationError, match="Gruppe"):
        await manager.async_save_room({**room, "group_id": "missing"}, 0)
    with pytest.raises(ServiceValidationError, match="Zyklus"):
        await manager.async_save_room({**room, "minimum_on": 1800, "minimum_off": 1800}, 0)


async def test_offset_at_hardware_boundary_survives_reload(hass, hass_storage, room, service_calls):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="thermo_control", data={}, unique_id="thermo_control")
    entry.add_to_hass(hass)
    with patch("homeassistant.components.frontend.async_setup", AsyncMock(return_value=True)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        manager = entry.runtime_data
        room_id = await manager.async_save_room(room, 0)
        await hass.async_block_till_done()
        await manager.async_set_master_offset(5)
        await hass.async_block_till_done()
        entity = manager.entities[room_id]
        await entity.async_set_temperature(temperature=5)
        assert entity.coordinator.target == 0
        assert entity.target_temperature == 5
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        manager = entry.runtime_data
        entity = manager.entities[room_id]
        assert entity.target_temperature == 5
        assert entity.coordinator.target == 0
        await entity.async_set_preset_mode("eco")
        await entity.async_set_preset_mode("none")
        assert entity.target_temperature == 5
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_group_multiple_rooms_aggregate_actual_status_without_double_count(
    manager, room, hass
):
    settings = deepcopy(SYSTEM_DEFAULTS)
    settings["groups"] = [{"id": "g", "name": "Both", "control": {}}]
    await manager.async_save_settings(settings, 0)
    first = {
        **room,
        "trvs": ["climate.a"],
        "devices": {"climate.a": room["devices"]["climate.a"]},
        "group_id": "g",
    }
    second = {
        **room,
        "name": "Second",
        "trvs": ["climate.b"],
        "devices": {"climate.b": room["devices"]["climate.b"]},
        "group_id": "g",
    }
    first_id = await manager.async_save_room(first, manager.revision)
    second_id = await manager.async_save_room(second, manager.revision)
    group = manager.groups["g"]
    await group.async_set_temperature(temperature=22, hvac_mode="heat")
    assert all(entity.target_temperature == 22 for entity in group.members)
    await manager.entities[first_id].async_set_temperature(temperature=23)
    assert group.extra_state_attributes["mixed_targets"]
    assert group.target_temperature == 22.5
    state = hass.states.get("climate.b")
    hass.states.async_set("climate.b", "heat", {**state.attributes, "hvac_action": "heating"})
    await manager.entities[second_id].coordinator._tick()
    assert group.hvac_action == "heating"
    assert manager.system.snapshot()["heating_rooms"] == 1
    assert manager.system.snapshot()["demand_rooms"] == 2
    assert len(group.extra_state_attributes["rooms"]) == 2
    # Empty/disabled physical rooms cannot request heat through unavailable valves.
    hass.states.async_set("climate.a", "unavailable")
    hass.states.async_set("climate.b", "unavailable")
    for entity in group.members:
        await entity.coordinator._tick()
    assert not group.available
    assert manager.system.snapshot()["demand"] == 0


async def test_master_service_requires_admin_for_user_calls(hass, manager, hass_read_only_user):
    from homeassistant.core import Context
    from homeassistant.exceptions import Unauthorized

    user = hass_read_only_user
    async_register_services(hass)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "thermo_control",
            "set_master_offset",
            {"offset": 1},
            blocking=True,
            context=Context(user_id=user.id),
        )
    assert manager.settings["master_offset"] == 0
