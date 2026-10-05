"""Serve the bundled, local-only sidebar panel through Home Assistant."""

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, NAME

PANEL_PATHS = (DOMAIN, "thermo-control")


async def async_register_panel(hass: HomeAssistant, assets: Path) -> None:
    if not hass.data.get(f"{DOMAIN}_static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/thermo_control_static", str(assets), cache_headers=False)]
        )
        hass.data[f"{DOMAIN}_static_registered"] = True
    for path in PANEL_PATHS:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=path,
            webcomponent_name="thermo-control-panel",
            sidebar_title=NAME if path == DOMAIN else None,
            sidebar_icon="mdi:home-thermometer-outline",
            module_url="/thermo_control_static/thermo-control-panel.js?v=2.1.3",
            require_admin=True,
            config_panel_domain=DOMAIN if path == DOMAIN else None,
        )
