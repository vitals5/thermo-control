"""Button entities for manual triggers like DHW boost and valve exercise."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN


def hub_device_info() -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, "hub")},
        name="Thermo Control",
        manufacturer="Thermo Control",
        model="Central Controller",
        entry_type=DeviceEntryType.SERVICE,
    )


async def async_setup_entry(hass, entry, async_add_entities):
    manager = entry.runtime_data
    async_add_entities(
        [
            DHWBoostButton(manager),
            DHWBoostCancelButton(manager),
            ValveMaintenanceButton(manager),
        ]
    )


class DHWBoostButton(ButtonEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:water-boiler-auto"

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{DOMAIN}_dhw_boost"
        self._attr_name = "Thermo Control Brauchwasser Boost"
        self._attr_device_info = hub_device_info()

    async def async_press(self) -> None:
        await self.manager.heat_pump.async_trigger_dhw_boost(True)


class DHWBoostCancelButton(ButtonEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:water-boiler-off"

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{DOMAIN}_dhw_boost_cancel"
        self._attr_name = "Thermo Control Brauchwasser Boost beenden"
        self._attr_device_info = hub_device_info()

    async def async_press(self) -> None:
        await self.manager.heat_pump.async_trigger_dhw_boost(False)


class ValveMaintenanceButton(ButtonEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:wrench"

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{DOMAIN}_valve_maintenance_trigger"
        self._attr_name = "Thermo Control Ventilwartung starten"
        self._attr_device_info = hub_device_info()

    async def async_press(self) -> None:
        await self.manager.async_trigger_valve_maintenance()
