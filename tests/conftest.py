"""Fixtures use real HA state machines, event helpers and service registry."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermo_control.const import (
    CONF_CALIBRATION_ENTITY,
    CONF_CLOSE_DELAY,
    CONF_DEVICES,
    CONF_OPEN_DELAY,
    CONF_SENSOR,
    CONF_TRVS,
    CONF_WINDOWS,
    DOMAIN,
)
from custom_components.thermo_control.coordinator import ThermoControlCoordinator

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def custom_components_enabled(enable_custom_integrations):
    """Allow loading the custom platform."""


@pytest.fixture
def room(hass):
    """A room with two independently calibrated TRVs and one contact."""
    registry = er.async_get(hass)
    for name in ("a", "b"):
        registry.async_get_or_create("climate", "mqtt", name, suggested_object_id=name)
        hass.states.async_set(
            f"climate.{name}",
            "heat",
            {
                "temperature": 20,
                "current_temperature": 23,
                "temperature_unit": "°C",
                "hvac_modes": ["off", "heat"],
                "min_temp": 5,
                "max_temp": 30,
                "target_temp_step": 0.5,
                "preset_modes": ["manual", "schedule"],
                "preset_mode": "manual",
                "position": 20 if name == "a" else 60,
            },
        )
        hass.states.async_set(f"number.{name}_offset", 0, {"min": -5, "max": 5, "step": 0.1})
    hass.states.async_set("sensor.room", 20, {"unit_of_measurement": "°C"})
    hass.states.async_set("binary_sensor.window", "off")
    return {
        "name": "Living room",
        CONF_TRVS: ["climate.a", "climate.b"],
        CONF_SENSOR: "sensor.room",
        CONF_WINDOWS: ["binary_sensor.window"],
        CONF_OPEN_DELAY: 0,
        CONF_CLOSE_DELAY: 0,
        CONF_DEVICES: {
            f"climate.{name}": {CONF_CALIBRATION_ENTITY: f"number.{name}_offset"}
            for name in ("a", "b")
        },
    }


@pytest.fixture
def entry(hass, room):
    entry = MockConfigEntry(domain=DOMAIN, data=room, title=room["name"])
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def service_calls(hass):
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    for domain, services in {
        "climate": ("set_hvac_mode", "set_temperature", "set_preset_mode"),
        "number": ("set_value",),
        "mqtt": ("publish",),
    }.items():
        for service in services:
            hass.services.async_register(domain, service, record)
    return calls


@pytest.fixture
async def coordinator(hass, entry, service_calls):
    coordinator = ThermoControlCoordinator(hass, entry)
    with (
        patch.object(coordinator._store, "async_load", AsyncMock(return_value=None)),
        patch.object(coordinator._store, "async_save", AsyncMock()),
        patch.object(coordinator._store, "async_delay_save"),
    ):
        await coordinator.async_initialize()
        yield coordinator
        await coordinator.async_shutdown()


@pytest.fixture
async def manager(hass, hass_storage, service_calls):
    from custom_components.thermo_control.manager import RoomManager

    manager = RoomManager(hass)
    await manager.async_initialize()
    hass.data[DOMAIN] = manager
    await manager.async_bind_platform(lambda entities: None)
    yield manager
    await manager.async_shutdown()
