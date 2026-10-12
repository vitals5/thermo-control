"""Binary sensor entities for heat pump states, permits, demand and boost."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
            DHWBoostBinarySensor(manager),
            HeatPumpCompressorBinarySensor(manager),
            HeatPermitBinarySensor(manager),
            PVSignalBinarySensor(manager),
            HeatRequestedBinarySensor(manager),
        ]
    )


class BaseThermoControlBinarySensor(BinarySensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, manager, key, name, icon=None, device_class=None):
        self.manager = manager
        self.key = key
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_device_info = hub_device_info()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )


class DHWBoostBinarySensor(BaseThermoControlBinarySensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "dhw_boost_active",
            "Thermo Control Brauchwasser Boost Aktiv",
            icon="mdi:water-boiler",
            device_class=BinarySensorDeviceClass.RUNNING,
        )

    @property
    def is_on(self) -> bool:
        return bool(self.manager.heat_pump.runtime.get("manual_dhw_boost"))


class HeatPumpCompressorBinarySensor(BaseThermoControlBinarySensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_compressor",
            "Thermo Control Wärmepumpe Verdichter",
            icon="mdi:heat-pump",
            device_class=BinarySensorDeviceClass.RUNNING,
        )

    @property
    def is_on(self) -> bool | None:
        return self.manager.system.snapshot().get("compressor")


class HeatPermitBinarySensor(BaseThermoControlBinarySensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_heat_permit",
            "Thermo Control Wärmefreigabe",
            icon="mdi:radiator",
            device_class=BinarySensorDeviceClass.HEAT,
        )

    @property
    def is_on(self) -> bool:
        return bool(self.manager.system.snapshot().get("warm", False))


class PVSignalBinarySensor(BaseThermoControlBinarySensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_pv_signal",
            "Thermo Control Wärmepumpe PV-Signal",
            icon="mdi:solar-power",
        )

    @property
    def is_on(self) -> bool:
        status = self.manager.heat_pump.status
        return bool(status.get("heating", {}).get("pv") or status.get("dhw", {}).get("pv"))


class HeatRequestedBinarySensor(BaseThermoControlBinarySensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_requested",
            "Thermo Control Wärmeanforderung",
            icon="mdi:fire",
            device_class=BinarySensorDeviceClass.HEAT,
        )

    @property
    def is_on(self) -> bool:
        return bool(self.manager.system.snapshot().get("heat_requested", False))
