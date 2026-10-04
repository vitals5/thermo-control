"""Climate services and lifecycle including restore before initial commands."""

import logging
from datetime import timedelta

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.core import State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import EntityPlatform
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.thermo_control.climate import ThermoControlClimate


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
