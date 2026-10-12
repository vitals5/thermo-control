"""PV and scheduled heat-pump targets via configurable HA entities."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import timedelta

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import HEAT_PUMP_CONTROL_DEFAULTS, SERVICE_TIMEOUT
from .helpers import celsius, finite, state_temperature
from .schedule import DAYS, minutes

_LOGGER = logging.getLogger(__name__)
PROFILES = ("standard", "boost", "blocked")
CHANNELS = ("heating", "dhw")


def validate_pump_schedule(plan):
    if (
        not isinstance(plan, dict)
        or set(plan) != {"enabled", "weekdays"}
        or type(plan["enabled"]) is not bool
    ):
        raise ServiceValidationError("Ungültiger Wärmepumpen-Zeitplan.")
    weekdays = plan["weekdays"]
    if not isinstance(weekdays, dict) or not set(weekdays) <= set(DAYS):
        raise ServiceValidationError("Ungültige Wochentage.")
    result, spans = {"enabled": plan["enabled"], "weekdays": {}}, []
    for day_index, day in enumerate(DAYS):
        blocks = weekdays.get(day, [])
        if not isinstance(blocks, list) or len(blocks) > 48:
            raise ServiceValidationError("Maximal 48 Sperrblöcke pro Tag.")
        result["weekdays"][day] = []
        for block in blocks:
            if not isinstance(block, dict) or set(block) != {"from", "to"}:
                raise ServiceValidationError("Sperrblöcke benötigen Start- und Endzeit.")
            start, end = minutes(block["from"]), minutes(block["to"], end=True)
            if start == end:
                raise ServiceValidationError("Start und Ende dürfen nicht gleich sein.")
            absolute = day_index * 1440 + start
            finish = day_index * 1440 + end + (1440 if end < start else 0)
            spans.append((absolute, finish))
            result["weekdays"][day].append(dict(block))
    expanded = spans + [(start - 10080, end - 10080) for start, end in spans]
    for index, (start, end) in enumerate(expanded):
        if any(
            max(start, other_start) < min(end, other_end)
            for other_start, other_end in expanded[index + 1 :]
        ):
            raise ServiceValidationError("Sperrblöcke überschneiden sich, auch über Mitternacht.")
    return result


def blocked(plan, now):
    if not plan["enabled"]:
        return False
    local = dt_util.as_local(now)
    current = local.weekday() * 1440 + local.hour * 60 + local.minute
    for day_index, day in enumerate(DAYS):
        for block in plan["weekdays"].get(day, []):
            start, end = minutes(block["from"]), minutes(block["to"], end=True)
            start += day_index * 1440
            end += day_index * 1440 + (1440 if end < minutes(block["from"]) else 0)
            if start <= current < end or start <= current + 10080 < end:
                return True
    return False


def validate_pump_control(hass, config, *, check_entities=True):
    """Validate all configured channels before activation can cause writes."""
    result = deepcopy(HEAT_PUMP_CONTROL_DEFAULTS)
    if not isinstance(config, dict) or not set(config) <= set(result):
        raise ServiceValidationError("Ungültige Wärmepumpensteuerung.")
    for key, value in config.items():
        if key in CHANNELS:
            if not isinstance(value, dict) or not set(value) <= set(result[key]):
                raise ServiceValidationError("Ungültige Kanal-Einstellungen.")
            result[key].update(deepcopy(value))
        else:
            result[key] = deepcopy(value)
    if not isinstance(result["name"], str) or not 1 <= len(result["name"].strip()) <= 80:
        raise ServiceValidationError("Wärmepumpenname muss 1 bis 80 Zeichen enthalten.")
    result["name"] = result["name"].strip()
    if any(type(result[key]) is not bool for key in ("enabled",)) or any(
        type(result[channel]["enabled"]) is not bool for channel in CHANNELS
    ):
        raise ServiceValidationError("Aktivierung benötigt Wahrheitswerte.")
    if result["priority"] not in ("block", "pv") or result["heating_mode"] not in (
        "automatic",
        "off",
    ):
        raise ServiceValidationError("Ungültige Priorität oder Heizungsmodus.")
    for key, low, high in (("pv_delay", 0, 1800), ("minimum_hold", 60, 3600)):
        value = finite(result[key])
        if value is None or not low <= value <= high or value % 1:
            raise ServiceValidationError("Ungültige Verzögerung / Mindesthaltezeit.")
        result[key] = int(value)
    heating, dhw = result["heating"], result["dhw"]
    if (
        not isinstance(heating["automatic_mode"], str)
        or not 1 <= len(heating["automatic_mode"].strip()) <= 80
        or heating["blocked_mode"]
        not in (
            "keep",
            "off",
        )
    ):
        raise ServiceValidationError("Ungültiger Heizungsmodus.")
    if not isinstance(dhw["operation_mode"], str) or len(dhw["operation_mode"]) > 80:
        raise ServiceValidationError("Ungültiger Warmwasser-Betriebsmodus.")
    if (
        not isinstance(heating["profiles"], dict)
        or not isinstance(dhw["profiles"], dict)
        or set(heating["profiles"]) != set(PROFILES)
        or set(dhw["profiles"]) != set(PROFILES)
    ):
        raise ServiceValidationError("Standard, Boost und Blockierung sind erforderlich.")
    for profile in PROFILES:
        values = heating["profiles"][profile]
        if not isinstance(values, dict) or set(values) != {"end", "shift", "correction"}:
            raise ServiceValidationError(
                "Heizprofile benötigen Endpunkt, Parallelverschiebung und Korrektur."
            )
        for key, low, high in (("end", 10, 60), ("shift", 5, 35), ("correction", -5, 5)):
            value = finite(values[key])
            if value is None or not low <= value <= high:
                raise ServiceValidationError(f"Ungültiger Heizprofilwert: {key}")
            values[key] = value
        value = finite(dhw["profiles"][profile])
        if value is None or not 10 <= value <= 65:
            raise ServiceValidationError("Warmwasser-Sollwert muss zwischen 10 und 65 °C liegen.")
        dhw["profiles"][profile] = value
    schedules = result["schedules"]
    if not isinstance(schedules, dict) or set(schedules) != set(CHANNELS):
        raise ServiceValidationError("Zeitpläne für Heizung und Warmwasser sind erforderlich.")
    result["schedules"] = {
        channel: validate_pump_schedule(schedules[channel]) for channel in CHANNELS
    }
    fields = [
        (result, "pv_entity", ("input_boolean", "binary_sensor")),
        *[(result, key, ("sensor",)) for key in ("return_sensor", "flow_sensor", "mixed_sensor")],
        *[(result, key, ("number",)) for key in ("mixed_end_entity", "mixed_shift_entity")],
        (heating, "entity", ("climate",)),
        *[
            (heating, key, ("number",))
            for key in ("end_entity", "shift_entity", "correction_entity")
        ],
        (dhw, "entity", ("water_heater",)),
    ]
    for owner, key, domains in fields:
        entity_id = owner[key]
        if entity_id in (None, ""):
            owner[key] = None
            continue
        if (
            not isinstance(entity_id, str)
            or entity_id.split(".")[0] not in domains
            or entity_id.count(".") != 1
        ):
            raise ServiceValidationError(f"Ungültige Wärmepumpen-Entität: {entity_id}")
    managed = [
        heating[key]
        for key in ("entity", "end_entity", "shift_entity", "correction_entity")
        if heating[key]
    ] + [
        value
        for value in (dhw["entity"], result["mixed_end_entity"], result["mixed_shift_entity"])
        if value
    ]
    if len(managed) != len(set(managed)):
        raise ServiceValidationError(
            "Schreibbare Wärmepumpen-Entitäten dürfen nicht doppelt zugeordnet sein."
        )
    if result["enabled"]:
        required = [result["pv_entity"]] if result["pv_entity"] else []
        if heating["enabled"]:
            required += [heating[key] for key in ("entity", "end_entity", "shift_entity")]
        if dhw["enabled"]:
            required += [dhw["entity"]]
        if any(not eid or (check_entities and hass.states.get(eid) is None) for eid in required):
            raise ServiceValidationError(
                "Zum Aktivieren müssen die zugeordneten Steuerungs-Entitäten vorhanden sein."
            )
    return result


class HeatPumpController:
    """One serialized controller for two independently scheduled channels."""

    def __init__(self, manager):
        self.manager, self.hass = manager, manager.hass
        self._store = Store(self.hass, 1, "thermo_control.heat_pump")
        self.runtime = {"writes": {}, "channels": {}, "baseline": {}, "manual_dhw_boost": False}
        self.status = {
            channel: {"profile": "disabled", "errors": {}, "pending": False} for channel in CHANNELS
        }
        self._lock = asyncio.Lock()
        self._unsubscribers = []
        self._pv_sample = None
        self._pv_since = None

    @property
    def config(self):
        return self.manager.settings["heat_pump_control"]

    async def async_initialize(self):
        if stored := await self._store.async_load():
            self.runtime.update(stored)
        self.runtime.setdefault("manual_dhw_boost", False)

    async def async_trigger_dhw_boost(self, enable: bool = True) -> None:
        """Trigger or cancel manual DHW boost."""
        async with self._lock:
            if enable:
                if not self.config["enabled"]:
                    raise ServiceValidationError("Wärmepumpensteuerung ist nicht aktiviert.")
                if not self.config["dhw"]["enabled"]:
                    raise ServiceValidationError("Warmwasser-Kanal ist nicht aktiviert.")
            self.runtime["manual_dhw_boost"] = bool(enable)
            await self._save()
        self.manager.notify()
        self.manager.schedule_reconcile()

    def bind(self):
        self.close()
        config = self.config
        ids = [
            config[key]
            for key in (
                "pv_entity",
                "return_sensor",
                "flow_sensor",
                "mixed_sensor",
                "mixed_end_entity",
                "mixed_shift_entity",
            )
            if config[key]
        ]
        for channel in CHANNELS:
            ids += [
                value for key, value in config[channel].items() if key.endswith("entity") and value
            ]
        self._unsubscribers = [
            async_track_state_change_event(self.hass, ids, self._changed),
            async_track_time_interval(self.hass, self._timer, timedelta(seconds=60)),
        ]
        self.manager.schedule_reconcile()

    @callback
    def _changed(self, event):
        self.manager.notify()
        self.manager.schedule_reconcile()

    @callback
    def _timer(self, now):
        if self.config["enabled"] or self.runtime["baseline"]:
            self.manager.schedule_reconcile()

    def close(self):
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()

    def _state(self, entity_id):
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raise ServiceValidationError(f"Entität nicht verfügbar: {entity_id}")
        return state

    def _temperature_command(self, entity_id, value, domain, *, correction=False):
        state = self._state(entity_id)
        unit = (
            state.attributes.get("unit_of_measurement")
            if domain == "number"
            else self.hass.config.units.temperature_unit
        )
        unit = state.attributes.get("temperature_unit", unit) or UnitOfTemperature.CELSIUS
        if unit not in (
            UnitOfTemperature.CELSIUS,
            UnitOfTemperature.FAHRENHEIT,
            UnitOfTemperature.KELVIN,
        ):
            raise ServiceValidationError(f"{entity_id}: Ungültige Temperatureinheit.")
        native = TemperatureConverter.convert(value, UnitOfTemperature.CELSIUS, unit)
        minimum, maximum = ("min", "max") if domain == "number" else ("min_temp", "max_temp")
        low, high = finite(state.attributes.get(minimum)), finite(state.attributes.get(maximum))
        if low is None or high is None or not low <= native <= high:
            raise ServiceValidationError(
                f"{entity_id}: Sollwert {value} °C außerhalb der gemeldeten Grenzen."
            )
        if correction and not (celsius(low, unit) <= 0 <= celsius(high, unit) <= 10):
            raise ServiceValidationError(
                "Heizungs-Climate stellt keinen ±5-°C-Korrekturwert bereit. Eine Korrektur-Number zuordnen."
            )
        step = finite(state.attributes.get("step" if domain == "number" else "target_temp_step"))
        if step and abs((native - low) / step - round((native - low) / step)) > 0.0001:
            raise ServiceValidationError(
                f"{entity_id}: Sollwert passt nicht zur Geräteschrittweite {step}."
            )
        key = "value" if domain == "number" else "temperature"
        current = finite(state.state if domain == "number" else state.attributes.get("temperature"))
        if current is None:
            raise ServiceValidationError(f"{entity_id}: Aktueller Sollwert nicht bekannt.")
        service = "set_value" if domain == "number" else "set_temperature"
        return entity_id, domain, service, {"entity_id": entity_id, key: native}, current, key

    def _mode_command(self, entity_id, value, domain):
        state = self._state(entity_id)
        options, key, service = (
            ("hvac_modes", "hvac_mode", "set_hvac_mode")
            if domain == "climate"
            else ("operation_list", "operation_mode", "set_operation_mode")
        )
        if value not in state.attributes.get(options, []):
            raise ServiceValidationError(f"{entity_id}: Betriebsmodus {value} nicht unterstützt.")
        current = (
            state.state
            if domain == "climate"
            else state.attributes.get("operation_mode", state.state)
        )
        if current is None:
            raise ServiceValidationError(f"{entity_id}: Aktueller Betriebsmodus nicht bekannt.")
        return entity_id, domain, service, {"entity_id": entity_id, key: value}, current, key

    def _commands(self, channel, profile):
        config = self.config[channel]
        if channel == "dhw":
            commands = [
                self._temperature_command(
                    config["entity"], config["profiles"][profile], "water_heater"
                )
            ]
            if config["operation_mode"]:
                commands.append(
                    self._mode_command(config["entity"], config["operation_mode"], "water_heater")
                )
            return commands
        if profile == "off":
            return [self._mode_command(config["entity"], "off", "climate")]
        values = config["profiles"][profile]
        commands = [
            self._temperature_command(config["end_entity"], values["end"], "number"),
            self._temperature_command(config["shift_entity"], values["shift"], "number"),
            self._temperature_command(
                config["correction_entity"] or config["entity"],
                values["correction"],
                "number" if config["correction_entity"] else "climate",
                correction=True,
            ),
        ]
        mode = (
            "off"
            if profile == "blocked" and config["blocked_mode"] == "off"
            else config["automatic_mode"]
        )
        if mode == "off":
            commands.insert(0, self._mode_command(config["entity"], mode, "climate"))
        else:
            commands.append(self._mode_command(config["entity"], mode, "climate"))
        return commands

    async def _save(self):
        await self._store.async_save(deepcopy(self.runtime))

    async def _write(self, command, *, restore=False):
        entity_id, domain, service, data, current, key = command
        desired = data[key]
        if (
            current == desired
            or isinstance(desired, (int, float))
            and finite(current) is not None
            and abs(current - desired) < 0.001
        ):
            return True
        write_key = f"{entity_id}/{service}"
        now = dt_util.utcnow()
        previous = self.runtime["writes"].get(write_key, {})
        previous_time = dt_util.parse_datetime(previous.get("at", ""))
        if (
            previous.get("data") == data
            and previous_time
            and (now - previous_time).total_seconds() < 60
        ):
            return False
        baseline = self.runtime["baseline"].get(write_key)
        if baseline is None and not restore:
            if current is None:
                raise ServiceValidationError(
                    f"{entity_id}: Ausgangswert unbekannt; Schreiben ausgesetzt."
                )
            self.runtime["baseline"][write_key] = {
                "entity_id": entity_id,
                "domain": domain,
                "service": service,
                "key": key,
                "value": current,
                "unit": self._state(entity_id).attributes.get("unit_of_measurement")
                if domain == "number"
                else self._state(entity_id).attributes.get(
                    "temperature_unit", self.hass.config.units.temperature_unit
                ),
            }
        previous_runtime = deepcopy(self.runtime["writes"])
        self.runtime["writes"][write_key] = {"data": data, "at": now.isoformat()}
        try:
            await self._save()
        except OSError:
            self.runtime["writes"] = previous_runtime
            if baseline is None:
                self.runtime["baseline"].pop(write_key, None)
            raise
        async with asyncio.timeout(SERVICE_TIMEOUT):
            await self.hass.services.async_call(domain, service, data, blocking=True)
        return False  # Service receipt may precede the device's actual acknowledgement.

    async def async_restore(self, keys=None):
        errors = {}
        for write_key, baseline in list(self.runtime["baseline"].items()):
            if keys is not None and write_key not in keys:
                continue
            try:
                entity_id, domain, key = baseline["entity_id"], baseline["domain"], baseline["key"]
                if key in ("value", "temperature"):
                    value = celsius(baseline["value"], baseline.get("unit") or "°C")
                    command = self._temperature_command(entity_id, value, domain)
                else:
                    command = self._mode_command(entity_id, baseline["value"], domain)
                if await self._write(command, restore=True):
                    del self.runtime["baseline"][write_key]
                    try:
                        await self._save()
                    except OSError:
                        self.runtime["baseline"][write_key] = baseline
                        raise
            except (HomeAssistantError, TimeoutError, OSError, ValueError) as err:
                errors[write_key] = str(err)
        return errors

    async def async_reconcile(self):
        async with self._lock:
            config, now = self.config, dt_util.utcnow()
            managed = set()
            if config["enabled"]:
                if config["heating"]["enabled"]:
                    heating = config["heating"]
                    managed.add(f"{heating['entity']}/set_hvac_mode")
                    managed.add(
                        f"{heating['correction_entity'] or heating['entity']}/{'set_value' if heating['correction_entity'] else 'set_temperature'}"
                    )
                    managed.update(
                        f"{heating[key]}/set_value" for key in ("end_entity", "shift_entity")
                    )
                if config["dhw"]["enabled"]:
                    managed.add(f"{config['dhw']['entity']}/set_temperature")
                    if config["dhw"]["operation_mode"]:
                        managed.add(f"{config['dhw']['entity']}/set_operation_mode")
            retired_errors = await self.async_restore(set(self.runtime["baseline"]) - managed)
            if not config["enabled"]:
                if self.runtime.get("manual_dhw_boost"):
                    self.runtime["manual_dhw_boost"] = False
                    try:
                        await self._save()
                    except OSError:
                        pass
                self.status = {
                    channel: {
                        "profile": "disabled",
                        "errors": retired_errors,
                        "pending": bool(self.runtime["baseline"]),
                    }
                    for channel in CHANNELS
                }
                return
            pv_state = self.hass.states.get(config["pv_entity"]) if config["pv_entity"] else None
            pv = (
                False
                if not config["pv_entity"]
                else pv_state.state == "on"
                if pv_state and pv_state.state in ("on", "off")
                else None
            )
            if pv != self._pv_sample or self._pv_since is None:
                self._pv_sample, self._pv_since = pv, now
            ready = pv is True and (now - self._pv_since).total_seconds() >= config["pv_delay"]
            for channel in CHANNELS:
                if not config[channel]["enabled"]:
                    if channel == "dhw" and self.runtime.get("manual_dhw_boost"):
                        self.runtime["manual_dhw_boost"] = False
                        try:
                            await self._save()
                        except OSError:
                            pass
                    self.status[channel] = {
                        "profile": "disabled",
                        "errors": dict(retired_errors),
                        "pending": bool(set(self.runtime["baseline"]) - managed),
                    }
                    continue
                manual_boost = False
                if channel == "dhw" and self.runtime.get("manual_dhw_boost"):
                    manual_boost = True
                    dhw_state = (
                        self.hass.states.get(config["dhw"]["entity"])
                        if config["dhw"]["entity"]
                        else None
                    )
                    dhw_temp = None
                    if dhw_state and dhw_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                        unit = dhw_state.attributes.get(
                            "temperature_unit",
                            dhw_state.attributes.get(
                                "unit_of_measurement", self.hass.config.units.temperature_unit
                            ),
                        )
                        dhw_temp = celsius(dhw_state.attributes.get("current_temperature"), unit)
                    boost_target = config["dhw"]["profiles"]["boost"]
                    if dhw_temp is not None and dhw_temp >= boost_target:
                        manual_boost = False
                        self.runtime["manual_dhw_boost"] = False
                        try:
                            await self._save()
                        except OSError:
                            pass
                        self.manager.notify()
                block = blocked(config["schedules"][channel], now)
                profile = (
                    "boost"
                    if manual_boost or (ready and (not block or config["priority"] == "pv"))
                    else "blocked"
                    if block
                    else "standard"
                )
                if channel == "heating" and config["heating_mode"] == "off":
                    profile = "off"
                saved = self.runtime["channels"].get(channel, {})
                since = dt_util.parse_datetime(saved.get("since", ""))
                if (
                    not manual_boost
                    and not saved.get("manual")
                    and profile in ("standard", "boost")
                    and saved.get("profile") in ("standard", "boost")
                    and since
                    and pv is not None
                    and (now - since).total_seconds() < config["minimum_hold"]
                ):
                    profile = saved["profile"]
                status = self.status[channel] = {
                    "profile": profile,
                    "blocked": block,
                    "pv": pv,
                    "pv_ready": ready,
                    "manual_boost": manual_boost,
                    "errors": dict(retired_errors),
                    "pending": False,
                }
                try:
                    commands = self._commands(channel, profile)  # Validate the whole channel first.
                    if saved.get("profile") != profile or saved.get("manual") != manual_boost:
                        self.runtime["channels"][channel] = {
                            "profile": profile,
                            "since": now.isoformat(),
                            "manual": manual_boost,
                        }
                        try:
                            await self._save()
                        except OSError:
                            if saved:
                                self.runtime["channels"][channel] = saved
                            else:
                                self.runtime["channels"].pop(channel, None)
                            raise
                    for command in commands:
                        if not await self._write(command):
                            status["pending"] = True
                except (HomeAssistantError, TimeoutError, OSError, ValueError) as err:
                    status["errors"][channel] = str(err)
                    _LOGGER.warning("Heat-pump control of %s failed: %s", channel, err)

    def snapshot(self):
        config = self.config

        def temperature(entity_id):
            state = self.hass.states.get(entity_id) if entity_id else None
            return (
                state_temperature(state)
                if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
                else None
            )

        def raw(entity_id, attribute=None):
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return None
            return state.attributes.get(attribute) if attribute else state.state

        def target(entity_id, attribute=None):
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return None
            unit = state.attributes.get(
                "temperature_unit",
                state.attributes.get(
                    "unit_of_measurement", self.hass.config.units.temperature_unit
                ),
            )
            return celsius(state.attributes.get(attribute) if attribute else state.state, unit)

        return {
            "name": config["name"],
            "enabled": config["enabled"],
            "channels": deepcopy(self.status),
            "manual_dhw_boost": bool(self.runtime.get("manual_dhw_boost", False)),
            "return": temperature(config["return_sensor"]),
            "flow": temperature(config["flow_sensor"]),
            "mixed_flow": temperature(config["mixed_sensor"]),
            "dhw_temperature": target(config["dhw"]["entity"], "current_temperature"),
            "dhw_target": target(config["dhw"]["entity"], "temperature"),
            "heating_mode": raw(config["heating"]["entity"]),
            "correction": target(config["heating"]["correction_entity"])
            if config["heating"]["correction_entity"]
            else target(config["heating"]["entity"], "temperature"),
            "end": target(config["heating"]["end_entity"]),
            "shift": target(config["heating"]["shift_entity"]),
            "mixed_end": target(config["mixed_end_entity"]),
            "mixed_shift": target(config["mixed_shift_entity"]),
        }

    async def async_shutdown(self):
        self.close()
        async with self._lock:
            # Keep persisted ownership and targets across reloads and restarts.
            # Baselines are restored explicitly when automation is disabled.
            pass

    async def async_set_mixed_curve(self, end, shift, revision):
        async with self.manager._lock:
            self.manager._check_revision(revision)
            async with self._lock:
                commands = [
                    self._temperature_command(self.config["mixed_end_entity"], end, "number"),
                    self._temperature_command(self.config["mixed_shift_entity"], shift, "number"),
                ]
                for _entity_id, domain, service, data, current, key in commands:
                    if current != data[key]:
                        async with asyncio.timeout(SERVICE_TIMEOUT):
                            await self.hass.services.async_call(
                                domain, service, data, blocking=True
                            )
        self.manager.notify()
