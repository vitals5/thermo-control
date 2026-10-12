"""Switch entities for activating integration channels and features."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .manager import SIGNAL_ROOMS


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
            HeatPumpMasterSwitch(manager),
            HeatPumpHeatingSwitch(manager),
            HeatPumpDHWSwitch(manager),
            HeatPumpInterlockSwitch(manager),
            ValveMaintenanceSwitch(manager),
        ]
    )


class BaseThermoControlSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, manager, key, name, icon):
        self.manager = manager
        self.key = key
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = hub_device_info()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )


class HeatPumpMasterSwitch(BaseThermoControlSwitch):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_master_enabled",
            "Thermo Control Wärmepumpensteuerung",
            "mdi:heat-pump-outline",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.manager.settings["heat_pump_control"]["enabled"])

    async def async_turn_on(self, **kwargs: Any) -> None:
        def enable(settings):
            settings["heat_pump_control"]["enabled"] = True

        await self.manager.async_update_setting(enable)

    async def async_turn_off(self, **kwargs: Any) -> None:
        def disable(settings):
            settings["heat_pump_control"]["enabled"] = False

        await self.manager.async_update_setting(disable)


class HeatPumpHeatingSwitch(BaseThermoControlSwitch):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_heating_enabled",
            "Thermo Control Wärmepumpe Heizung",
            "mdi:radiator",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.manager.settings["heat_pump_control"]["heating"]["enabled"])

    async def async_turn_on(self, **kwargs: Any) -> None:
        def enable(settings):
            settings["heat_pump_control"]["heating"]["enabled"] = True

        await self.manager.async_update_setting(enable)

    async def async_turn_off(self, **kwargs: Any) -> None:
        def disable(settings):
            settings["heat_pump_control"]["heating"]["enabled"] = False

        await self.manager.async_update_setting(disable)


class HeatPumpDHWSwitch(BaseThermoControlSwitch):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_dhw_enabled",
            "Thermo Control Wärmepumpe Warmwasser",
            "mdi:water-boiler",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.manager.settings["heat_pump_control"]["dhw"]["enabled"])

    async def async_turn_on(self, **kwargs: Any) -> None:
        def enable(settings):
            settings["heat_pump_control"]["dhw"]["enabled"] = True

        await self.manager.async_update_setting(enable)

    async def async_turn_off(self, **kwargs: Any) -> None:
        def disable(settings):
            settings["heat_pump_control"]["dhw"]["enabled"] = False

        await self.manager.async_update_setting(disable)


class HeatPumpInterlockSwitch(BaseThermoControlSwitch):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_interlock",
            "Thermo Control Wärmepumpen-Freigabe (Interlock)",
            "mdi:lock-check",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.manager.settings["heat_pump"]["interlock"])

    async def async_turn_on(self, **kwargs: Any) -> None:
        def enable(settings):
            settings["heat_pump"]["interlock"] = True

        await self.manager.async_update_setting(enable)

    async def async_turn_off(self, **kwargs: Any) -> None:
        def disable(settings):
            settings["heat_pump"]["interlock"] = False

        await self.manager.async_update_setting(disable)


class ValveMaintenanceSwitch(BaseThermoControlSwitch):
    def __init__(self, manager):
        super().__init__(
            manager,
            "valve_maintenance_enabled",
            "Thermo Control Ventilwartung",
            "mdi:valve",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.manager.settings["valve_maintenance"]["enabled"])

    async def async_turn_on(self, **kwargs: Any) -> None:
        def enable(settings):
            settings["valve_maintenance"]["enabled"] = True

        await self.manager.async_update_setting(enable)

    async def async_turn_off(self, **kwargs: Any) -> None:
        def disable(settings):
            settings["valve_maintenance"]["enabled"] = False

        await self.manager.async_update_setting(disable)
