"""Panel commands through Home Assistant's authenticated WebSocket server."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.thermo_control.websocket import async_register_commands


async def test_list_save_delete(hass, hass_ws_client, manager, room):
    async_register_commands(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "thermo_control/rooms"})
    assert (await client.receive_json())["result"]["rooms"] == []
    await client.send_json(
        {"id": 2, "type": "thermo_control/save_room", "config": room, "revision": 0}
    )
    saved = await client.receive_json()
    assert saved["success"]
    room_id = saved["result"]["room_id"]
    await client.send_json(
        {"id": 3, "type": "thermo_control/delete_room", "room_id": room_id, "revision": 1}
    )
    assert (await client.receive_json())["success"]


async def test_subscribe_and_unsubscribe(hass, hass_ws_client, manager, room):
    async_register_commands(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "thermo_control/subscribe"})
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"]["revision"] == 0
    await manager.async_save_room(room, 0)
    assert (await client.receive_json())["event"]["revision"] == 1
    await client.send_json({"id": 2, "type": "unsubscribe_events", "subscription": 1})
    assert (await client.receive_json())["success"]


async def test_validation_error(hass, hass_ws_client, manager, room):
    async_register_commands(hass)
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "thermo_control/save_room",
            "config": {**room, "calibration_interval": 1},
            "revision": 0,
        }
    )
    result = await client.receive_json()
    assert result["error"]["code"] == "invalid_configuration"


@pytest.mark.parametrize(
    "type",
    [
        "thermo_control/rooms",
        "thermo_control/subscribe",
        "thermo_control/save_room",
        "thermo_control/delete_room",
    ],
)
async def test_admin_required(
    hass, hass_ws_client, hass_read_only_access_token, manager, room, type
):
    async_register_commands(hass)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    data = {"id": 1, "type": type}
    if type.endswith("save_room"):
        data.update(config=room, revision=0)
    if type.endswith("delete_room"):
        data.update(room_id="missing", revision=0)
    await client.send_json(data)
    result = await client.receive_json()
    assert not result["success"]
    assert result["error"]["code"] == "unauthorized"


async def test_storage_error(hass, hass_ws_client, manager, room):
    async_register_commands(hass)
    client = await hass_ws_client(hass)
    with patch.object(manager._store, "async_save", AsyncMock(side_effect=OSError("disk full"))):
        await client.send_json(
            {"id": 1, "type": "thermo_control/save_room", "config": room, "revision": 0}
        )
        result = await client.receive_json()
        assert result["error"]["code"] == "storage_error"


@pytest.mark.parametrize("command", ["save_settings", "master_offset"])
async def test_system_commands(hass, hass_ws_client, manager, command):
    from copy import deepcopy

    from custom_components.thermo_control.const import SYSTEM_DEFAULTS

    async_register_commands(hass)
    client = await hass_ws_client(hass)
    data = {"id": 1, "type": f"thermo_control/{command}"}
    if command == "save_settings":
        data.update(config=deepcopy(SYSTEM_DEFAULTS), revision=0)
    else:
        data["offset"] = -2
    await client.send_json(data)
    assert (await client.receive_json())["success"]
    assert manager.revision == 1
    invalid = {**data, "id": 2}
    if command == "save_settings":
        invalid["config"] = {**invalid["config"], "master_offset": 99}
        invalid["revision"] = 1
    else:
        invalid["offset"] = 99
    await client.send_json(invalid)
    assert (await client.receive_json())["error"]["code"] == "invalid_configuration"
    data["id"] = 3
    if command == "save_settings":
        data["revision"] = 1
    with patch.object(manager._store, "async_save", AsyncMock(side_effect=OSError("full"))):
        await client.send_json(data)
        assert (await client.receive_json())["error"]["code"] == "storage_error"


@pytest.mark.parametrize("command", ["save_settings", "master_offset"])
async def test_system_commands_require_admin(
    hass, hass_ws_client, hass_read_only_access_token, manager, command
):
    from copy import deepcopy

    from custom_components.thermo_control.const import SYSTEM_DEFAULTS

    async_register_commands(hass)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    message = {"id": 1, "type": f"thermo_control/{command}"}
    if command == "save_settings":
        message.update(config=deepcopy(SYSTEM_DEFAULTS), revision=0)
    else:
        message["offset"] = 1
    await client.send_json(message)
    assert (await client.receive_json())["error"]["code"] == "unauthorized"
