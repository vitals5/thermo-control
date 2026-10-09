"""Push-driven room control, window interlock and bounded calibration writes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_OFF,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

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
    RETRY_SECONDS,
    SERVICE_TIMEOUT,
)
from .control import FloorController
from .helpers import (
    calibration_value,
    celsius,
    discover_related,
    finite,
    quantize,
    state_temperature,
)
from .maintenance import ValveMaintenance
from .manager import RoomConfig

_LOGGER = logging.getLogger(__name__)


class ThermoControlCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Serialize intent and side effects; telemetry never overrides room intent."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry | RoomConfig, *, manager=None
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry if isinstance(entry, ConfigEntry) else None,
        )
        self.entry = entry
        self.manager = manager
        self.controller = FloorController()
        self.heat_demand = 0.0
        self.heat_permitted = True
        self.interlock_reason = None
        self.config = {**DEFAULTS, **entry.data, **entry.options}
        self.trvs: list[str] = self.config[CONF_TRVS]
        self.devices: dict[str, dict[str, Any]] = {}
        for entity_id in self.trvs:
            device = {**DEVICE_DEFAULTS, **self.config.get(CONF_DEVICES, {}).get(entity_id, {})}
            # Older configurations used auto as a regulated mode. External
            # control now always uses heat; the physical auto mode is respected.
            device[CONF_REGULATED_MODE] = HVACMode.HEAT
            if not device.get(CONF_CALIBRATION_ENTITY) and not device.get(CONF_CALIBRATION_TOPIC):
                device[CONF_CALIBRATION_ENTITY] = discover_related(
                    hass, entity_id, "number", "local_temperature_calibration"
                )
            if not device.get(CONF_POSITION_ENTITY):
                device[CONF_POSITION_ENTITY] = discover_related(
                    hass, entity_id, "sensor", "position"
                )
            self.devices[entity_id] = device
        self.target = float(self.config["preset_none"])
        self.manual_target = self.target
        self.mode = HVACMode.OFF
        self.preset = "none"
        self.schedule_state = {"schedule_active": False, "schedule_available": False}
        self._preheat_latch = {}
        self.window_blocked = False
        self._window_pending: bool | None = None
        self._window_cancel: Callable[[], None] | None = None
        self._debounce_cancel: Callable[[], None] | None = None
        self._unsubscribers: list[Callable[[], None]] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self._lock = asyncio.Lock()
        self._closed = False
        self._demand = False
        self._normal_output = False
        self._attempts: dict[tuple[str, str], tuple[dict[str, Any], datetime]] = {}
        self._calibration: dict[str, dict[str, Any]] = {}
        self._errors: dict[str, str] = {}
        self.maintenance = ValveMaintenance(self)
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")

    async def async_initialize(self) -> None:
        """Load write timestamps before any possible device writes."""
        stored = await self._store.async_load()
        if stored:
            self.maintenance.restore(stored.get("valve_maintenance", {}))
            self._calibration = stored.get("calibration", {})
            self._preheat_latch = stored.get("schedule_preheat", {})
            self.window_blocked = bool(stored.get("window_blocked", False))
            self.controller.restore(stored.get("control", {}), dt_util.utcnow().timestamp())
        self._publish()

    async def async_start(self) -> None:
        """Subscribe after the climate entity has restored its desired state."""
        ids = {*self.trvs, *self.config[CONF_WINDOWS]}
        if sensor := self.config.get(CONF_SENSOR):
            ids.add(sensor)
        for device in self.devices.values():
            ids.update(
                device[key]
                for key in (CONF_CALIBRATION_ENTITY, CONF_INTERNAL_SENSOR, CONF_POSITION_ENTITY)
                if device.get(key)
            )
        self._unsubscribers.extend(
            [
                async_track_state_change_event(self.hass, list(ids), self._state_changed),
                async_track_time_interval(self.hass, self._tick, timedelta(seconds=RETRY_SECONDS)),
            ]
        )
        await self._tick()

    @callback
    def _state_changed(self, event: Event) -> None:
        """Process contacts promptly; coalesce noisy device and sensor reports."""
        if self._closed:
            return
        entity_id = event.data["entity_id"]
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if (
            entity_id in self.trvs
            and old
            and new
            and old.state != new.state
            and HVACMode.AUTO in (old.state, new.state)
        ):
            self._forget_commands(entity_id)
        if (
            self.mode == HVACMode.AUTO
            and event.data["entity_id"] in self.trvs
            and (old := event.data.get("old_state")) is not None
            and old.state == HVACMode.AUTO
            and (new := event.data.get("new_state")) is not None
            and new.state == HVACMode.HEAT
        ):
            # A deliberate manual switch on a device resumes external control.
            # Other devices that remain in auto are still left untouched.
            self.mode = HVACMode.HEAT
        if event.data["entity_id"] in self.config[CONF_WINDOWS]:
            self._update_windows()
            self._publish()
        if self._debounce_cancel is None:
            self._debounce_cancel = async_call_later(self.hass, 0.5, self._debounced)

    @callback
    def _debounced(self, _: datetime) -> None:
        self._debounce_cancel = None
        if not self._closed:
            task = self.hass.async_create_task(self._tick(), f"{DOMAIN} reconcile")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _state(self, entity_id: str | None) -> State | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        return state if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else None

    def _room_temperature(self) -> float | None:
        """Use the chosen reference, or average valid thermostat measurements."""
        if sensor := self.config.get(CONF_SENSOR):
            value = state_temperature(self._state(sensor))
            return value if value is not None and -40 <= value <= 80 else None
        values = []
        for entity_id in self.trvs:
            if (state := self._state(entity_id)) is None:
                continue
            unit = state.attributes.get("temperature_unit", self.hass.config.units.temperature_unit)
            value = celsius(state.attributes.get("current_temperature"), unit)
            if value is not None and -40 <= value <= 80:
                values.append(value)
        return sum(values) / len(values) if values else None

    def _windows_open(self) -> bool:
        # Only positively closed contacts permit recovery. Missing contacts block heat.
        return any(
            (state := self._state(entity_id)) is None or state.state != STATE_OFF
            for entity_id in self.config[CONF_WINDOWS]
        )

    @callback
    def _update_windows(self) -> None:
        opened = self._windows_open()
        if opened == self.window_blocked:
            if self._window_cancel:
                self._window_cancel()
                self._window_cancel = None
            self._window_pending = None
            return
        if self._window_pending == opened:
            return
        if self._window_cancel:
            self._window_cancel()
        self._window_pending = opened
        delay = self.config[CONF_OPEN_DELAY if opened else CONF_CLOSE_DELAY]
        if delay == 0:
            self.window_blocked = opened
            self._window_pending = None
            self._window_cancel = None
            self._save_later()
        else:
            self._window_cancel = async_call_later(self.hass, delay, self._window_elapsed)

    async def _window_elapsed(self, _: datetime) -> None:
        self._window_cancel = None
        if self._closed:
            return
        async with self._lock:
            if self._window_pending == self._windows_open():
                self.window_blocked = bool(self._window_pending)
                self._save_later()
            self._window_pending = None
            await self._reconcile()

    async def _tick(self, _: datetime | None = None) -> None:
        async with self._lock:
            if not self._closed:
                self._update_windows()
                await self._reconcile()

    async def async_set_intent(
        self,
        *,
        mode: HVACMode | None = None,
        temperature: float | None = None,
        preset: str | None = None,
    ) -> None:
        """Keep desired mode and temperature even while the interlock is active."""
        async with self._lock:
            await self.maintenance.async_cancel("cancelled")
            if mode is not None:
                if not self.supports_mode(mode):
                    raise ServiceValidationError(
                        "Der gewünschte Modus wird nicht von allen Thermostaten unterstützt."
                    )
                previous_mode = self.mode
                self.mode = mode
                try:
                    for entity_id in self.trvs:
                        state = self._state(entity_id)
                        if state is None:
                            continue
                        wanted = HVACMode.AUTO if mode == HVACMode.AUTO else HVACMode.HEAT
                        # Only explicit user mode changes may enter or leave auto.
                        if (mode == HVACMode.AUTO and state.state != wanted) or (
                            mode != HVACMode.AUTO and state.state == HVACMode.AUTO
                        ):
                            await self._call(
                                entity_id,
                                "climate",
                                "set_hvac_mode",
                                {"entity_id": entity_id, "hvac_mode": wanted},
                                allow_auto=True,
                            )
                except (HomeAssistantError, TimeoutError):
                    self.mode = previous_mode
                    self._publish()
                    raise
            if preset is not None:
                if self.manager and self.manager.schedules.plan_for(self.entry.entry_id):
                    await self.manager.schedules.async_room_active(self.entry.entry_id, False)
                if preset == "none":
                    self.target = self.manual_target
                else:
                    if self.preset == "none":
                        self.manual_target = self.target
                    self.target = float(self.config[f"preset_{preset}"])
                self.preset = preset
            if temperature is not None:
                schedule_active = (
                    self.manager and self.manager.schedules.state_for(self)["schedule_active"]
                )
                if schedule_active:
                    await self.manager.schedules.async_override(self, temperature)
                    self.target = temperature
                else:
                    self.target = self.manual_target = temperature
                    self.preset = "none"
            self._update_windows()
            await self._reconcile()

    def temperature_limits(self) -> tuple[float, float]:
        """Expose the intersection of available TRV temperature ranges."""
        lows, highs = [5.0], [35.0]
        for entity_id in self.trvs:
            if (state := self._state(entity_id)) is None:
                continue
            unit = state.attributes.get("temperature_unit", self.hass.config.units.temperature_unit)
            if (low := celsius(state.attributes.get("min_temp"), unit)) is not None:
                lows.append(low)
            if (high := celsius(state.attributes.get("max_temp"), unit)) is not None:
                highs.append(high)
        return max(lows), min(highs)

    @property
    def effective_target(self) -> float:
        low, high = self.temperature_limits()
        offset = self.manager.settings["master_offset"] if self.manager else 0
        return min(high, max(low, self.target + offset))

    def base_temperature_limits(self) -> tuple[float, float]:
        low, high = self.temperature_limits()
        # A manual effective setpoint at a hardware boundary can have a base
        # outside that boundary while a valid master offset is applied.
        return low - 5, high + 5

    def control_config(self) -> dict[str, Any]:
        return self.manager.control_for(self.config) if self.manager else self.config

    def supports_mode(self, mode: HVACMode) -> bool:
        physical = HVACMode.AUTO if mode == HVACMode.AUTO else HVACMode.HEAT
        if mode not in (HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO):
            return False
        for entity_id in self.trvs:
            state = self.hass.states.get(entity_id)
            modes = state.attributes.get("hvac_modes") if state else None
            if modes is not None:
                if physical not in modes:
                    return False
            elif physical == HVACMode.AUTO and (not state or state.state != HVACMode.AUTO):
                return False
        return True

    def _is_auto(self, state: State | None) -> bool:
        if self.mode == HVACMode.AUTO:
            return True
        if state is None:
            return False
        modes = state.attributes.get("hvac_modes", [])
        return state.state == HVACMode.AUTO or ("auto" in modes and "heat" not in modes)

    @property
    def auto_devices(self) -> list[str]:
        return [entity_id for entity_id in self.trvs if self._is_auto(self._state(entity_id))]

    @property
    def native_auto(self) -> bool:
        states = [state for entity_id in self.trvs if (state := self._state(entity_id))]
        return self.mode == HVACMode.AUTO or bool(
            states and all(self._is_auto(state) for state in states)
        )

    def _publish(self) -> None:
        positions: list[float] = []
        device_status = {}
        for entity_id, device in self.devices.items():
            state = self._state(entity_id)
            sensor = self._state(device.get(CONF_POSITION_ENTITY))
            position = finite(
                sensor.state if sensor else state.attributes.get("position") if state else None
            )
            if position is not None and 0 <= position <= 100:
                positions.append(position)
            device_status[entity_id] = {
                "available": state is not None,
                "hvac_mode": state.state if state else None,
                "external_control": state is not None and not self._is_auto(state),
                "hvac_action": state.attributes.get("hvac_action") if state else None,
                "position": position,
                "child_lock": state.attributes.get("child_lock") if state else None,
                "window_detection": state.attributes.get(
                    "window_detection", state.attributes.get("open_window")
                )
                if state
                else None,
                "calibration": self._calibration.get(entity_id, {}).get("value"),
                "error": self._errors.get(entity_id),
            }
        room = self._room_temperature()
        native_targets = []
        if self.native_auto:
            for entity_id in self.trvs:
                state = self._state(entity_id)
                if state and self._is_auto(state):
                    unit = state.attributes.get(
                        "temperature_unit", self.hass.config.units.temperature_unit
                    )
                    if (value := celsius(state.attributes.get("temperature"), unit)) is not None:
                        native_targets.append(value)
        target = (
            sum(native_targets) / len(native_targets) if native_targets else self.effective_target
        )
        actions = [
            device["hvac_action"] for device in device_status.values() if device["available"]
        ]
        if HVACAction.HEATING in actions:
            action = (
                HVACAction.HEATING
            )  # Actual valve activity, including delayed off acknowledgements.
        elif HVACAction.IDLE in actions:
            action = HVACAction.IDLE
        elif HVACAction.OFF in actions or self.mode == HVACMode.OFF:
            action = HVACAction.OFF
        else:
            action = None  # A missing hardware report is never invented from demand.
        self.async_set_updated_data(
            {
                **self.schedule_state,
                "temperature": room,
                "target": target,
                "mode": HVACMode.AUTO
                if self.native_auto
                else HVACMode.OFF
                if self.window_blocked
                else self.mode,
                "native_auto": self.native_auto,
                "auto_devices": self.auto_devices,
                "action": action,
                "preset": self.preset,
                "position": round(sum(positions) / len(positions), 1) if positions else None,
                "available": room is not None
                and any(self._state(entity_id) for entity_id in self.trvs),
                "devices": device_status,
                "heat_demand": self.heat_demand,
                "heat_permitted": self.heat_permitted,
                "interlock_reason": self.interlock_reason,
                "temperature_rate": self.controller.rate,
                "predicted_temperature": self.controller.predicted,
                "pre_shutoff": self.controller.pre_shutoff,
                "pwm_active": self.controller.active,
                "duty_cycle": self.controller.cycle_duty * 100,
                "valve_maintenance_phase": self.maintenance.phase,
                "valve_maintenance_last_date": self.maintenance.state.get("last_date"),
                "valve_maintenance_result": self.maintenance.state.get("last_result"),
            }
        )
        if (
            self.manager
            and self.entry.entry_id in self.manager.entities
            and self.manager.entities[self.entry.entry_id].coordinator is self
        ):
            self.manager.notify()

    async def _reconcile(self) -> None:
        self.schedule_state = (
            self.manager.schedules.state_for(self)
            if self.manager
            else {"schedule_active": False, "schedule_available": False}
        )
        previous_latch = self._preheat_latch
        state = self.schedule_state
        if (
            state["schedule_active"]
            and not state.get("schedule_override")
            and self.config["heating_type"] == "floor"
        ):
            until = dt_util.parse_datetime(previous_latch.get("until", ""))
            if (
                until
                and until > dt_util.utcnow()
                and previous_latch.get("signature") == state.get("schedule_signature")
            ):
                state.update(
                    target=previous_latch["target"],
                    preheating=True,
                    schedule_until=previous_latch["until"],
                )
            elif state["preheating"]:
                self._preheat_latch = {
                    "target": state["target"],
                    "until": state["next_change"],
                    "signature": state["schedule_signature"],
                }
            else:
                self._preheat_latch = {}
        else:
            self._preheat_latch = {}
        if previous_latch != self._preheat_latch:
            try:
                await self._store.async_save(self._storage_data())
            except OSError:
                self._preheat_latch = previous_latch
                raise
        if self.schedule_state["schedule_active"]:
            self.target = self.schedule_state["target"]
            self.preset = "schedule"
        elif self.preset == "schedule":
            self.target = self.manual_target
            self.preset = "none"
        room = self._room_temperature()
        enabled = (
            self.mode == HVACMode.HEAT
            and not self.window_blocked
            and room is not None
            and any(
                (state := self._state(entity_id)) is not None and not self._is_auto(state)
                for entity_id in self.trvs
            )
        )
        self.heat_permitted, self.interlock_reason = (
            self.manager.system.permit(room) if self.manager else (True, None)
        )
        config = self.control_config()
        previous_control = (self.controller.active, self.controller.switched_at)
        if self.config["heating_type"] == "floor":
            output = self.controller.update(
                dt_util.utcnow().timestamp(),
                room,
                self.effective_target,
                enabled,
                config,
                permitted=self.heat_permitted,
            )
            self.heat_demand = self.controller.demand * 100
            self._demand = output
        else:
            output = enabled and self.heat_permitted
            if not enabled:
                self._demand = False
            elif room <= self.effective_target - config[CONF_TOLERANCE]:
                self._demand = True
            elif room >= self.effective_target + config[CONF_TOLERANCE]:
                self._demand = False
            self.heat_demand = 100.0 if self._demand else 0.0
        if any(
            (state := self._state(entity_id)) is not None
            and self._is_auto(state)
            and state.attributes.get("hvac_action") == HVACAction.HEATING
            for entity_id in self.trvs
        ):
            # Auto demand is observed hardware activity, never an external PWM request.
            self.heat_demand = 100.0
        # Persist transitions before hardware calls so minimum dwell survives restart.
        if previous_control != (self.controller.active, self.controller.switched_at):
            try:
                await self._store.async_save(self._storage_data())
            except OSError:
                self.controller.active, self.controller.switched_at = previous_control
                raise
        elif self.config["heating_type"] == "floor":
            self._store.async_delay_save(self._storage_data, 60)
        self._normal_output = output and not self.window_blocked
        maintenance = await self.maintenance.async_update()
        exercising = maintenance is not None
        self._publish()
        for entity_id, device in self.devices.items():
            state = self._state(entity_id)
            if state is None:
                continue
            self._errors.pop(entity_id, None)
            try:
                await self._sync_trv(
                    entity_id,
                    device,
                    state,
                    output and not self.window_blocked,
                    maintenance=maintenance,
                )
                if (
                    enabled
                    and self.maintenance.phase is None
                    and not self._windows_open()
                    and not self._is_auto(self._state(entity_id))
                ):
                    await self._calibrate(entity_id, device, state, room)
            except (HomeAssistantError, TimeoutError, ValueError) as err:
                await self.maintenance.async_cancel("failed")
                maintenance = None
                self._errors[entity_id] = str(err)
                _LOGGER.warning(
                    "Control of %s failed; retry in %s seconds: %s", entity_id, RETRY_SECONDS, err
                )
        if exercising and self.maintenance.phase == "restore":
            await self._restore_maintenance_output()
        await self.maintenance.async_finish()
        self._publish()

    async def _restore_maintenance_output(self) -> None:
        """Undo temporary device setpoints, also on failure or integration unload."""
        for entity_id, device in self.devices.items():
            state = self._state(entity_id)
            if state is None:
                continue
            try:
                await self._sync_trv(entity_id, device, state, self._normal_output)
            except (HomeAssistantError, TimeoutError, ValueError) as err:
                self._errors[entity_id] = str(err)
                _LOGGER.warning("Restoring %s after valve maintenance failed: %s", entity_id, err)

    def _forget_commands(self, entity_id: str) -> None:
        # A schedule may change targets without acknowledging our previous writes.
        for key in list(self._attempts):
            if key[0] == entity_id:
                del self._attempts[key]

    async def _call(
        self,
        entity_id: str,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        allow_auto: bool = False,
    ) -> bool:
        """Suppress unacknowledged duplicate commands and bound every service call."""
        if not allow_auto and self._is_auto(self._state(entity_id)):
            return False
        if allow_auto:
            self._forget_commands(entity_id)
        key = (entity_id, f"{domain}.{service}")
        now = dt_util.utcnow()
        previous = self._attempts.get(key)
        if (
            not allow_auto
            and previous
            and previous[0] == data
            and (now - previous[1]).total_seconds() < RETRY_SECONDS
        ):
            return False
        self._attempts[key] = (dict(data), now)
        async with asyncio.timeout(SERVICE_TIMEOUT):
            await self.hass.services.async_call(domain, service, data, blocking=True)
        return True

    async def _sync_trv(
        self,
        entity_id: str,
        device: dict[str, Any],
        state: State,
        enabled: bool,
        *,
        maintenance: float | None = None,
    ) -> None:
        if self._is_auto(self._state(entity_id)):
            self._forget_commands(entity_id)
            return
        modes = state.attributes.get("hvac_modes", [])
        desired = HVACMode.HEAT
        if desired not in modes:
            raise HomeAssistantError("External control requires the thermostat's heat mode")
        if (
            "manual" in state.attributes.get("preset_modes", [])
            and state.attributes.get("preset_mode") != "manual"
        ):
            await self._call(
                entity_id,
                "climate",
                "set_preset_mode",
                {"entity_id": entity_id, "preset_mode": "manual"},
            )
        unit = state.attributes.get("temperature_unit", self.hass.config.units.temperature_unit)
        wanted = self.effective_target if enabled else float(self.config[CONF_FROST])
        low = celsius(state.attributes.get("min_temp"), unit)
        high = celsius(state.attributes.get("max_temp"), unit)
        if maintenance is not None:
            wanted = (
                (low if low is not None else 5)
                if maintenance == 0
                else (high if high is not None else 30)
            )
        wanted = min(high if high is not None else 35, max(low if low is not None else 5, wanted))
        native = TemperatureConverter.convert(wanted, UnitOfTemperature.CELSIUS, unit)
        step = finite(state.attributes.get("target_temp_step")) or 0.5
        if unit == UnitOfTemperature.CELSIUS:
            native = quantize(
                native, low if low is not None else 5, high if high is not None else 35, step
            )
        elif maintenance is not None:
            native = quantize(
                native,
                TemperatureConverter.convert(
                    low if low is not None else 5, UnitOfTemperature.CELSIUS, unit
                ),
                TemperatureConverter.convert(
                    high if high is not None else 35, UnitOfTemperature.CELSIUS, unit
                ),
                step,
            )
        actual = finite(state.attributes.get("temperature"))
        tolerance = 0.01 if unit == UnitOfTemperature.CELSIUS else 0.5
        if actual is None or abs(actual - native) > tolerance:
            await self._call(
                entity_id,
                "climate",
                "set_temperature",
                {"entity_id": entity_id, "temperature": native},
            )
        if (enabled or maintenance is not None) and (
            self.window_blocked
            or self._room_temperature() is None
            or maintenance is not None
            and self._windows_open()
        ):
            await self._sync_trv(entity_id, device, state, False)
            return
        if state.state != desired:
            await self._call(
                entity_id,
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": desired},
            )

    async def _calibrate(
        self, entity_id: str, device: dict[str, Any], state: State, room: float
    ) -> None:
        if self._is_auto(self._state(entity_id)) or not self.config.get(CONF_SENSOR):
            return  # Never recalibrate trusted thermostat readings against their own mean.
        number_id, topic = device.get(CONF_CALIBRATION_ENTITY), device.get(CONF_CALIBRATION_TOPIC)
        if not number_id and not topic:
            return
        saved = self._calibration.get(entity_id, {})
        now = dt_util.utcnow()
        if last := saved.get("attempted_at"):
            last_date = dt_util.parse_datetime(last)
            interval = (
                self.manager.settings[CONF_INTERVAL]
                if self.manager and self.config["use_global_calibration"]
                else self.config[CONF_INTERVAL]
            )
            if last_date and (now - last_date).total_seconds() < interval:
                return
        number = self._state(number_id)
        if number_id and number is None:
            return  # A selected number never silently falls back to MQTT.
        current = finite(
            number.state if number else state.attributes.get("local_temperature_calibration")
        )
        if current is None:
            current = finite(saved.get("value"))
        if current is None:
            return  # Unknown baseline must not be assumed zero.
        internal_state = self._state(device.get(CONF_INTERNAL_SENSOR))
        if device.get(CONF_INTERNAL_SENSOR):
            internal = state_temperature(internal_state)
        else:
            unit = state.attributes.get("temperature_unit", self.hass.config.units.temperature_unit)
            internal = celsius(state.attributes.get("current_temperature"), unit)
        if internal is None or not -40 <= internal <= 80:
            return
        minimum, maximum, step = (
            float(device[key])
            for key in (CONF_CALIBRATION_MIN, CONF_CALIBRATION_MAX, CONF_CALIBRATION_STEP)
        )
        origin = minimum
        if number:
            origin = finite(number.attributes.get("min"))
            minimum = max(
                minimum,
                finite(number.attributes.get("min"))
                if finite(number.attributes.get("min")) is not None
                else minimum,
            )
            maximum = min(
                maximum,
                finite(number.attributes.get("max"))
                if finite(number.attributes.get("max")) is not None
                else maximum,
            )
            step = finite(number.attributes.get("step")) or step
        if minimum >= maximum or step <= 0:
            raise HomeAssistantError("Invalid calibration bounds")
        value = calibration_value(
            room, internal, current, device[CONF_CORRECTED], minimum, maximum, step, origin
        )
        if abs(value - current) < self.config[CONF_THRESHOLD] or abs(value - current) < 0.001:
            return
        # Persist the attempt before sending; failed writes are rate-limited too.
        self._calibration[entity_id] = {**saved, "attempted_at": now.isoformat()}
        await self._store.async_save(self._storage_data())
        if number_id:
            written = await self._call(
                entity_id, "number", "set_value", {"entity_id": number_id, "value": value}
            )
        else:
            written = await self._call(
                entity_id,
                "mqtt",
                "publish",
                {"topic": topic, "payload": str(value), "qos": 0, "retain": False},
            )
        if not written:
            return
        self._calibration[entity_id]["value"] = value
        self._save_later()

    @callback
    def _storage_data(self) -> dict[str, Any]:
        return {
            "schedule_preheat": self._preheat_latch,
            "calibration": self._calibration,
            "window_blocked": self.window_blocked,
            "control": self.controller.dump(),
            "valve_maintenance": self.maintenance.dump(),
        }

    @callback
    def _save_later(self) -> None:
        self._store.async_delay_save(self._storage_data, 1)

    async def async_shutdown(self) -> None:
        """Remove listeners, timers and running commands before unloading."""
        self._closed = True
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        for cancel in (self._window_cancel, self._debounce_cancel):
            if cancel:
                cancel()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        async with self._lock:
            if self.maintenance.phase:
                await self.maintenance.async_cancel()
                await self._restore_maintenance_output()
                await self.maintenance.async_finish()
            await self._store.async_save(self._storage_data())
        await super().async_shutdown()
