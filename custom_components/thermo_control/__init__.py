"""Load Thermo Control; room settings belong exclusively to the panel."""

from pathlib import Path

from homeassistant.components.frontend import async_remove_panel
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .manager import RoomManager
from .panel import PANEL_PATHS, async_register_panel
from .services import async_register_services
from .websocket import async_register_commands

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)
PLATFORMS = [Platform.CLIMATE, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the API and optionally import the old empty YAML bootstrap."""
    async_register_commands(hass)
    async_register_services(hass)
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}, data={})
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start one panel and climate platform, including old per-room entries."""
    existing: RoomManager | None = hass.data.get(DOMAIN)
    if existing is not None and not existing._closed:
        entry.runtime_data = existing
        return True

    manager = RoomManager(hass)
    await manager.async_initialize()
    await manager.async_import_legacy(hass.config_entries.async_entries(DOMAIN))
    manager.config_entry_id = entry.entry_id
    hass.data[DOMAIN] = entry.runtime_data = manager
    try:
        await async_register_panel(hass, Path(__file__).parent / "frontend")
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        await manager.async_shutdown()
        for path in PANEL_PATHS:
            async_remove_panel(hass, path)
        raise

    async def stop(_: Event) -> None:
        await manager.async_shutdown()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload listeners, virtual entities and the panel; retain room storage."""
    manager: RoomManager | None = hass.data.get(DOMAIN)
    if manager is None or manager.config_entry_id != entry.entry_id:
        return True
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await manager.async_shutdown()
    for path in PANEL_PATHS:
        async_remove_panel(hass, path)
    # Old releases created one entry per room. If the hosting entry is removed,
    # let another loaded legacy entry host the shared panel and stored rooms.
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry.entry_id and other.state is ConfigEntryState.LOADED:
            hass.async_create_task(hass.config_entries.async_reload(other.entry_id))
            break
    return True
