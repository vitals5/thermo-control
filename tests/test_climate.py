"""Climate services and lifecycle including restore before initial commands."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.core import State
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.thermo_control.climate import ThermoControlClimate


async def test_climate_services(coordinator):
    climate = ThermoControlClimate(coordinator)
    await climate.async_turn_on()
    assert climate.hvac_mode == HVACMode.HEAT
    await climate.async_set_temperature(temperature=21)
    assert climate.target_temperature == 21
    await climate.async_set_preset_mode("comfort")
    assert climate.preset_mode == "comfort"
    await climate.async_turn_off()
    assert climate.hvac_mode == HVACMode.OFF
    assert climate.extra_state_attributes["valve_position"] == 40
    assert climate.current_temperature == 20
    assert climate.min_temp == 5
    assert climate.max_temp == 30


@pytest.mark.parametrize("value", [None, "nan", 40, True])
async def test_invalid_temperature(coordinator, value):
    climate = ThermoControlClimate(coordinator)
    with pytest.raises(ServiceValidationError):
        await climate.async_set_temperature(temperature=value)


async def test_invalid_mode_and_preset(coordinator):
    climate = ThermoControlClimate(coordinator)
    with pytest.raises(ServiceValidationError):
        await climate.async_set_hvac_mode("cool")
    with pytest.raises(ServiceValidationError):
        await climate.async_set_preset_mode("schedule")
    with pytest.raises(ServiceValidationError):
        await climate.async_set_temperature(temperature=20, hvac_mode="cool")


async def test_real_setup_restore_and_unload(hass, entry, service_calls):
    mock_restore_cache(
        hass,
        [
            State(
                "climate.living_room",
                "off",
                {
                    "temperature": 22,
                    "temperature_unit": "°C",
                    "desired_hvac_mode": "heat",
                    "preset_mode": "none",
                    "manual_temperature": 22,
                },
            )
        ],
    )
    with (
        patch(
            "custom_components.thermo_control.coordinator.Store.async_load",
            AsyncMock(return_value={"window_blocked": True}),
        ),
        patch("custom_components.thermo_control.coordinator.Store.async_save", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert (state := hass.states.get("climate.living_room")) is not None
        assert state.attributes["temperature"] == 22
        assert state.attributes["desired_hvac_mode"] == "heat"
        coordinator = entry.runtime_data
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert hass.states.get("climate.living_room").state == "unavailable"
        assert coordinator._closed
