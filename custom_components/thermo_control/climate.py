"""A room climate entity with persisted intent and an optional external sensor."""

from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData, RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SENSOR, CONF_TRVS, PRESETS
from .coordinator import ThermoControlCoordinator
from .helpers import celsius, finite

if TYPE_CHECKING:
    from .manager import RoomManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    await entry.runtime_data.async_bind_platform(async_add_entities)


class ThermoControlClimate(
    CoordinatorEntity[ThermoControlCoordinator], ClimateEntity, RestoreEntity
):
    """Virtual climate; service methods update intent even during an open window."""

    _attr_has_entity_name = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = list(PRESETS)
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        coordinator: ThermoControlCoordinator,
        *,
        manager: RoomManager | None = None,
        restore: bool = True,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.entry.entry_id
        self._attr_name = coordinator.config["name"]
        self._manager = manager
        self._restore = restore

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        attributes = {}
        if self._restore:
            if state := await self.async_get_last_state():
                attributes = {"desired_hvac_mode": state.state, **state.attributes}
            # HA strips climate attributes when an entity is unavailable. Extra
            # restore data remains independent of availability and display units.
            if extra := await self.async_get_last_extra_data():
                attributes.update(extra.as_dict())
        if attributes:
            mode = attributes.get("desired_hvac_mode")
            if mode in (HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO):
                self.coordinator.mode = HVACMode(mode)
            low, high = self.coordinator.base_temperature_limits()
            target = finite(attributes.get("target_temperature_celsius"))
            if target is None:
                target = celsius(
                    attributes.get(ATTR_TEMPERATURE), self.hass.config.units.temperature_unit
                )
            if target is not None and low <= target <= high:
                self.coordinator.target = target
            if (
                manual := finite(attributes.get("manual_temperature"))
            ) is not None and low <= manual <= high:
                self.coordinator.manual_target = manual
            if attributes.get("preset_mode") in self.preset_modes:
                self.coordinator.preset = attributes["preset_mode"]
        await self.coordinator.async_start()
        if self._manager is not None:
            self._manager.notify()

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        """Preserve room intent even when sensors or thermostats are offline."""
        return RestoredExtraData(
            {
                "desired_hvac_mode": self.coordinator.mode,
                "target_temperature_celsius": self.coordinator.target,
                "manual_temperature": self.coordinator.manual_target,
                "preset_mode": self.coordinator.preset,
            }
        )

    async def async_will_remove_from_hass(self) -> None:
        await self.coordinator.async_shutdown()
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data["available"])

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.get("temperature")

    @property
    def target_temperature(self) -> float:
        return self.coordinator.data.get("target", self.coordinator.effective_target)

    @property
    def preset_modes(self) -> list[str]:
        return [*PRESETS, "schedule"] if self._manager else list(PRESETS)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return [
            mode
            for mode in (HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO)
            if self.coordinator.supports_mode(mode)
        ]

    @property
    def min_temp(self) -> float:
        return self.coordinator.temperature_limits()[0]

    @property
    def max_temp(self) -> float:
        return self.coordinator.temperature_limits()[1]

    @property
    def hvac_mode(self) -> HVACMode:
        return self.coordinator.data["mode"]

    @property
    def hvac_action(self) -> HVACAction | None:
        return self.coordinator.data["action"]

    @property
    def preset_mode(self) -> str:
        return self.coordinator.preset

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.coordinator.schedule_state,
            "desired_hvac_mode": self.coordinator.mode,
            "manual_temperature": self.coordinator.manual_target,
            "target_temperature_celsius": self.coordinator.target,
            "base_target_temperature": self.coordinator.target,
            "current_temperature_celsius": self.coordinator.data["temperature"],
            "effective_target_temperature": self.target_temperature,
            "native_auto": self.coordinator.native_auto,
            "auto_devices": self.coordinator.auto_devices,
            "heating_type": self.coordinator.config["heating_type"],
            "floor": self.coordinator.config["floor"],
            "group_id": self.coordinator.config["group_id"],
            **{
                key: self.coordinator.data.get(key)
                for key in (
                    "heat_demand",
                    "heat_permitted",
                    "interlock_reason",
                    "temperature_rate",
                    "predicted_temperature",
                    "pre_shutoff",
                    "pwm_active",
                    "duty_cycle",
                )
            },
            "window_open": self.coordinator.window_blocked,
            "window_pending": self.coordinator._window_pending,
            "valve_position": self.coordinator.data["position"],
            "temperature_sensor": self.coordinator.config[CONF_SENSOR],
            "temperature_source": (
                "external_sensor" if self.coordinator.config[CONF_SENSOR] else "thermostats"
            ),
            "thermostats": self.coordinator.config[CONF_TRVS],
            "device_status": self.coordinator.data["devices"],
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self.hvac_modes:
            raise ServiceValidationError(
                "Dieser Modus wird nicht von allen Thermostaten unterstützt."
            )
        await self.coordinator.async_set_intent(mode=HVACMode(hvac_mode))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = finite(kwargs.get(ATTR_TEMPERATURE))
        if temperature is None or not self.min_temp <= temperature <= self.max_temp:
            raise ServiceValidationError("Target temperature is outside the room's supported range")
        mode = kwargs.get("hvac_mode")
        if mode is not None and mode not in self.hvac_modes:
            raise ServiceValidationError(
                "Dieser Modus wird nicht von allen Thermostaten unterstützt."
            )
        if self.coordinator.native_auto and mode not in (HVACMode.HEAT, HVACMode.OFF):
            raise ServiceValidationError(
                "Im Auto-Modus regelt das Gerät. Für Sollwerte zuerst Heizen wählen."
            )
        offset = self._manager.settings["master_offset"] if self._manager else 0
        await self.coordinator.async_set_intent(
            temperature=temperature - offset, mode=HVACMode(mode) if mode is not None else None
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == "schedule" and self._manager:
            await self._manager.schedules.async_room_active(self.coordinator.entry.entry_id, True)
            await self.coordinator.async_set_intent(mode=HVACMode.HEAT)
            return
        if self.coordinator.native_auto:
            raise ServiceValidationError(
                "Im Auto-Modus verwendet das Thermostat seinen eigenen Zeitplan."
            )
        if preset_mode not in PRESETS:
            raise ServiceValidationError("Unsupported preset")
        value = (
            self.coordinator.manual_target
            if preset_mode == "none"
            else self.coordinator.config[f"preset_{preset_mode}"]
        )
        low, high = (
            self.coordinator.base_temperature_limits()
            if preset_mode == "none"
            else (self.min_temp, self.max_temp)
        )
        if not low <= value <= high:
            raise ServiceValidationError("Preset temperature is outside the room's supported range")
        await self.coordinator.async_set_intent(preset=preset_mode)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
