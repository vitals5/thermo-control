"""Serve the bundled, local-only sidebar panel through Home Assistant."""

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, NAME


async def async_register_panel(hass: HomeAssistant, assets: Path) -> None:
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig("/thermo_control_static", str(assets), cache_headers=False),
        ]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=DOMAIN,
        webcomponent_name="thermo-control-panel",
        sidebar_title=NAME,
        sidebar_icon="mdi:home-thermometer-outline",
        module_url="/thermo_control_static/thermo-control-panel.js?v=1.1.0",
        require_admin=True,
    )
