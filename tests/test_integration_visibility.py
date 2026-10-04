"""Verify the same catalog and entry filters used by HA's integrations UI."""

from unittest.mock import AsyncMock, patch

from homeassistant import loader
from homeassistant.components.frontend import async_panel_exists
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.thermo_control.const import DOMAIN, NAME

# The integration overview subscribes to exactly these types; helpers are separate.
INTEGRATION_TYPES = ["device", "hub", "service", "hardware"]


async def test_listed_as_integration_in_add_dialog(hass):
    descriptions = await loader.async_get_integration_descriptions(hass)
    metadata = descriptions["custom"]["integration"][DOMAIN]
    assert metadata["name"] == NAME
    assert metadata["integration_type"] == "hub"
    assert metadata["config_flow"]
    assert metadata["single_config_entry"]
    assert DOMAIN not in descriptions["custom"]["helper"]
    assert DOMAIN in await loader.async_get_config_flows(hass)
    assert DOMAIN not in await loader.async_get_config_flows(hass, "helper")


async def test_confirmed_entry_visible_before_any_room_and_after_reload(
    hass, hass_storage, hass_ws_client, room, service_calls
):
    # Only the compiled HA frontend distribution is omitted. Flow, entry setup,
    # panel registry, climate platform and authenticated websocket API are real.
    with patch("homeassistant.components.frontend.async_setup", AsyncMock(return_value=True)):
        flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert flow["type"] == FlowResultType.FORM
        assert flow["data_schema"].schema == {}
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        entry = result["result"]
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert entry.data == {}
        assert entry.runtime_data.rooms == {}
        assert async_panel_exists(hass, DOMAIN)
        client = await hass_ws_client(hass)
        await client.send_json(
            {"id": 1, "type": "config_entries/subscribe", "type_filter": INTEGRATION_TYPES}
        )
        assert (await client.receive_json())["success"]
        changes = (await client.receive_json())["event"]
        visible = [change["entry"] for change in changes if change["entry"]["domain"] == DOMAIN]
        assert len(visible) == 1
        assert visible[0]["entry_id"] == entry.entry_id
        assert visible[0]["title"] == NAME
        assert visible[0]["state"] == "loaded"
        await client.send_json({"id": 2, "type": "unsubscribe_events", "subscription": 1})
        assert (await client.receive_json())["success"]
        await client.send_json({"id": 3, "type": "config_entries/get", "type_filter": ["helper"]})
        assert all(item["domain"] != DOMAIN for item in (await client.receive_json())["result"])
        await client.send_json(
            {"id": 4, "type": f"{DOMAIN}/save_room", "config": room, "revision": 0}
        )
        saved = await client.receive_json()
        assert saved["success"]
        room_id = saved["result"]["room_id"]
        await hass.async_block_till_done()
        entity_id = entry.runtime_data.entities[room_id].entity_id
        assert er.async_get(hass).async_get(entity_id).config_entry_id == entry.entry_id
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert async_panel_exists(hass, DOMAIN)
        assert entry.runtime_data.entities[room_id].entity_id == entity_id
        await client.send_json(
            {"id": 5, "type": "config_entries/get", "type_filter": INTEGRATION_TYPES}
        )
        assert any(
            item["entry_id"] == entry.entry_id for item in (await client.receive_json())["result"]
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
