"""Add the singleton integration; all settings belong to the sidebar panel."""

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, NAME


class ThermoControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Confirm installation without requesting any room or device settings."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured(error="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Keep the empty 1.1 YAML bootstrap working without storing settings."""
        return await self.async_step_user({})
