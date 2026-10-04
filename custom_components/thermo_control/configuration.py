"""Shared validation for configurations submitted by the sidebar panel."""

from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
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
from .helpers import celsius, finite


def _range(low: float, high: float):
    def number(value):
        if (result := finite(value)) is None:
            raise vol.Invalid("Eine endliche Zahl ist erforderlich")
        return result

    return vol.All(number, vol.Range(min=low, max=high))


DEVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CALIBRATION_ENTITY): cv.entity_id,
        vol.Optional(CONF_POSITION_ENTITY): cv.entity_id,
        vol.Optional(CONF_INTERNAL_SENSOR): cv.entity_id,
        vol.Optional(CONF_CALIBRATION_TOPIC, default=""): str,
        vol.Optional(CONF_CORRECTED, default=True): bool,
        vol.Optional(CONF_REGULATED_MODE): vol.In(("heat", "auto")),
        vol.Optional(CONF_CALIBRATION_MIN, default=-9): _range(-10, 0),
        vol.Optional(CONF_CALIBRATION_MAX, default=9): _range(0, 10),
        vol.Optional(CONF_CALIBRATION_STEP, default=0.5): _range(0.1, 1),
    }
)
ROOM_SCHEMA = vol.Schema(
    {
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=100)),
        vol.Required(CONF_TRVS): vol.All([cv.entity_id], vol.Length(min=1, max=32)),
        vol.Optional(CONF_SENSOR, default=None): vol.Any(None, "", cv.entity_id),
        vol.Optional(CONF_WINDOWS, default=list): [cv.entity_id],
        vol.Optional(CONF_DEVICES, default=dict): {cv.entity_id: DEVICE_SCHEMA},
        vol.Optional(CONF_INTERVAL, default=DEFAULTS[CONF_INTERVAL]): _range(300, 86400),
        vol.Optional(CONF_THRESHOLD, default=DEFAULTS[CONF_THRESHOLD]): _range(0.1, 5),
        vol.Optional(CONF_OPEN_DELAY, default=DEFAULTS[CONF_OPEN_DELAY]): _range(0, 3600),
        vol.Optional(CONF_CLOSE_DELAY, default=DEFAULTS[CONF_CLOSE_DELAY]): _range(0, 3600),
        vol.Optional(CONF_TOLERANCE, default=DEFAULTS[CONF_TOLERANCE]): _range(0.1, 2),
        vol.Optional(CONF_FROST, default=DEFAULTS[CONF_FROST]): _range(5, 15),
        **{
            vol.Optional(f"preset_{name}", default=DEFAULTS[f"preset_{name}"]): _range(5, 35)
            for name in PRESETS
        },
    }
)


