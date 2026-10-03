"""UI setup and options with explicit per-TRV calibration mapping."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_ADVANCED,
    CONF_CALIBRATION_ENTITY,
    CONF_CALIBRATION_MAX,
    CONF_CALIBRATION_MIN,
    CONF_CALIBRATION_STEP,
    CONF_CALIBRATION_TOPIC,
    CONF_CLOSE_DELAY,
    CONF_CORRECTED,
    CONF_DEVICES,
    CONF_FROST,
    CONF_INTERNAL_SENSOR,
    CONF_INTERVAL,
    CONF_OPEN_DELAY,
    CONF_POSITION_ENTITY,
    CONF_REGULATED_MODE,
    CONF_SENSOR,
    CONF_THRESHOLD,
    CONF_TOLERANCE,
    CONF_TRVS,
    CONF_WINDOWS,
    DEFAULTS,
    DEVICE_DEFAULTS,
    DOMAIN,
    PRESETS,
)
from .helpers import celsius, discover_related, state_temperature


def _entity(domain: str, multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain, multiple=multiple))


def _number(minimum: float, maximum: float, step: float, unit: str = "") -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _room_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("name", default=values.get("name", "")): selector.TextSelector(),
            vol.Required(CONF_TRVS, default=values.get(CONF_TRVS, [])): _entity("climate", True),
            vol.Required(CONF_SENSOR, default=values.get(CONF_SENSOR, "")): _entity("sensor"),
            vol.Optional(
                CONF_ADVANCED, default=values.get(CONF_ADVANCED, True)
            ): selector.BooleanSelector(),
        }
    )


def _advanced_schema(values: dict[str, Any]) -> vol.Schema:
    defaults = {**DEFAULTS, **values}
    schema: dict[Any, Any] = {
        vol.Optional(CONF_WINDOWS, default=defaults[CONF_WINDOWS]): _entity("binary_sensor", True),
        vol.Required(CONF_TOLERANCE, default=defaults[CONF_TOLERANCE]): _number(0.1, 2, 0.1, "°C"),
        vol.Required(CONF_INTERVAL, default=defaults[CONF_INTERVAL]): _number(300, 86400, 1, "s"),
        vol.Required(CONF_THRESHOLD, default=defaults[CONF_THRESHOLD]): _number(0.1, 5, 0.1, "°C"),
        vol.Required(CONF_OPEN_DELAY, default=defaults[CONF_OPEN_DELAY]): _number(0, 3600, 1, "s"),
        vol.Required(CONF_CLOSE_DELAY, default=defaults[CONF_CLOSE_DELAY]): _number(
            0, 3600, 1, "s"
        ),
        vol.Required(CONF_FROST, default=defaults[CONF_FROST]): _number(5, 15, 0.5, "°C"),
    }
    schema.update(
        {
            vol.Required(f"preset_{name}", default=defaults[f"preset_{name}"]): _number(
                5, 35, 0.5, "°C"
            )
            for name in PRESETS
        }
    )
    return vol.Schema(schema)


def _device_schema(values: dict[str, Any]) -> vol.Schema:
    defaults = {**DEVICE_DEFAULTS, **values}
    schema: dict[Any, Any] = {
        vol.Optional(
            CONF_CALIBRATION_TOPIC,
            description={"suggested_value": defaults.get(CONF_CALIBRATION_TOPIC, "")},
        ): selector.TextSelector(),
        vol.Required(CONF_CORRECTED, default=defaults[CONF_CORRECTED]): selector.BooleanSelector(),
        vol.Required(
            CONF_REGULATED_MODE, default=defaults[CONF_REGULATED_MODE]
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["heat", "auto"], mode=selector.SelectSelectorMode.DROPDOWN
            )
        ),
        vol.Required(CONF_CALIBRATION_MIN, default=defaults[CONF_CALIBRATION_MIN]): _number(
            -10, 0, 0.1, "°C"
        ),
        vol.Required(CONF_CALIBRATION_MAX, default=defaults[CONF_CALIBRATION_MAX]): _number(
            0, 10, 0.1, "°C"
        ),
        vol.Required(CONF_CALIBRATION_STEP, default=defaults[CONF_CALIBRATION_STEP]): _number(
            0.1, 1, 0.1, "°C"
        ),
    }
    for key, domain in (
        (CONF_CALIBRATION_ENTITY, "number"),
        (CONF_POSITION_ENTITY, "sensor"),
        (CONF_INTERNAL_SENSOR, "sensor"),
    ):
        field = (
            vol.Optional(key, description={"suggested_value": defaults[key]})
            if defaults.get(key)
            else vol.Optional(key)
        )
        schema[field] = _entity(domain)
    return vol.Schema(schema)


class _FlowSteps:
    """Share the entire editable configuration between setup and options."""

    _values: dict[str, Any]
    _device_index: int
    _editing_entry_id: str | None = None

    def _validate_room(self, values: dict[str, Any]) -> dict[str, str]:
        if not values["name"].strip():
            return {"name": "name_required"}
        if not values[CONF_TRVS] or len(values[CONF_TRVS]) != len(set(values[CONF_TRVS])):
            return {CONF_TRVS: "invalid_trvs"}
        registry = er.async_get(self.hass)
        for entity_id in values[CONF_TRVS]:
            entity = registry.async_get(entity_id)
            if not entity or entity.platform == DOMAIN or not self.hass.states.get(entity_id):
                return {CONF_TRVS: "invalid_trvs"}
            modes = self.hass.states.get(entity_id).attributes.get("hvac_modes", [])
            if not set(modes) & {"heat", "auto"}:
                return {CONF_TRVS: "invalid_trvs"}
        if state_temperature(self.hass.states.get(values[CONF_SENSOR])) is None:
            return {CONF_SENSOR: "invalid_sensor"}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == self._editing_entry_id:
                continue
            existing = {**entry.data, **entry.options}
            if set(values[CONF_TRVS]) & set(existing[CONF_TRVS]):
                return {CONF_TRVS: "trv_in_use"}
        return {}

    async def _room_step(self, step: str, user_input: dict[str, Any] | None) -> FlowResult:
        errors = {}
        if user_input is not None:
            errors = self._validate_room(user_input)
            if not errors:
                self._values.update(user_input)
                self._values["name"] = user_input["name"].strip()
                if user_input.get(CONF_ADVANCED):
                    return await self.async_step_advanced()
                return self._finish()
        return self.async_show_form(
            step_id=step, data_schema=_room_schema(self._values), errors=errors
        )

    async def async_step_advanced(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            for entity_id in self._values[CONF_TRVS]:
                state = self.hass.states.get(entity_id)
                if state is None:
                    continue
                unit = state.attributes.get(
                    "temperature_unit", self.hass.config.units.temperature_unit
                )
                low = celsius(state.attributes.get("min_temp", 5), unit)
                high = celsius(state.attributes.get("max_temp", 35), unit)
                for name in PRESETS:
                    if (
                        low is not None
                        and high is not None
                        and not low <= user_input[f"preset_{name}"] <= high
                    ):
                        errors[f"preset_{name}"] = "unsupported_temperature"
            if any(
                not self.hass.states.get(entity_id)
                for entity_id in user_input.get(CONF_WINDOWS, [])
            ):
                errors[CONF_WINDOWS] = "invalid_windows"
            if not errors:
                self._values.update(user_input)
                self._device_index = 0
                self._values[CONF_DEVICES] = {
                    entity_id: values
                    for entity_id, values in self._values.get(CONF_DEVICES, {}).items()
                    if entity_id in self._values[CONF_TRVS]
                }
                return await self.async_step_device()
        return self.async_show_form(
            step_id="advanced", data_schema=_advanced_schema(self._values), errors=errors
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entity_id = self._values[CONF_TRVS][self._device_index]
        values = self._values.get(CONF_DEVICES, {}).get(entity_id, {})
        values = dict(values)
        if CONF_REGULATED_MODE not in values:
            state = self.hass.states.get(entity_id)
            if state and "heat" not in state.attributes.get("hvac_modes", []):
                values[CONF_REGULATED_MODE] = "auto"
        if not values:
            for key, domain, suffix in (
                (CONF_CALIBRATION_ENTITY, "number", "local_temperature_calibration"),
                (CONF_POSITION_ENTITY, "sensor", "position"),
            ):
                if discovered := discover_related(self.hass, entity_id, domain, suffix):
                    values[key] = discovered
        errors = {}
        if user_input is not None:
            topic = user_input.get(CONF_CALIBRATION_TOPIC, "").strip()
            if user_input.get(CONF_CALIBRATION_ENTITY) and topic:
                errors["base"] = "ambiguous_calibration"
            elif topic and (
                any(token in topic for token in ("+", "#", "\x00"))
                or not topic.endswith("/set/local_temperature_calibration")
            ):
                errors[CONF_CALIBRATION_TOPIC] = "invalid_topic"
            elif user_input[CONF_CALIBRATION_MIN] >= user_input[CONF_CALIBRATION_MAX]:
                errors["base"] = "invalid_bounds"
            state = self.hass.states.get(entity_id)
            if state and user_input[CONF_REGULATED_MODE] not in state.attributes.get(
                "hvac_modes", []
            ):
                errors[CONF_REGULATED_MODE] = "unsupported_mode"
            for key, domain in (
                (CONF_CALIBRATION_ENTITY, "number"),
                (CONF_POSITION_ENTITY, "sensor"),
                (CONF_INTERNAL_SENSOR, "sensor"),
            ):
                if selected := user_input.get(key):
                    selected_state = self.hass.states.get(selected)
                    if not selected.startswith(f"{domain}.") or selected_state is None:
                        errors[key] = "invalid_entity"
                    elif key == CONF_INTERNAL_SENSOR and state_temperature(selected_state) is None:
                        errors[key] = "invalid_sensor"
            if (
                topic
                and CONF_CALIBRATION_TOPIC not in errors
                and not self.hass.services.has_service("mqtt", "publish")
            ):
                errors[CONF_CALIBRATION_TOPIC] = "mqtt_unavailable"
            if not errors:
                self._values.setdefault(CONF_DEVICES, {})[entity_id] = {
                    **user_input,
                    CONF_CALIBRATION_TOPIC: topic,
                }
                self._device_index += 1
                if self._device_index < len(self._values[CONF_TRVS]):
                    return await self.async_step_device()
                return self._finish()
        return self.async_show_form(
            step_id="device",
            data_schema=_device_schema(values),
            errors=errors,
            description_placeholders={"thermostat": entity_id},
        )

    def _finish(self) -> FlowResult:
        values = {key: value for key, value in self._values.items() if key != CONF_ADVANCED}
        return self.async_create_entry(title=values["name"], data=values)


class ThermoControlConfigFlow(_FlowSteps, config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a room without YAML."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if not hasattr(self, "_values"):
            self._values = deepcopy(DEFAULTS)
        return await self._room_step("user", user_input)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ThermoControlOptionsFlow:
        return ThermoControlOptionsFlow()


class ThermoControlOptionsFlow(_FlowSteps, config_entries.OptionsFlow):
    """Edit the room, contacts, presets and every device mapping."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if not hasattr(self, "_values"):
            self._values = deepcopy(
                {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}
            )
            self._editing_entry_id = self.config_entry.entry_id
        return await self._room_step("init", user_input)
