"""Serve the bundled, local-only sidebar panel through Home Assistant."""

import json
from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, NAME

PANEL_PATHS = (DOMAIN, "thermo-control")


def _panel_version(assets: Path) -> str:
    manifest_file = assets.parent / "manifest.json"
    if manifest_file.is_file():
        try:
            return json.loads(manifest_file.read_text(encoding="utf-8")).get("version", "2.8.1")
        except Exception:
            pass
    return "2.8.1"


async def async_register_panel(hass: HomeAssistant, assets: Path) -> None:
    if not hass.data.get(f"{DOMAIN}_static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/thermo_control_static", str(assets), cache_headers=False)]
        )
        hass.data[f"{DOMAIN}_static_registered"] = True
    version = _panel_version(assets)
    for path in PANEL_PATHS:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=path,
            webcomponent_name="thermo-control-panel",
            sidebar_title=NAME if path == DOMAIN else None,
            sidebar_icon="mdi:home-thermometer-outline",
            module_url=f"/thermo_control_static/thermo-control-panel.js?v={version}",
            require_admin=True,
            config_panel_domain=DOMAIN if path == DOMAIN else None,
        )
