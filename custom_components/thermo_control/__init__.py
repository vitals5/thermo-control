"""Thermo Control config-entry lifecycle."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import ThermoControlCoordinator

type ThermoControlConfigEntry = ConfigEntry[ThermoControlCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ThermoControlConfigEntry) -> bool:
    """Create one coordinator per room; the platform starts it after restoration."""
    coordinator = ThermoControlCoordinator(hass, entry)
    await coordinator.async_initialize()
    entry.runtime_data = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.async_shutdown()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ThermoControlConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ThermoControlConfigEntry) -> bool:
    """Entity removal stops the coordinator and releases every subscription."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
