"""Sensors for heat pump temperatures, setpoints, aggregate demand and room statistics."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
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
    entities: list[SensorEntity] = [
        DemandSensor(manager, key, name)
        for key, name in (
            ("demand", "Thermo Control Wärmebedarf"),
            ("eligible_demand", "Thermo Control Freigegebener Wärmebedarf"),
        )
    ]
    entities.extend([PumpControlSensor(manager, channel) for channel in ("heating", "dhw")])
    entities.extend(
        [
            MeanDemandSensor(manager),
            HeatingRoomsSensor(manager),
            DemandRoomsSensor(manager),
            HeatPumpFlowSensor(manager),
            HeatPumpReturnSensor(manager),
            HeatPumpMixedFlowSensor(manager),
            HeatPumpTargetSensor(manager),
            HeatPumpDHWCurrentSensor(manager),
            HeatPumpDHWTargetSensor(manager),
        ]
    )
    async_add_entities(entities)


class PumpControlSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:heat-pump"

    def __init__(self, manager, channel):
        self.manager, self.channel = manager, channel
        self._attr_unique_id = f"{DOMAIN}_heat_pump_{channel}"
        self._attr_device_info = hub_device_info()

    @property
    def name(self):
        return (
            "Thermo Control "
            + self.manager.heat_pump.config["name"]
            + " "
            + ("Heizung" if self.channel == "heating" else "Warmwasser")
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )

    @property
    def native_value(self):
        return self.manager.heat_pump.status[self.channel]["profile"]

    @property
    def extra_state_attributes(self):
        return self.manager.heat_pump.snapshot()


class DemandSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:radiator"

    def __init__(self, manager, key, name):
        self.manager, self.key = manager, key
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = name
        self._attr_device_info = hub_device_info()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )

    @property
    def native_value(self):
        return self.manager.system.snapshot()[self.key]

    @property
    def extra_state_attributes(self):
        return self.manager.system.snapshot()


class MeanDemandSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:radiator"

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{DOMAIN}_mean_demand"
        self._attr_name = "Thermo Control Mittlerer Wärmebedarf"
        self._attr_device_info = hub_device_info()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )

    @property
    def native_value(self):
        return self.manager.system.snapshot().get("mean_demand", 0)


class HeatingRoomsSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:home-thermometer"

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{DOMAIN}_heating_rooms"
        self._attr_name = "Thermo Control Heizende Räume"
        self._attr_device_info = hub_device_info()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )

    @property
    def native_value(self):
        return self.manager.system.snapshot().get("heating_rooms", 0)


class DemandRoomsSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_icon = "mdi:home-alert"

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{DOMAIN}_demand_rooms"
        self._attr_name = "Thermo Control Räume mit Wärmebedarf"
        self._attr_device_info = hub_device_info()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )

    @property
    def native_value(self):
        return self.manager.system.snapshot().get("demand_rooms", 0)


class HeatPumpTemperatureSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, manager, key, name, snapshot_getter):
        self.manager = manager
        self.key = key
        self.snapshot_getter = snapshot_getter
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = name
        self._attr_device_info = hub_device_info()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )

    @property
    def native_value(self):
        return self.snapshot_getter(self.manager)


class HeatPumpFlowSensor(HeatPumpTemperatureSensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_flow",
            "Thermo Control Wärmepumpe Vorlauf",
            lambda m: m.heat_pump.snapshot().get("flow"),
        )


class HeatPumpReturnSensor(HeatPumpTemperatureSensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_return",
            "Thermo Control Wärmepumpe Rücklauf",
            lambda m: m.heat_pump.snapshot().get("return"),
        )


class HeatPumpMixedFlowSensor(HeatPumpTemperatureSensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_mixed_flow",
            "Thermo Control Wärmepumpe Mischkreis Vorlauf",
            lambda m: m.heat_pump.snapshot().get("mixed_flow"),
        )


class HeatPumpTargetSensor(HeatPumpTemperatureSensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_target",
            "Thermo Control Wärmepumpe Vorlauf Soll",
            lambda m: m.system.snapshot().get("target"),
        )


class HeatPumpDHWCurrentSensor(HeatPumpTemperatureSensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_dhw_temperature",
            "Thermo Control Warmwasser Ist",
            lambda m: m.heat_pump.snapshot().get("dhw_temperature"),
        )


class HeatPumpDHWTargetSensor(HeatPumpTemperatureSensor):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_dhw_target",
            "Thermo Control Warmwasser Soll",
            lambda m: m.heat_pump.snapshot().get("dhw_target"),
        )
