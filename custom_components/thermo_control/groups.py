"""Virtual group climates share intent and report actual member activity."""

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import PRESETS
from .manager import SIGNAL_ROOMS


class ThermoControlGroup(ClimateEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [*PRESETS, "schedule"]
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, manager, group_id, name) -> None:
        self.manager, self.group_id = manager, group_id
        self._attr_unique_id = f"group_{group_id}"
        self._attr_name = name

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )
        self.manager.notify()

    @property
    def members(self):
        return [
            entity
            for room_id, entity in self.manager.entities.items()
            if self.manager.rooms[room_id]["group_id"] == self.group_id
        ]

    @property
    def available(self):
        return any(member.available for member in self.members)

    def _mean(self, key):
        values = [
            getattr(member, key)
            for member in self.members
            if member.available and getattr(member, key) is not None
        ]
        return sum(values) / len(values) if values else None

    @property
    def current_temperature(self):
        return self._mean("current_temperature")

    @property
    def target_temperature(self):
        return self._mean("target_temperature")

    @property
    def min_temp(self):
        return max((member.min_temp for member in self.members), default=5)

    @property
    def max_temp(self):
        return min((member.max_temp for member in self.members), default=35)

    @property
    def hvac_modes(self):
        members = self.members
        return [
            mode
            for mode in (HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO)
            if all(mode in member.hvac_modes for member in members)
        ]

    @property
    def hvac_mode(self):
        modes = {member.hvac_mode for member in self.members}
        return next(
            (mode for mode in (HVACMode.HEAT, HVACMode.AUTO) if mode in modes), HVACMode.OFF
        )

    @property
    def hvac_action(self):
        actions = [member.hvac_action for member in self.members]
        return next((action for action in ("heating", "idle", "off") if action in actions), None)

    @property
    def preset_mode(self):
        presets = {member.preset_mode for member in self.members}
        return next(iter(presets)) if len(presets) == 1 else "none"

    @property
    def extra_state_attributes(self):
        return {
            "current_temperature_celsius": self.current_temperature,
            "effective_target_temperature": self.target_temperature,
            "group_id": self.group_id,
            "rooms": [member.entity_id for member in self.members],
            "auto_rooms": [
                member.entity_id for member in self.members if member.coordinator.native_auto
            ],
            "heat_demand": max(
                (member.coordinator.heat_demand for member in self.members), default=0
            ),
            "mixed_targets": len({member.target_temperature for member in self.members}) > 1,
        }

    async def async_set_temperature(self, **kwargs):
        # Validate the common range before touching any member.
        from homeassistant.exceptions import ServiceValidationError

        from .helpers import finite

        value = finite(kwargs.get("temperature"))
        if value is None or not self.min_temp <= value <= self.max_temp:
            raise ServiceValidationError("Sollwert liegt außerhalb der gemeinsamen Gruppengrenzen.")
        mode = kwargs.get("hvac_mode")
        if mode is not None and mode not in self.hvac_modes:
            raise ServiceValidationError(
                "Modus wird nicht von allen Gruppenmitgliedern unterstützt."
            )
        if any(member.coordinator.native_auto for member in self.members) and mode not in (
            HVACMode.HEAT,
            HVACMode.OFF,
        ):
            raise ServiceValidationError(
                "Für Gruppensollwerte zuerst alle Räume auf Heizen stellen."
            )
        for member in self.members:
            await member.async_set_temperature(**kwargs)

    async def async_set_hvac_mode(self, hvac_mode):
        from homeassistant.exceptions import ServiceValidationError

        if hvac_mode not in self.hvac_modes:
            raise ServiceValidationError(
                "Modus wird nicht von allen Gruppenmitgliedern unterstützt."
            )
        for member in self.members:
            await member.async_set_hvac_mode(hvac_mode)

    async def async_set_preset_mode(self, preset_mode):
        from homeassistant.exceptions import ServiceValidationError

        if preset_mode == "schedule":
            if any(
                not self.manager.schedules.plan_for(member.coordinator.entry.entry_id)
                or not member.coordinator.supports_mode("heat")
                for member in self.members
            ):
                raise ServiceValidationError("Zuerst einen Zeitplan für alle Gruppenräume anlegen.")
            for member in self.members:
                await member.async_set_preset_mode(preset_mode)
            return
        if any(member.coordinator.native_auto for member in self.members):
            raise ServiceValidationError("Im Auto-Modus gilt der geräteeigene Zeitplan.")
        if preset_mode not in PRESETS or any(
            not (member.min_temp - 5 if preset_mode == "none" else member.min_temp)
            <= (
                member.coordinator.manual_target
                if preset_mode == "none"
                else member.coordinator.config[f"preset_{preset_mode}"]
            )
            <= (member.max_temp + 5 if preset_mode == "none" else member.max_temp)
            for member in self.members
        ):
            raise ServiceValidationError(
                "Preset wird nicht von allen Gruppenmitgliedern unterstützt."
            )
        for member in self.members:
            await member.async_set_preset_mode(preset_mode)
