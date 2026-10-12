"""Automation access to the reversible master setpoint shift."""

import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN


def async_register_services(hass):
    def get_manager():
        manager = hass.data.get(DOMAIN)
        if manager is None or manager._closed:
            raise ServiceValidationError("Thermo Control ist noch nicht bereit.")
        return manager

    async def set_master(call):
        await get_manager().async_set_master_offset(call.data["offset"])

    async def trigger_dhw_boost(call):
        await get_manager().heat_pump.async_trigger_dhw_boost(True)

    async def cancel_dhw_boost(call):
        await get_manager().heat_pump.async_trigger_dhw_boost(False)

    async def trigger_valve_maintenance(call):
        await get_manager().async_trigger_valve_maintenance()

    async_register_admin_service(
        hass,
        DOMAIN,
        "set_master_offset",
        set_master,
        schema=vol.Schema({vol.Required("offset"): vol.Coerce(float)}),
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        "trigger_dhw_boost",
        trigger_dhw_boost,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        "cancel_dhw_boost",
        cancel_dhw_boost,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        "trigger_valve_maintenance",
        trigger_valve_maintenance,
    )
