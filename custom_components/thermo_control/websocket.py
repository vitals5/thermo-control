"""Authenticated panel API with server-side validation and edit revisions."""

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .manager import SIGNAL_ROOMS


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/rooms"})
@websocket_api.require_admin
@callback
def ws_rooms(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    connection.send_result(msg["id"], hass.data[DOMAIN].snapshot())


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@websocket_api.require_admin
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    @callback
    def updated() -> None:
        connection.send_event(msg["id"], hass.data[DOMAIN].snapshot())

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_ROOMS, updated)
    connection.send_result(msg["id"])
    updated()


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save_room",
        vol.Required("config"): dict,
        vol.Required("revision"): vol.All(int, vol.Range(min=0)),
        vol.Optional("room_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_room(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    try:
        room_id = await hass.data[DOMAIN].async_save_room(
            msg["config"], msg["revision"], msg.get("room_id")
        )
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_configuration", str(err))
    except OSError:
        connection.send_error(
            msg["id"], "storage_error", "Die Konfiguration konnte nicht gespeichert werden."
        )
    else:
        connection.send_result(msg["id"], {"room_id": room_id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/delete_room",
        vol.Required("room_id"): str,
        vol.Required("revision"): vol.All(int, vol.Range(min=0)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_room(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    try:
        await hass.data[DOMAIN].async_delete_room(msg["room_id"], msg["revision"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_configuration", str(err))
    except OSError:
        connection.send_error(msg["id"], "storage_error", "Der Raum konnte nicht gelöscht werden.")
    else:
        connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save_settings",
        vol.Required("config"): dict,
        vol.Required("revision"): vol.All(int, vol.Range(min=0)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_settings(hass, connection, msg):
    try:
        await hass.data[DOMAIN].async_save_settings(msg["config"], msg["revision"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_configuration", str(err))
    except OSError:
        connection.send_error(
            msg["id"], "storage_error", "Systemeinstellungen konnten nicht gespeichert werden."
        )
    else:
        connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/master_offset", vol.Required("offset"): vol.Coerce(float)}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_master_offset(hass, connection, msg):
    try:
        await hass.data[DOMAIN].async_set_master_offset(msg["offset"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_configuration", str(err))
    except OSError:
        connection.send_error(
            msg["id"], "storage_error", "Sollwertverschiebung konnte nicht gespeichert werden."
        )
    else:
        connection.send_result(msg["id"])


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    for command in (
        ws_rooms,
        ws_subscribe,
        ws_save_room,
        ws_delete_room,
        ws_save_settings,
        ws_master_offset,
    ):
        websocket_api.async_register_command(hass, command)