def validate_room(
    hass: HomeAssistant,
    config: dict[str, Any],
    rooms: dict[str, dict[str, Any]],
    room_id: str | None = None,
    *,
    check_entities: bool = True,
) -> dict[str, Any]:
    """Reject invalid data and conflicting assignments before changing runtime."""
    try:
        result = ROOM_SCHEMA(deepcopy(config))
    except vol.Invalid as err:
        raise ServiceValidationError(f"Ungültige Raumkonfiguration: {err}") from err
    result["name"] = result["name"].strip()
    trvs = result[CONF_TRVS]
    if not result["name"] or len(trvs) != len(set(trvs)):
        raise ServiceValidationError("Raumname und unterschiedliche Thermostate sind erforderlich.")
    for other_id, other in rooms.items():
        if other_id != room_id and set(trvs) & set(other[CONF_TRVS]):
            raise ServiceValidationError(
                "Ein Thermostat ist bereits einem anderen Raum zugeordnet."
            )
    if not set(result[CONF_DEVICES]) <= set(trvs):
        raise ServiceValidationError(
            "Gerätezuordnungen müssen zu den Thermostaten dieses Raums gehören."
        )
    registry = er.async_get(hass)

    def require_entity(entity_id: str, domain: str) -> None:
        if not entity_id.startswith(f"{domain}.") or (
            check_entities and not hass.states.get(entity_id)
        ):
            raise ServiceValidationError(
                f"Entität {entity_id} muss eine vorhandene {domain}-Entität sein."
            )

    result[CONF_SENSOR] = result[CONF_SENSOR] or None
    if result[CONF_SENSOR]:
        require_entity(result[CONF_SENSOR], "sensor")
    if check_entities and result[CONF_SENSOR]:
        state = hass.states.get(result[CONF_SENSOR])
        unit = state.attributes.get("unit_of_measurement")
        # Offline sensors remain editable; never require a current measurement.
        if unit not in ("°C", "°F", "K"):
            raise ServiceValidationError(
                "Der Raumtemperatursensor benötigt eine Temperatureinheit."
            )
    for contact in result[CONF_WINDOWS]:
        require_entity(contact, "binary_sensor")
    for entity_id in trvs:
        require_entity(entity_id, "climate")
        registered = registry.async_get(entity_id)
        if check_entities and (registered is None or registered.platform == DOMAIN):
            raise ServiceValidationError("Bitte registrierte physische Thermostate auswählen.")
        state = hass.states.get(entity_id) if check_entities else None
        device = result[CONF_DEVICES].setdefault(entity_id, deepcopy(DEVICE_DEFAULTS))
        if CONF_REGULATED_MODE not in device:
            modes = state.attributes.get("hvac_modes", []) if state else []
            device[CONF_REGULATED_MODE] = (
                "auto" if "auto" in modes and "heat" not in modes else "heat"
            )
        if (
            state
            and (modes := state.attributes.get("hvac_modes"))
            and device[CONF_REGULATED_MODE] not in modes
        ):
            raise ServiceValidationError(
                f"{entity_id} unterstützt den gewählten Regelungsmodus nicht."
            )
        if state:
            unit = state.attributes.get("temperature_unit", hass.config.units.temperature_unit)
            low, high = (
                celsius(state.attributes.get(key), unit) for key in ("min_temp", "max_temp")
            )
            if low is not None and high is not None:
                for preset in PRESETS:
                    if not low <= result[f"preset_{preset}"] <= high:
                        raise ServiceValidationError(
                            f"Sollwert für {preset} liegt außerhalb der Grenzen von {entity_id}."
                        )
        if device[CONF_CALIBRATION_MIN] >= device[CONF_CALIBRATION_MAX]:
            raise ServiceValidationError(
                "Der minimale Kalibrierungsoffset muss kleiner als der maximale sein."
            )
        for key, domain in (
            (CONF_CALIBRATION_ENTITY, "number"),
            (CONF_INTERNAL_SENSOR, "sensor"),
            (CONF_POSITION_ENTITY, "sensor"),
        ):
            if selected := device.get(key):
                require_entity(selected, domain)
                if check_entities and key == CONF_INTERNAL_SENSOR:
                    sensor = hass.states.get(selected)
                    if sensor.attributes.get("unit_of_measurement") not in ("°C", "°F", "K"):
                        raise ServiceValidationError(
                            "Der interne Sensor benötigt eine Temperatureinheit."
                        )
        topic = device[CONF_CALIBRATION_TOPIC] = device.get(CONF_CALIBRATION_TOPIC, "").strip()
        if topic and device.get(CONF_CALIBRATION_ENTITY):
            raise ServiceValidationError(
                "Entweder eine Kalibrierungs-Number-Entität oder ein MQTT-Topic auswählen."
            )
        if topic and (
            any(token in topic for token in ("+", "#", "\x00"))
            or not topic.endswith("/set/local_temperature_calibration")
        ):
            raise ServiceValidationError("Ungültiges MQTT-Kalibrierungstopic.")
        if topic and check_entities and not hass.services.has_service("mqtt", "publish"):
            raise ServiceValidationError("Die MQTT-Integration muss zuerst eingerichtet werden.")
    return result
