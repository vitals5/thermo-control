"""Load the sidebar panel; room setup happens exclusively inside the panel."""

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .manager import RoomManager
from .panel import async_register_panel
from .websocket import async_register_commands

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """A single empty YAML key starts Thermo Control without a config flow."""
    manager = RoomManager(hass)
    await manager.async_initialize()
    await manager.async_import_legacy(hass.config_entries.async_entries(DOMAIN))
    hass.data[DOMAIN] = manager
    async_register_commands(hass)
    await async_register_panel(hass, Path(__file__).parent / "frontend")
    await async_load_platform(hass, "climate", DOMAIN, {}, config)

    async def stop(_: Event) -> None:
        await manager.async_shutdown()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Compatibility for already existing 1.0 entries; the panel owns their rooms."""
    entry.runtime_data = hass.data[DOMAIN]
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Legacy entry removal does not remove a migrated panel configuration."""
    return True
