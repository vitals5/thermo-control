"""Number entities for master setpoint shift, DHW profiles and heating curve settings."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity
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
    async_add_entities(
        [
            MasterOffsetNumber(manager),
            DHWStandardSetpointNumber(manager),
            DHWBoostSetpointNumber(manager),
            DHWBlockedSetpointNumber(manager),
            HeatingCurveEndNumber(manager),
            HeatingCurveShiftNumber(manager),
            HeatingCurveCorrectionNumber(manager),
            HeatPumpDemandTargetPositionNumber(manager),
            HeatPumpDemandMinCorrectionNumber(manager),
            HeatPumpDemandMaxCorrectionNumber(manager),
        ]
    )


class BaseThermoControlNumber(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5

    def __init__(self, manager, key, name, icon, min_val, max_val):
        self.manager = manager
        self.key = key
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_device_info = hub_device_info()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )


class MasterOffsetNumber(BaseThermoControlNumber):
    def __init__(self, manager):
        super().__init__(
            manager,
            "master_offset",
            "Thermo Control Master-Sollwertverschiebung",
            "mdi:thermometer-lines",
            -5.0,
            5.0,
        )

    @property
    def native_value(self) -> float:
        return float(self.manager.settings.get("master_offset", 0.0))

    async def async_set_native_value(self, value: float) -> None:
        await self.manager.async_set_master_offset(value)


class DHWStandardSetpointNumber(BaseThermoControlNumber):
    def __init__(self, manager):
        super().__init__(
            manager,
            "dhw_setpoint_standard",
            "Thermo Control Warmwasser Sollwert Standard",
            "mdi:water-thermometer-outline",
            10.0,
            65.0,
        )

    @property
    def native_value(self) -> float:
        return float(self.manager.settings["heat_pump_control"]["dhw"]["profiles"]["standard"])

    async def async_set_native_value(self, value: float) -> None:
        def update(settings):
            settings["heat_pump_control"]["dhw"]["profiles"]["standard"] = value

        await self.manager.async_update_setting(update)


class DHWBoostSetpointNumber(BaseThermoControlNumber):
    def __init__(self, manager):
        super().__init__(
            manager,
            "dhw_setpoint_boost",
            "Thermo Control Warmwasser Sollwert Boost",
            "mdi:water-boiler-auto",
            10.0,
            65.0,
        )

    @property
    def native_value(self) -> float:
        return float(self.manager.settings["heat_pump_control"]["dhw"]["profiles"]["boost"])

    async def async_set_native_value(self, value: float) -> None:
        def update(settings):
            settings["heat_pump_control"]["dhw"]["profiles"]["boost"] = value

        await self.manager.async_update_setting(update)


class DHWBlockedSetpointNumber(BaseThermoControlNumber):
    def __init__(self, manager):
        super().__init__(
            manager,
            "dhw_setpoint_blocked",
            "Thermo Control Warmwasser Sollwert Sperre",
            "mdi:water-off-outline",
            10.0,
            65.0,
        )

    @property
    def native_value(self) -> float:
        return float(self.manager.settings["heat_pump_control"]["dhw"]["profiles"]["blocked"])

    async def async_set_native_value(self, value: float) -> None:
        def update(settings):
            settings["heat_pump_control"]["dhw"]["profiles"]["blocked"] = value

        await self.manager.async_update_setting(update)


class HeatingCurveEndNumber(BaseThermoControlNumber):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heating_end_standard",
            "Thermo Control Heizkurve Endpunkt Standard",
            "mdi:chart-bell-curve",
            10.0,
            60.0,
        )

    @property
    def native_value(self) -> float:
        return float(
            self.manager.settings["heat_pump_control"]["heating"]["profiles"]["standard"]["end"]
        )

    async def async_set_native_value(self, value: float) -> None:
        def update(settings):
            settings["heat_pump_control"]["heating"]["profiles"]["standard"]["end"] = value

        await self.manager.async_update_setting(update)


class HeatingCurveShiftNumber(BaseThermoControlNumber):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heating_shift_standard",
            "Thermo Control Heizkurve Parallelverschiebung Standard",
            "mdi:chart-line",
            5.0,
            35.0,
        )

    @property
    def native_value(self) -> float:
        return float(
            self.manager.settings["heat_pump_control"]["heating"]["profiles"]["standard"]["shift"]
        )

    async def async_set_native_value(self, value: float) -> None:
        def update(settings):
            settings["heat_pump_control"]["heating"]["profiles"]["standard"]["shift"] = value

        await self.manager.async_update_setting(update)


class HeatingCurveCorrectionNumber(BaseThermoControlNumber):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heating_correction_standard",
            "Thermo Control Heizkurve Korrektur Standard",
            "mdi:tune-vertical",
            -5.0,
            5.0,
        )

    @property
    def native_value(self) -> float:
        return float(
            self.manager.settings["heat_pump_control"]["heating"]["profiles"]["standard"][
                "correction"
            ]
        )

    async def async_set_native_value(self, value: float) -> None:
        def update(settings):
            settings["heat_pump_control"]["heating"]["profiles"]["standard"]["correction"] = value

        await self.manager.async_update_setting(update)


class HeatPumpDemandTargetPositionNumber(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_native_unit_of_measurement = "%"
    _attr_native_step = 1.0
    _attr_native_min_value = 10.0
    _attr_native_max_value = 90.0
    _attr_icon = "mdi:valve"

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{DOMAIN}_heat_pump_demand_target_position"
        self._attr_name = "Thermo Control Wärmepumpe Bedarfs-Zielventilöffnung"
        self._attr_device_info = hub_device_info()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )

    @property
    def native_value(self) -> float:
        return float(
            self.manager.settings["heat_pump_control"]["heating"]
            .get("demand_regulation", {})
            .get("target_position", 55.0)
        )

    async def async_set_native_value(self, value: float) -> None:
        def set_val(settings):
            settings["heat_pump_control"]["heating"].setdefault("demand_regulation", {})[
                "target_position"
            ] = value

        await self.manager.async_update_setting(set_val)


class HeatPumpDemandMinCorrectionNumber(BaseThermoControlNumber):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_demand_min_correction",
            "Thermo Control Wärmepumpe Bedarfs-Min-Korrektur",
            "mdi:thermometer-minus",
            -5.0,
            0.0,
        )

    @property
    def native_value(self) -> float:
        return float(
            self.manager.settings["heat_pump_control"]["heating"]
            .get("demand_regulation", {})
            .get("min_correction", -3.0)
        )

    async def async_set_native_value(self, value: float) -> None:
        def set_val(settings):
            settings["heat_pump_control"]["heating"].setdefault("demand_regulation", {})[
                "min_correction"
            ] = value

        await self.manager.async_update_setting(set_val)


class HeatPumpDemandMaxCorrectionNumber(BaseThermoControlNumber):
    def __init__(self, manager):
        super().__init__(
            manager,
            "heat_pump_demand_max_correction",
            "Thermo Control Wärmepumpe Bedarfs-Max-Korrektur",
            "mdi:thermometer-plus",
            0.0,
            5.0,
        )

    @property
    def native_value(self) -> float:
        return float(
            self.manager.settings["heat_pump_control"]["heating"]
            .get("demand_regulation", {})
            .get("max_correction", 2.0)
        )

    async def async_set_native_value(self, value: float) -> None:
        def set_val(settings):
            settings["heat_pump_control"]["heating"].setdefault("demand_regulation", {})[
                "max_correction"
            ] = value

        await self.manager.async_update_setting(set_val)
