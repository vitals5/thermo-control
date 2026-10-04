"""Luxtronik telemetry, explicit heat availability and aggregate demand."""

from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

from .helpers import state_temperature

if TYPE_CHECKING:
    from .manager import RoomManager


class HeatingSystem:
    """Read configured HA entities; leave compressor and DHW control to Luxtronik."""

    def __init__(self, manager: RoomManager) -> None:
        self.manager = manager
        self._unsubscribe = None

    def bind(self) -> None:
        self.close()
        hp = self.manager.settings["heat_pump"]
        ids = [
            hp[key]
            for key in ("flow_sensor", "target_sensor", "mode_entity", "compressor_entity")
            if hp[key]
        ]
        if ids:
            self._unsubscribe = async_track_state_change_event(
                self.manager.hass, ids, self._changed
            )

    @callback
    def _changed(self, event) -> None:
        self.manager.notify()
        self.manager.schedule_reconcile()

    def close(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def telemetry(self) -> dict[str, Any]:
        config = self.manager.settings["heat_pump"]

        def state(key):
            value = self.manager.hass.states.get(config[key]) if config[key] else None
            return (
                value if value and value.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE) else None
            )

        mode, compressor = state("mode_entity"), state("compressor_entity")
        mode_value = mode.state if mode else None
        automatic = mode_value.casefold() in config["automatic_states"] if mode_value else None
        flow = state_temperature(state("flow_sensor"))
        target = state_temperature(state("target_sensor"))
        compressor_on = (
            compressor.state == "on" if compressor and compressor.state in ("on", "off") else None
        )
        return {
            "flow": flow,
            "target": target,
            "mode": mode_value,
            "automatic": automatic,
            "compressor": compressor_on,
            "interlock": config["interlock"],
            "warm": flow is not None and flow >= config["minimum_flow"],
        }

    def permit(self, room_temperature: float | None) -> tuple[bool, str | None]:
        config = self.manager.settings["heat_pump"]
        if not config["interlock"]:
            return True, None
        status = self.telemetry()
        if status["automatic"] is not True:
            return False, "mode_unavailable" if status["automatic"] is None else "not_automatic"
        if (
            room_temperature is None
            or not status["warm"]
            or status["flow"] < room_temperature + config["flow_margin"]
        ):
            return False, "no_flow_heat"
        return True, None

    def snapshot(self) -> dict[str, Any]:
        rooms = [entity.coordinator.data for entity in self.manager.entities.values()]
        demand = max((data.get("heat_demand", 0) for data in rooms), default=0)
        mean = sum(data.get("heat_demand", 0) for data in rooms) / len(rooms) if rooms else 0
        eligible = max(
            (data.get("heat_demand", 0) for data in rooms if data.get("heat_permitted")), default=0
        )
        return {
            **self.telemetry(),
            "demand": round(demand, 1),
            "mean_demand": round(mean, 1),
            "eligible_demand": round(eligible, 1),
            "heat_requested": eligible > 0,
            "heating_rooms": sum(data.get("action") == "heating" for data in rooms),
            "demand_rooms": sum(data.get("heat_demand", 0) > 0 for data in rooms),
        }
