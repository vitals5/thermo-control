"""Empty UI installation, panel registration, migration and entry lifecycle."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermo_control import (
    CONFIG_SCHEMA,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.thermo_control.const import DOMAIN
from custom_components.thermo_control.panel import PANEL_PATHS, async_register_panel


async def test_setup_does_not_start_panel_without_entry(hass):
    with patch("custom_components.thermo_control.async_register_panel", AsyncMock()) as panel:
        assert await async_setup(hass, {})
        panel.assert_not_called()
        assert DOMAIN not in hass.data


async def test_yaml_bootstrap_imports_empty_entry(hass):
    with patch.object(hass.config_entries.flow, "async_init", AsyncMock()) as flow:
        assert await async_setup(hass, CONFIG_SCHEMA({DOMAIN: {}}))
        await hass.async_block_till_done()
        flow.assert_awaited_once_with(DOMAIN, context={"source": "import"}, data={})


async def test_empty_entry_setup_unload_and_reload(hass, hass_storage):
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    with (
        patch("custom_components.thermo_control.async_register_panel", AsyncMock()) as panel,
        patch("custom_components.thermo_control.async_remove_panel") as remove,
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()) as forward,
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)),
    ):
        assert await async_setup_entry(hass, entry)
        manager = entry.runtime_data
        assert manager.rooms == {}
        assert manager.config_entry_id == entry.entry_id
        assert manager.revision == 0
        forward.assert_awaited_once_with(entry, ["climate", "sensor"])
        assert await async_unload_entry(hass, entry)
        assert manager._closed
        assert remove.call_args_list == [call(hass, path) for path in PANEL_PATHS]
        assert await async_setup_entry(hass, entry)
        assert entry.runtime_data is not manager
        assert panel.await_count == 2
        await hass.async_stop()
        assert entry.runtime_data._closed


async def test_failed_platform_unload_retains_running_panel(hass, hass_storage):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    with (
        patch("custom_components.thermo_control.async_register_panel", AsyncMock()),
        patch("custom_components.thermo_control.async_remove_panel") as remove,
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)),
    ):
        await async_setup_entry(hass, entry)
        assert not await async_unload_entry(hass, entry)
        assert not entry.runtime_data._closed
        remove.assert_not_called()
        await entry.runtime_data.async_shutdown()


async def test_failed_setup_cleans_up(hass, hass_storage):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    with (
        patch("custom_components.thermo_control.async_register_panel", AsyncMock()),
        patch("custom_components.thermo_control.async_remove_panel") as remove,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", AsyncMock(side_effect=RuntimeError)
        ),
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)),
    ):
        with pytest.raises(RuntimeError):
            await async_setup_entry(hass, entry)
        assert entry.runtime_data._closed
        assert remove.call_args_list == [call(hass, path) for path in PANEL_PATHS]


async def test_local_panel_registration_can_repeat(hass):
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    with patch(
        "custom_components.thermo_control.panel.panel_custom.async_register_panel", AsyncMock()
    ) as panel:
        await async_register_panel(hass, Path("custom_components/thermo_control/frontend"))
        await async_register_panel(hass, Path("custom_components/thermo_control/frontend"))
        assert panel.await_count == 4
        for index, registration in enumerate(panel.await_args_list):
            kwargs = registration.kwargs
            assert kwargs["frontend_url_path"] == PANEL_PATHS[index % 2]
            assert kwargs["require_admin"] is True
            assert kwargs["module_url"].startswith("/thermo_control_static/")
            assert kwargs["sidebar_title"] == ("Thermo Control" if index % 2 == 0 else None)
            assert kwargs["config_panel_domain"] == (DOMAIN if index % 2 == 0 else None)
        hass.http.async_register_static_paths.assert_awaited_once()
        paths = hass.http.async_register_static_paths.await_args.args[0]
        assert paths[0].url_path == "/thermo_control_static"


async def test_legacy_entries_share_one_platform_and_transfer_host(hass, entry, hass_storage):
    other = MockConfigEntry(domain=DOMAIN, data={})
    other.add_to_hass(hass)
    with (
        patch("custom_components.thermo_control.async_register_panel", AsyncMock()) as panel,
        patch("custom_components.thermo_control.async_remove_panel"),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()) as forward,
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)),
        patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload,
    ):
        assert await async_setup_entry(hass, entry)
        assert await async_setup_entry(hass, other)
        assert other.runtime_data is entry.runtime_data
        assert entry.entry_id in other.runtime_data.rooms
        assert len(other.runtime_data.rooms) == 1
        panel.assert_awaited_once()
        forward.assert_awaited_once()
        assert await async_unload_entry(hass, other)
        assert not entry.runtime_data._closed
        other.mock_state(hass, ConfigEntryState.LOADED)
        assert await async_unload_entry(hass, entry)
        await hass.async_block_till_done()
        reload.assert_awaited_once_with(other.entry_id)


async def test_unload_without_runtime_is_safe(hass):
    assert await async_unload_entry(hass, MockConfigEntry(domain=DOMAIN, data={}))


@pytest.mark.parametrize("external_sensor", [True, False])
async def test_real_entry_platform_restores_rooms_on_reload(
    hass, hass_storage, room, service_calls, external_sensor
):
    from homeassistant.components.frontend import async_panel_exists
    from homeassistant.helpers import entity_registry as er

    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    if not external_sensor:
        room = {**room, "temperature_sensor": None}
    # Frontend's compiled distribution is not part of the HA test environment.
    # The actual panel registry, static path and climate platform remain real.
    with patch("homeassistant.components.frontend.async_setup", AsyncMock(return_value=True)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert all(async_panel_exists(hass, path) for path in PANEL_PATHS)
        manager = entry.runtime_data
        room_id = await manager.async_save_room(room, manager.revision)
        await hass.async_block_till_done()
        entity = manager.entities[room_id]
        entity_id = entity.entity_id
        assert hass.states.get(entity_id).attributes["current_temperature"] == (
            20 if external_sensor else 23
        )
        assert er.async_get(hass).async_get(entity_id).config_entry_id == entry.entry_id
        await entity.async_set_temperature(temperature=22, hvac_mode="heat")
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not any(async_panel_exists(hass, path) for path in PANEL_PATHS)
        assert hass.states.get(entity_id).state == "unavailable"
        assert entity.coordinator._closed
        assert manager._closed
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert all(async_panel_exists(hass, path) for path in PANEL_PATHS)
        assert entry.runtime_data is not manager
        assert room_id in entry.runtime_data.rooms
        assert entry.runtime_data.entities[room_id].entity_id == entity_id
        assert hass.states.get(entity_id).attributes["temperature"] == 22
        assert hass.states.get(entity_id).state == "heat"
        assert await hass.config_entries.async_unload(entry.entry_id)
