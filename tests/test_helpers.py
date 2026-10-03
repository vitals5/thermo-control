"""Numerical behavior including corrected telemetry and device step grids."""

import pytest

from custom_components.thermo_control.helpers import calibration_value, celsius, finite, quantize


@pytest.mark.parametrize("value", [None, "unknown", "unavailable", "nan", "inf", True])
def test_nonfinite(value):
    assert finite(value) is None


def test_units():
    assert celsius(68, "°F") == pytest.approx(20)
    assert celsius(293.15, "K") == pytest.approx(20)
    assert celsius(20, None) is None


@pytest.mark.parametrize("corrected,current,expected", [(False, 2, -3), (True, 2, -1)])
def test_calibration_baseline(corrected, current, expected):
    assert calibration_value(20, 23, current, corrected, -9, 9, 0.5) == expected


def test_calibration_clamp_and_round():
    assert calibration_value(15, 35, 0, True, -5, 5, 0.1) == -5
    assert quantize(0.3, -5, 5, 0.2) == 0.4
    assert quantize(50, -9, 9, 0.5) == 9


def test_hardware_grid_survives_custom_bounds():
    assert quantize(-8.9, -8.9, 8.9, 0.2, -10) == -8.8
    assert quantize(8.9, -8.9, 8.9, 0.2, -10) == 8.8
    with pytest.raises(ValueError):
        quantize(0, 0.1, 0.2, 0.5, 0)


def test_registry_discovery_is_unambiguous(hass, entry):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from custom_components.thermo_control.helpers import discover_related

    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("mqtt", "a")}
    )
    registry = er.async_get(hass)
    registry.async_update_entity("climate.a", device_id=device.id)
    number = registry.async_get_or_create(
        "number",
        "mqtt",
        "0xab_local_temperature_calibration_zigbee2mqtt",
        device_id=device.id,
        suggested_object_id="renamed_offset",
    )
    assert (
        discover_related(hass, "climate.a", "number", "local_temperature_calibration")
        == number.entity_id
    )
    registry.async_get_or_create(
        "number", "mqtt", "0xac_local_temperature_calibration_zigbee2mqtt", device_id=device.id
    )
    assert discover_related(hass, "climate.a", "number", "local_temperature_calibration") is None
