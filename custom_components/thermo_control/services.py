"""Automation access to the reversible master setpoint shift."""

import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN


def async_register_services(hass):
    async def set_master(call):
        manager = hass.data.get(DOMAIN)
        if manager is None or manager._closed:
            raise ServiceValidationError("Thermo Control ist noch nicht bereit.")
        await manager.async_set_master_offset(call.data["offset"])

    async_register_admin_service(
        hass,
        DOMAIN,
        "set_master_offset",
        set_master,
        schema=vol.Schema({vol.Required("offset"): vol.Coerce(float)}),
    )
