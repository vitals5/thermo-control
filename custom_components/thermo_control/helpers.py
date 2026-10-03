"""Pure calculations and capability-based entity discovery."""

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_conversion import TemperatureConverter


def finite(value: Any) -> float | None:
    """Reject unknown, unavailable, NaN, infinity and booleans."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def celsius(value: Any, unit: str | None) -> float | None:
    """Convert an absolute temperature, never a calibration offset."""
    number = finite(value)
    if number is None or unit not in (
        UnitOfTemperature.CELSIUS,
        UnitOfTemperature.FAHRENHEIT,
        UnitOfTemperature.KELVIN,
    ):
        return None
    return TemperatureConverter.convert(number, unit, UnitOfTemperature.CELSIUS)


def state_temperature(state: State | None) -> float | None:
    if state is None:
        return None
    return celsius(state.state, state.attributes.get("unit_of_measurement"))


def quantize(
    value: float, minimum: float, maximum: float, step: float, origin: float | None = None
) -> float:
    """Round to the hardware grid while respecting configured safety bounds."""
    if step <= 0 or minimum > maximum:
        raise ValueError("Invalid bounds or step")
    low, increment = Decimal(str(minimum if origin is None else origin)), Decimal(str(step))
    lower = ((Decimal(str(minimum)) - low) / increment).to_integral_value(rounding=ROUND_CEILING)
    upper = ((Decimal(str(maximum)) - low) / increment).to_integral_value(rounding=ROUND_FLOOR)
    if lower > upper:
        raise ValueError("No hardware increment fits the configured bounds")
    steps = ((Decimal(str(value)) - low) / increment).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(low + min(upper, max(lower, steps)) * increment)


def calibration_value(
    room: float,
    internal: float,
    current: float,
    corrected: bool,
    minimum: float,
    maximum: float,
    step: float,
    origin: float | None = None,
) -> float:
    """Account for firmware that already includes the active offset in telemetry."""
    delta = room - internal
    return quantize(current + delta if corrected else delta, minimum, maximum, step, origin)


def discover_related(hass: HomeAssistant, climate_id: str, domain: str, suffix: str) -> str | None:
    """Only discover unambiguous siblings on the same registered device."""
    registry = er.async_get(hass)
    climate = registry.async_get(climate_id)
    if climate is None or climate.device_id is None:
        return None
    matches = [
        entity.entity_id
        for entity in er.async_entries_for_device(registry, climate.device_id)
        if entity.domain == domain
        and entity.disabled_by is None
        and (
            entity.unique_id.endswith(suffix)
            or f"_{suffix}_" in entity.unique_id
            or entity.entity_id.endswith(suffix)
        )
    ]
    return matches[0] if len(matches) == 1 else None
