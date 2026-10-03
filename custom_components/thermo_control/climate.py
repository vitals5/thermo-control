"""A room climate entity with persisted intent and external temperature."""

from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SENSOR, CONF_TRVS, DOMAIN, PRESETS
from .coordinator import ThermoControlCoordinator
from .helpers import celsius, finite

if TYPE_CHECKING:
    from .manager import RoomManager


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    await hass.data[DOMAIN].async_bind_platform(async_add_entities)


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
        if self._restore and (state := await self.async_get_last_state()):
            mode = state.attributes.get("desired_hvac_mode", state.state)
            if mode in self.hvac_modes:
                self.coordinator.mode = HVACMode(mode)
            low, high = self.coordinator.temperature_limits()
            target = finite(state.attributes.get("target_temperature_celsius"))
            if target is None:
                target = celsius(
                    state.attributes.get(ATTR_TEMPERATURE), self.hass.config.units.temperature_unit
                )
            if target is not None and low <= target <= high:
                self.coordinator.target = target
            if (
                manual := finite(state.attributes.get("manual_temperature"))
            ) is not None and low <= manual <= high:
                self.coordinator.manual_target = manual
            if state.attributes.get("preset_mode") in PRESETS:
                self.coordinator.preset = state.attributes["preset_mode"]
        await self.coordinator.async_start()
        if self._manager is not None:
            self._manager.notify()

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
        return self.coordinator.target

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
    def hvac_action(self) -> HVACAction:
        return self.coordinator.data["action"]

    @property
    def preset_mode(self) -> str:
        return self.coordinator.preset

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "desired_hvac_mode": self.coordinator.mode,
            "manual_temperature": self.coordinator.manual_target,
            "target_temperature_celsius": self.coordinator.target,
            "window_open": self.coordinator.window_blocked,
            "window_pending": self.coordinator._window_pending,
            "valve_position": self.coordinator.data["position"],
            "temperature_sensor": self.coordinator.config[CONF_SENSOR],
            "thermostats": self.coordinator.config[CONF_TRVS],
            "device_status": self.coordinator.data["devices"],
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self.hvac_modes:
            raise ServiceValidationError("Only off and heat are supported")
        await self.coordinator.async_set_intent(mode=HVACMode(hvac_mode))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = finite(kwargs.get(ATTR_TEMPERATURE))
        if temperature is None or not self.min_temp <= temperature <= self.max_temp:
            raise ServiceValidationError("Target temperature is outside the room's supported range")
        mode = kwargs.get("hvac_mode")
        if mode is not None and mode not in self.hvac_modes:
            raise ServiceValidationError("Only off and heat are supported")
        await self.coordinator.async_set_intent(
            temperature=temperature, mode=HVACMode(mode) if mode is not None else None
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in PRESETS:
            raise ServiceValidationError("Unsupported preset")
        value = (
            self.coordinator.manual_target
            if preset_mode == "none"
            else self.coordinator.config[f"preset_{preset_mode}"]
        )
        if not self.min_temp <= value <= self.max_temp:
            raise ServiceValidationError("Preset temperature is outside the room's supported range")
        await self.coordinator.async_set_intent(preset=preset_mode)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
