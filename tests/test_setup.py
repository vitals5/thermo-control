"""Sidebar registration and the empty YAML-only bootstrap."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.thermo_control import (
    CONFIG_SCHEMA,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.thermo_control.const import DOMAIN
from custom_components.thermo_control.panel import async_register_panel


async def test_empty_bootstrap(hass, hass_storage):
    with (
        patch("custom_components.thermo_control.async_register_panel", AsyncMock()) as panel,
        patch("custom_components.thermo_control.async_load_platform", AsyncMock()) as platform,
    ):
        assert await async_setup(hass, CONFIG_SCHEMA({DOMAIN: {}}))
        panel.assert_awaited_once()
        platform.assert_awaited_once()
        assert hass.data[DOMAIN].rooms == {}
        await hass.async_stop()
        assert hass.data[DOMAIN]._closed


def test_no_config_flow():
    manifest = json.loads(Path("custom_components/thermo_control/manifest.json").read_text())
    assert not manifest.get("config_flow")
    assert not Path("custom_components/thermo_control/config_flow.py").exists()


async def test_local_panel_registration(hass):
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    with patch(
        "custom_components.thermo_control.panel.panel_custom.async_register_panel", AsyncMock()
    ) as panel:
        await async_register_panel(hass, Path("custom_components/thermo_control/frontend"))
        assert panel.await_args.kwargs["frontend_url_path"] == DOMAIN
        assert panel.await_args.kwargs["require_admin"] is True
        assert panel.await_args.kwargs["module_url"].startswith("/thermo_control_static/")
        paths = hass.http.async_register_static_paths.await_args.args[0]
        assert paths[0].url_path == "/thermo_control_static"


async def test_legacy_entry_compatibility(hass, entry, manager):
    assert await async_setup_entry(hass, entry)
    assert entry.runtime_data is manager
    assert await async_unload_entry(hass, entry)
