"""Climate services and lifecycle including restore before initial commands."""

import logging
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.core import State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import EntityPlatform
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.thermo_control.climate import ThermoControlClimate
from custom_components.thermo_control.const import SYSTEM_DEFAULTS


async def test_climate_services(coordinator):
    climate = ThermoControlClimate(coordinator)
    await climate.async_turn_on()
    assert climate.hvac_mode == HVACMode.HEAT
    await climate.async_set_temperature(temperature=21)
    assert climate.target_temperature == 21
    await climate.async_set_preset_mode("comfort")
    assert climate.preset_mode == "comfort"
    await climate.async_turn_off()
    assert climate.hvac_mode == HVACMode.OFF
    assert climate.extra_state_attributes["valve_position"] == 40
    assert climate.current_temperature == 20
    assert climate.min_temp == 5
    assert climate.max_temp == 30


@pytest.mark.parametrize("value", [None, "nan", 40, True])
async def test_invalid_temperature(coordinator, value):
    climate = ThermoControlClimate(coordinator)
    with pytest.raises(ServiceValidationError):
        await climate.async_set_temperature(temperature=value)


async def test_invalid_mode_and_preset(coordinator):
    climate = ThermoControlClimate(coordinator)
    with pytest.raises(ServiceValidationError):
        await climate.async_set_hvac_mode("cool")
    with pytest.raises(ServiceValidationError):
        await climate.async_set_preset_mode("schedule")
    with pytest.raises(ServiceValidationError):
        await climate.async_set_temperature(temperature=20, hvac_mode="cool")


async def test_real_setup_restore_and_unload(hass, room, service_calls, hass_storage):
    from custom_components.thermo_control.manager import RoomManager

    mock_restore_cache(
        hass,
        [
            State(
                "climate.living_room",
                "off",
                {
                    "temperature": 22,
                    "desired_hvac_mode": "heat",
                    "preset_mode": "none",
                    "manual_temperature": 22,
                },
            )
        ],
    )
    manager = RoomManager(hass)
    await manager.async_initialize()
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain="climate",
        platform_name="thermo_control",
        platform=None,
        scan_interval=timedelta(seconds=60),
        entity_namespace=None,
    )

    def add(entities):
        hass.async_create_task(platform.async_add_entities(entities))

    await manager.async_bind_platform(add)
    room_id = await manager.async_save_room(room, 0)
    await hass.async_block_till_done()
    entity = manager.entities[room_id]
    assert (state := hass.states.get("climate.living_room")) is not None
    assert state.attributes["temperature"] == 22
    assert state.attributes["desired_hvac_mode"] == "heat"
    original_id = entity.entity_id
    await manager.async_save_room({**room, "name": "Renamed"}, 1, room_id)
    await hass.async_block_till_done()
    assert manager.entities[room_id].entity_id == original_id
    assert hass.states.get(original_id).attributes["temperature"] == 22
    assert entity.coordinator._closed
    await manager.async_delete_room(room_id, 2)
    await hass.async_block_till_done()
    assert hass.states.get("climate.living_room") is None
    assert entity.coordinator._closed
    await platform.async_reset()
    await manager.async_shutdown()


@pytest.mark.parametrize(
    "preset,mode,target",
    [("schedule", "heat", 22), ("eco", "heat", 17), ("none", "heat", 21), ("none", "off", 21)],
)
@pytest.mark.parametrize("outage", ["sensor", "thermostats"])
@pytest.mark.parametrize("recovery", ["reload", "disk"])
async def test_unavailable_room_preserves_intent_on_reload(
    hass, room, service_calls, hass_storage, preset, mode, target, outage, recovery
):
    from homeassistant.helpers.restore_state import async_get
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.thermo_control.schedule import DAYS

    entry = MockConfigEntry(domain="thermo_control", data={}, unique_id="thermo_control")
    entry.add_to_hass(hass)
    with patch("homeassistant.components.frontend.async_setup", AsyncMock(return_value=True)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        manager = entry.runtime_data
        settings = deepcopy(SYSTEM_DEFAULTS)
        settings["groups"] = [{"id": "floor", "name": "Floor", "control": {}}]
        await manager.async_save_settings(settings, manager.revision)
        rid = await manager.async_save_room({**room, "group_id": "floor"}, manager.revision)
        await hass.async_block_till_done()
        entity = manager.entities[rid]
        entity_id = entity.entity_id
        await entity.async_set_temperature(temperature=21)
        await entity.async_set_hvac_mode(mode)
        if preset == "schedule":
            await manager.schedules.async_save(
                {
                    "group_id": "floor",
                    "enabled": True,
                    "weekdays": {
                        day: [{"from": "00:00", "to": "24:00", "temp": 22}] for day in DAYS
                    },
                },
                manager.schedules.revision,
            )
        else:
            await entity.async_set_preset_mode(preset)
        await entity.coordinator._tick()
        await hass.async_block_till_done()
        offline_ids = ["sensor.room"] if outage == "sensor" else ["climate.a", "climate.b"]
        originals = {eid: hass.states.get(eid) for eid in offline_ids}
        for eid in offline_ids:
            hass.states.async_set(eid, "unavailable")
        await entity.coordinator._tick()
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert state.state == "unavailable"
        assert "desired_hvac_mode" not in state.attributes
        assert "preset_mode" not in state.attributes
        restore_data = async_get(hass)
        # The unavailable state has no intent attributes, but its independent
        # restore payload must be included in HA's persisted startup snapshot.
        snapshot = next(
            item
            for item in restore_data.async_get_stored_states()
            if item.state.entity_id == entity_id
        )
        assert snapshot.extra_data.as_dict() == {
            "desired_hvac_mode": mode,
            "target_temperature_celsius": target,
            "manual_temperature": 21,
            "preset_mode": preset,
        }
        await restore_data.async_dump_states()
        if recovery == "reload":
            assert await hass.config_entries.async_reload(entry.entry_id)
        else:
            assert await hass.config_entries.async_unload(entry.entry_id)
            # Discard the in-memory removal cache and read the on-disk snapshot,
            # as HA's restore helper does at startup.
            restore_data.last_states.clear()
            await restore_data.async_load()
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        manager = entry.runtime_data
        restored = manager.entities[rid]
        assert restored.entity_id == entity_id
        assert restored.coordinator.mode == mode
        assert restored.preset_mode == preset
        assert restored.coordinator.target == target
        assert restored.coordinator.manual_target == 21
        for eid, original in originals.items():
            hass.states.async_set(eid, original.state, dict(original.attributes))
        await restored.coordinator._tick()
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == mode
        assert manager.groups["floor"].hvac_mode == mode
        assert manager.groups["floor"].preset_mode == preset
        assert restored.target_temperature == target
        assert await hass.config_entries.async_unload(entry.entry_id)
