"""Stable demand entities make the read-only heat-pump interlock automatable."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .manager import SIGNAL_ROOMS


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            DemandSensor(entry.runtime_data, key, name)
            for key, name in (
                ("demand", "Thermo Control Wärmebedarf"),
                ("eligible_demand", "Thermo Control Freigegebener Wärmebedarf"),
            )
        ]
    )


class DemandSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:radiator"

    def __init__(self, manager, key, name):
        self.manager, self.key = manager, key
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = name

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_ROOMS, self.async_write_ha_state)
        )

    @property
    def native_value(self):
        return self.manager.system.snapshot()[self.key]

    @property
    def extra_state_attributes(self):
        return self.manager.system.snapshot()
