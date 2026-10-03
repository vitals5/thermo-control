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
from homeassistant.exceptions import HomeAssistantError
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
from .helpers import (
    calibration_value,
    celsius,
    discover_related,
    finite,
    quantize,
    state_temperature,
)
from .manager import RoomConfig

_LOGGER = logging.getLogger(__name__)


class ThermoControlCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Serialize intent and side effects; telemetry never overrides room intent."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry | RoomConfig) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry if isinstance(entry, ConfigEntry) else None,
        )
        self.entry = entry
        self.config = {**DEFAULTS, **entry.data, **entry.options}
        self.trvs: list[str] = self.config[CONF_TRVS]
        self.devices: dict[str, dict[str, Any]] = {}
        for entity_id in self.trvs:
            device = {**DEVICE_DEFAULTS, **self.config.get(CONF_DEVICES, {}).get(entity_id, {})}
            if CONF_REGULATED_MODE not in self.config.get(CONF_DEVICES, {}).get(entity_id, {}):
                state = hass.states.get(entity_id)
                if (
                    state
                    and "heat" not in state.attributes.get("hvac_modes", [])
                    and "auto" in state.attributes.get("hvac_modes", [])
                ):
                    device[CONF_REGULATED_MODE] = "auto"
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
        self.window_blocked = False
        self._window_pending: bool | None = None
        self._window_cancel: Callable[[], None] | None = None
        self._debounce_cancel: Callable[[], None] | None = None
        self._unsubscribers: list[Callable[[], None]] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self._lock = asyncio.Lock()
        self._closed = False
        self._demand = False
        self._attempts: dict[tuple[str, str], tuple[dict[str, Any], datetime]] = {}
        self._calibration: dict[str, dict[str, Any]] = {}
        self._errors: dict[str, str] = {}
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")

    async def async_initialize(self) -> None:
        """Load write timestamps before any possible device writes."""
        stored = await self._store.async_load()
        if stored:
            self._calibration = stored.get("calibration", {})
            self.window_blocked = bool(stored.get("window_blocked", False))
        self._publish()

    async def async_start(self) -> None:
        """Subscribe after the climate entity has restored its desired state."""
        ids = {self.config[CONF_SENSOR], *self.trvs, *self.config[CONF_WINDOWS]}
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
        value = state_temperature(self._state(self.config[CONF_SENSOR]))
        return value if value is not None and -40 <= value <= 80 else None

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
            if mode is not None:
                self.mode = mode
            if preset is not None:
                if preset == "none":
                    self.target = self.manual_target
                else:
                    if self.preset == "none":
                        self.manual_target = self.target
                    self.target = float(self.config[f"preset_{preset}"])
                self.preset = preset
            if temperature is not None:
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
        if self.mode == HVACMode.OFF or self.window_blocked or room is None:
            action = HVACAction.OFF
        else:
            action = HVACAction.HEATING if self._demand else HVACAction.IDLE
        self.async_set_updated_data(
            {
                "temperature": room,
                "target": self.target,
                "mode": HVACMode.OFF if self.window_blocked else self.mode,
                "action": action,
                "preset": self.preset,
                "position": round(sum(positions) / len(positions), 1) if positions else None,
                "available": room is not None
                and any(self._state(entity_id) for entity_id in self.trvs),
                "devices": device_status,
            }
        )

    async def _reconcile(self) -> None:
        room = self._room_temperature()
        enabled = self.mode == HVACMode.HEAT and not self.window_blocked and room is not None
        if not enabled:
            self._demand = False
        elif room <= self.target - self.config[CONF_TOLERANCE]:
            self._demand = True
        elif room >= self.target + self.config[CONF_TOLERANCE]:
            self._demand = False
        # TRVs keep their own proportional regulation. Hysteresis governs action
        # reporting, not repetitive heat/off motor commands around the setpoint.
        self._publish()
        for entity_id, device in self.devices.items():
            state = self._state(entity_id)
            if state is None:
                continue
            self._errors.pop(entity_id, None)
            try:
                await self._sync_trv(entity_id, device, state, enabled and not self.window_blocked)
                if enabled and not self._windows_open():
                    await self._calibrate(entity_id, device, state, room)
            except (HomeAssistantError, TimeoutError, ValueError) as err:
                self._errors[entity_id] = str(err)
                _LOGGER.warning(
                    "Control of %s failed; retry in %s seconds: %s", entity_id, RETRY_SECONDS, err
                )
        self._publish()

    async def _call(self, entity_id: str, domain: str, service: str, data: dict[str, Any]) -> bool:
        """Suppress unacknowledged duplicate commands and bound every service call."""
        key = (entity_id, f"{domain}.{service}")
        now = dt_util.utcnow()
        previous = self._attempts.get(key)
        if previous and previous[0] == data and (now - previous[1]).total_seconds() < RETRY_SECONDS:
            return False
        self._attempts[key] = (dict(data), now)
        async with asyncio.timeout(SERVICE_TIMEOUT):
            await self.hass.services.async_call(domain, service, data, blocking=True)
        return True

    async def _sync_trv(
        self, entity_id: str, device: dict[str, Any], state: State, enabled: bool
    ) -> None:
        modes = state.attributes.get("hvac_modes", [])
        regulated = device[CONF_REGULATED_MODE]
        desired = regulated if enabled else HVACMode.OFF
        # Off takes priority over all other commands. If unsupported, use frost target.
        if not enabled and HVACMode.OFF in modes:
            if state.state != HVACMode.OFF:
                await self._call(
                    entity_id,
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": HVACMode.OFF},
                )
            return
        if regulated not in modes:
            raise HomeAssistantError(f"Configured regulated mode {regulated} is unsupported")
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
        wanted = self.target if enabled else float(self.config[CONF_FROST])
        low = celsius(state.attributes.get("min_temp"), unit)
        high = celsius(state.attributes.get("max_temp"), unit)
        wanted = min(high if high is not None else 35, max(low if low is not None else 5, wanted))
        native = TemperatureConverter.convert(wanted, UnitOfTemperature.CELSIUS, unit)
        step = finite(state.attributes.get("target_temp_step")) or 0.5
        if unit == UnitOfTemperature.CELSIUS:
            native = quantize(
                native, low if low is not None else 5, high if high is not None else 35, step
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
        if enabled and (self.window_blocked or self._room_temperature() is None):
            await self._sync_trv(entity_id, device, state, False)
            return
        if desired == HVACMode.OFF:
            desired = regulated  # Firmware without off: frost protection fallback.
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
        number_id, topic = device.get(CONF_CALIBRATION_ENTITY), device.get(CONF_CALIBRATION_TOPIC)
        if not number_id and not topic:
            return
        saved = self._calibration.get(entity_id, {})
        now = dt_util.utcnow()
        if last := saved.get("attempted_at"):
            last_date = dt_util.parse_datetime(last)
            if last_date and (now - last_date).total_seconds() < self.config[CONF_INTERVAL]:
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
            await self._call(
                entity_id, "number", "set_value", {"entity_id": number_id, "value": value}
            )
        else:
            await self._call(
                entity_id,
                "mqtt",
                "publish",
                {"topic": topic, "payload": str(value), "qos": 0, "retain": False},
            )
        self._calibration[entity_id]["value"] = value
        self._save_later()

    @callback
    def _storage_data(self) -> dict[str, Any]:
        return {"calibration": self._calibration, "window_blocked": self.window_blocked}

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
            await self._store.async_save(self._storage_data())
        await super().async_shutdown()
