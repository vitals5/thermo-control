"""Persistent panel room edits and validation at the backend boundary."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.exceptions import ServiceValidationError

from custom_components.thermo_control.manager import RoomManager


async def test_create_edit_delete_and_restart(manager, room, hass, hass_storage):
    room_id = await manager.async_save_room(room, 0)
    assert manager.snapshot()["rooms"][0]["id"] == room_id
    assert manager.revision == 1
    await manager.entities[room_id].coordinator.async_set_intent(mode=HVACMode.HEAT, temperature=22)
    config = {**room, "name": "Renamed", "window_sensors": []}
    await manager.async_save_room(config, 1, room_id)
    assert manager.entities[room_id].coordinator.target == 22
    assert manager.entities[room_id].coordinator.mode == HVACMode.HEAT
    assert manager.rooms[room_id]["name"] == "Renamed"
    restarted = RoomManager(hass)
    await restarted.async_initialize()
    assert restarted.rooms == manager.rooms
    assert restarted.revision == 2
    await manager.async_delete_room(room_id, 2)
    assert manager.rooms == {}
    assert manager.revision == 3


async def test_revision_conflict_preserves_config(manager, room):
    room_id = await manager.async_save_room(room, 0)
    with pytest.raises(ServiceValidationError, match="inzwischen"):
        await manager.async_save_room({**room, "name": "Stale"}, 0, room_id)
    assert manager.rooms[room_id]["name"] == room["name"]


async def test_storage_failure_keeps_running_room(manager, room):
    room_id = await manager.async_save_room(room, 0)
    existing = manager.entities[room_id]
    with patch.object(manager._store, "async_save", AsyncMock(side_effect=OSError("disk full"))):
        with pytest.raises(OSError):
            await manager.async_save_room({**room, "name": "New"}, 1, room_id)
    assert manager.entities[room_id] is existing
    assert not existing.coordinator._closed
    assert manager.revision == 1


async def test_duplicate_trv(manager, room):
    await manager.async_save_room(room, 0)
    with pytest.raises(ServiceValidationError, match="bereits"):
        await manager.async_save_room({**room, "name": "Duplicate"}, 1)


@pytest.mark.parametrize(
    "key,value",
    [
        ("calibration_interval", 10),
        ("calibration_threshold", float("nan")),
        ("name", "  "),
        ("trvs", []),
        ("window_sensors", ["sensor.room"]),
        ("preset_boost", 35),
    ],
)
async def test_invalid_configuration(manager, room, key, value):
    with pytest.raises(ServiceValidationError):
        await manager.async_save_room({**room, key: value}, 0)
    assert manager.rooms == {}


async def test_offline_sensor_can_be_edited(manager, room, hass):
    hass.states.async_set("sensor.room", "unavailable", {"unit_of_measurement": "°C"})
    room_id = await manager.async_save_room(room, 0)
    assert room_id in manager.rooms


async def test_mapping_conflict_and_topic_validation(manager, room):
    config = deepcopy(room)
    config["devices"]["climate.a"]["calibration_topic"] = (
        "zigbee2mqtt/a/set/local_temperature_calibration"
    )
    with pytest.raises(ServiceValidationError, match="Entweder"):
        await manager.async_save_room(config, 0)
    del config["devices"]["climate.a"]["calibration_entity"]
    config["devices"]["climate.a"]["calibration_topic"] = (
        "zigbee2mqtt/+/set/local_temperature_calibration"
    )
    with pytest.raises(ServiceValidationError, match="MQTT"):
        await manager.async_save_room(config, 0)


async def test_deleted_room_and_stopped_manager(manager, room):
    with pytest.raises(ServiceValidationError, match="existiert"):
        await manager.async_delete_room("missing", 0)
    await manager.async_shutdown()
    with pytest.raises(ServiceValidationError, match="bereit"):
        await manager.async_save_room(room, 0)


async def test_legacy_import_is_once_only(manager, entry, hass):
    await manager.async_import_legacy([entry])
    assert entry.entry_id in manager.rooms
    assert manager.revision == 1
    await manager.async_bind_platform(lambda entities: None)
    await manager.async_delete_room(entry.entry_id, 1)
    restarted = RoomManager(hass)
    await restarted.async_initialize()
    await restarted.async_import_legacy([entry])
    assert restarted.rooms == {}
    assert restarted.revision == 2


async def test_legacy_registry_detached_from_old_entry(manager, entry, hass):
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "climate",
        "thermo_control",
        entry.entry_id,
        config_entry=entry,
        suggested_object_id="living_room",
    )
    await manager.async_import_legacy([entry])
    await manager.async_bind_platform(lambda entities: None)
    assert registry.async_get(old.entity_id).config_entry_id is None
    assert registry.async_get(old.entity_id).unique_id == entry.entry_id


@pytest.mark.parametrize("sensor", [None, "", "omitted"])
async def test_optional_sensor_can_be_stored_and_restored(manager, room, hass, sensor):
    config = deepcopy(room)
    if sensor == "omitted":
        del config["temperature_sensor"]
    else:
        config["temperature_sensor"] = sensor
    room_id = await manager.async_save_room(config, 0)
    assert manager.rooms[room_id]["temperature_sensor"] is None
    assert manager.entities[room_id].coordinator.data["temperature"] == 23
    restored = RoomManager(hass)
    await restored.async_initialize()
    assert restored.rooms[room_id]["temperature_sensor"] is None


async def test_external_sensor_can_be_removed_from_existing_room(manager, room, service_calls):
    room_id = await manager.async_save_room(room, 0)
    await manager.entities[room_id].async_set_temperature(temperature=22, hvac_mode="heat")
    service_calls.clear()
    await manager.async_save_room({**room, "temperature_sensor": None}, 1, room_id)
    climate = manager.entities[room_id]
    await climate.coordinator._tick()
    assert climate.target_temperature == 22
    assert climate.current_temperature == 23
    assert climate.extra_state_attributes["temperature_sensor"] is None
    assert climate.extra_state_attributes["temperature_source"] == "thermostats"
    assert not [call for call in service_calls if call[0] in ("number", "mqtt")]


@pytest.mark.parametrize("sensor", ["climate.a", "sensor.missing", "sensor.room_invalid", 42])
async def test_optional_sensor_still_validated_when_selected(manager, room, hass, sensor):
    hass.states.async_set("sensor.room_invalid", "45", {"unit_of_measurement": "%"})
    with pytest.raises(ServiceValidationError):
        await manager.async_save_room({**room, "temperature_sensor": sensor}, 0)
