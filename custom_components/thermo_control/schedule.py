"""Validated weekly wall-clock schedules, persistent overrides and FBH anticipation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .helpers import finite

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_MINUTES = 1440
WEEK_MINUTES = 10080


def minutes(value: Any, *, end: bool = False) -> int:
    if end and value == "24:00":
        return DAY_MINUTES
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ServiceValidationError("Zeiten benötigen HH:MM; 24:00 ist nur als Ende erlaubt.")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def plan_key(plan: dict) -> str:
    return f"room:{plan['room_id']}" if "room_id" in plan else f"group:{plan['group_id']}"


def validate_plan(plan: dict, manager, *, check_owner: bool = True) -> dict:
    allowed = {
        "room_id",
        "group_id",
        "enabled",
        "weekdays",
        "fallback_temp",
        "override_hours",
        "preheat",
        "heating_rate",
        "max_preheat_minutes",
    }
    if (
        not isinstance(plan, dict)
        or set(plan) - allowed
        or ("room_id" in plan) == ("group_id" in plan)
    ):
        raise ServiceValidationError("Ein Plan benötigt genau eine Raum- oder Gruppenzuordnung.")
    owner = "room_id" if "room_id" in plan else "group_id"
    owner_id = plan[owner]
    if not isinstance(owner_id, str) or not owner_id or len(owner_id) > 100:
        raise ServiceValidationError("Ungültige Zeitplanzuordnung.")
    if check_owner and (
        owner_id not in manager.rooms
        if owner == "room_id"
        else owner_id not in {g["id"] for g in manager.settings["groups"]}
    ):
        raise ServiceValidationError("Der Raum oder die Gruppe existiert nicht mehr.")
    result = {
        owner: owner_id,
        "enabled": plan.get("enabled", False),
        "weekdays": {day: [] for day in DAYS},
        "preheat": plan.get("preheat", False),
    }
    if type(result["enabled"]) is not bool or type(result["preheat"]) is not bool:
        raise ServiceValidationError("Aktivierung und Vorheizen benötigen Wahrheitswerte.")
    for key, default, low, high in [
        ("fallback_temp", 18, 5, 30),
        ("override_hours", 0, 0, 48),
        ("heating_rate", 0.5, 0.1, 5),
        ("max_preheat_minutes", 180, 0, 360),
    ]:
        value = finite(plan.get(key, default))
        if value is None or not low <= value <= high or (key == "fallback_temp" and value * 2 % 1):
            raise ServiceValidationError(f"Ungültiger Zeitplanparameter: {key}.")
        result[key] = value
    weekdays = plan.get("weekdays", {})
    if not isinstance(weekdays, dict) or set(weekdays) - set(DAYS):
        raise ServiceValidationError("Ungültige Wochentage.")
    intervals = []
    for index, day in enumerate(DAYS):
        blocks = weekdays.get(day, [])
        if not isinstance(blocks, list) or len(blocks) > 48:
            raise ServiceValidationError("Höchstens 48 Blöcke je Tag sind erlaubt.")
        for block in blocks:
            if not isinstance(block, dict) or set(block) != {"from", "to", "temp"}:
                raise ServiceValidationError("Ein Block benötigt from, to und temp.")
            start, end = minutes(block["from"]), minutes(block["to"], end=True)
            temperature = finite(block["temp"])
            if (
                start == end
                or temperature is None
                or not 5 <= temperature <= 30
                or temperature * 2 % 1
            ):
                raise ServiceValidationError(
                    "Blöcke benötigen eine Dauer und 5–30 °C in 0,5-°C-Schritten."
                )
            end += DAY_MINUTES if end < start else 0
            absolute_start, absolute_end = index * DAY_MINUTES + start, index * DAY_MINUTES + end
            intervals.append((absolute_start, min(absolute_end, WEEK_MINUTES)))
            if absolute_end > WEEK_MINUTES:
                intervals.append((0, absolute_end - WEEK_MINUTES))
            result["weekdays"][day].append(
                {"from": block["from"], "to": block["to"], "temp": temperature}
            )
        result["weekdays"][day].sort(key=lambda block: minutes(block["from"]))
    intervals.sort()
    if any(right[0] < left[1] for left, right in zip(intervals, intervals[1:], strict=False)):
        raise ServiceValidationError("Zeitblöcke überschneiden sich, auch über Mitternacht.")
    if check_owner:
        room_ids = (
            [owner_id]
            if owner == "room_id"
            else [rid for rid, room in manager.rooms.items() if room["group_id"] == owner_id]
        )
        targets = [
            result["fallback_temp"],
            *[b["temp"] for blocks in result["weekdays"].values() for b in blocks],
        ]
        for rid in room_ids:
            entity = manager.entities.get(rid)
            if entity and any(not entity.min_temp <= value <= entity.max_temp for value in targets):
                raise ServiceValidationError(
                    "Zeitplan liegt außerhalb der Temperaturgrenzen eines Raums."
                )
    return result


def templates() -> dict:
    profiles = {
        "standard_fbh": (
            "Standard FBH",
            [("00:00", "06:00", 19), ("06:00", "22:00", 21.5), ("22:00", "24:00", 19)],
        ),
        "homeoffice": (
            "Homeoffice",
            [
                ("00:00", "06:00", 18),
                ("06:00", "08:30", 21),
                ("08:30", "17:00", 21.5),
                ("17:00", "22:00", 21),
                ("22:00", "24:00", 18),
            ],
        ),
        "away": ("Abwesend", [("00:00", "24:00", 18)]),
    }
    return {
        key: {
            "name": name,
            "weekdays": {
                day: [{"from": start, "to": end, "temp": temp} for start, end, temp in blocks]
                for day in DAYS
            },
        }
        for key, (name, blocks) in profiles.items()
    }


def wall_time(day, minute: int, zone) -> datetime:
    """Choose the first fold; collapse nonexistent spring times onto the next real minute."""
    value = datetime.combine(day, time(), zone) + timedelta(minutes=minute)
    # Collapse the missing spring hour onto the first real local minute, keeping
    # adjacent window boundaries ordered instead of creating overlaps.
    while dt_util.as_utc(value).astimezone(zone).replace(tzinfo=None) != value.replace(tzinfo=None):
        value += timedelta(minutes=1)
    return dt_util.as_utc(value)


def evaluate(
    plan: dict,
    now: datetime,
    room_temp: float | None = None,
    *,
    floor: bool = False,
    offset: float = 0,
    lookahead: float = 360,
) -> dict:
    local = dt_util.as_local(now)
    now = dt_util.as_utc(now)
    intervals = []
    for shift in range(-1, 9):
        day = local.date() + timedelta(days=shift)
        for block in plan["weekdays"][DAYS[day.weekday()]]:
            start, end = minutes(block["from"]), minutes(block["to"], end=True)
            end += DAY_MINUTES if end < start else 0
            intervals.append(
                (
                    wall_time(day, start, local.tzinfo),
                    wall_time(day, end, local.tzinfo),
                    block["temp"],
                )
            )

    def target_at(moment):
        return next(
            (temp for start, end, temp in intervals if start <= moment < end), plan["fallback_temp"]
        )

    boundaries = sorted(
        {point for start, end, _ in intervals for point in (start, end) if point > now}
    )
    # Only actual temperature changes are switching points (midnight seams don't end overrides).
    changes = [
        (point, target_at(point))
        for point in boundaries
        if target_at(point - timedelta(microseconds=1)) != target_at(point)
    ]
    scheduled = target_at(now)
    target, preheating = scheduled, False
    next_change = changes[0][0] if changes else None
    if floor and plan["preheat"] and room_temp is not None:
        for point, future in changes:
            if future <= scheduled:
                continue
            lead = min(
                plan["max_preheat_minutes"],
                lookahead,
                max(0, (future + offset - room_temp) / plan["heating_rate"] * 60),
            )
            if 0 < (point - now).total_seconds() <= lead * 60:
                target, preheating, next_change = future, True, point
            break
    return {
        "target": target,
        "scheduled_target": scheduled,
        "next_change": next_change.isoformat() if next_change else None,
        "preheating": preheating,
    }


class ScheduleManager:
    def __init__(self, manager) -> None:
        self.manager = manager
        self.plans: dict[str, dict] = {}
        self.runtime: dict[str, dict] = {}
        self.revision = 0
        self._lock = asyncio.Lock()
        self._store = Store(manager.hass, 1, "thermo_control_schedules")
        self._unsubscribe = None

    async def async_initialize(self) -> None:
        if stored := await self._store.async_load():
            self.plans = {
                key: validate_plan(plan, self.manager, check_owner=False)
                for key, plan in stored.get("plans", {}).items()
            }
            self.runtime = stored.get("runtime", {})
            self.revision = stored.get("revision", 0)

    def bind(self) -> None:
        if self._unsubscribe is not None:
            return
        self._unsubscribe = async_track_utc_time_change(
            self.manager.hass, self._minute_elapsed, second=0
        )

    @callback
    def _minute_elapsed(self, now) -> None:
        if any(plan["enabled"] for plan in self.plans.values()):
            self.manager.schedule_reconcile()

    def close(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def snapshot(self) -> dict:
        return {
            "schedules": deepcopy(list(self.plans.values())),
            "schedule_revision": self.revision,
            "schedule_templates": templates(),
            "time_zone": self.manager.hass.config.time_zone,
        }

    def plan_for(self, room_id: str) -> dict | None:
        room = self.manager.rooms.get(room_id)
        if room is None:
            return None
        return self.plans.get(f"room:{room_id}") or self.plans.get(f"group:{room['group_id']}")

    def state_for(self, coordinator) -> dict:
        rid = coordinator.entry.entry_id
        plan = self.plan_for(rid)
        runtime = self.runtime.get(rid, {})
        if (
            not plan
            or not plan["enabled"]
            or runtime.get("manual")
            or coordinator.mode != "heat"
            or coordinator.native_auto
        ):
            return {"schedule_active": False, "schedule_available": plan is not None}
        now = dt_util.utcnow()
        result = evaluate(
            plan,
            now,
            coordinator._room_temperature(),
            floor=coordinator.config["heating_type"] == "floor",
            offset=self.manager.settings["master_offset"],
            lookahead=coordinator.control_config()["lookahead"],
        )
        until = dt_util.parse_datetime(runtime.get("until", ""))
        override = bool(until and until > now and runtime.get("plan_key") == plan_key(plan))
        if override:
            result.update(target=runtime["target"], preheating=False)
        return {
            **result,
            "schedule_active": True,
            "schedule_available": True,
            "schedule_key": plan_key(plan),
            "schedule_signature": hashlib.sha256(
                json.dumps(plan, sort_keys=True).encode()
            ).hexdigest(),
            "schedule_override": override,
            "schedule_until": runtime["until"] if override else result["next_change"],
        }

    async def _persist(self, plans, runtime, *, configuration: bool = True) -> None:
        await self._store.async_save(
            {"plans": plans, "runtime": runtime, "revision": self.revision + int(configuration)}
        )
        self.plans, self.runtime = plans, runtime
        self.revision += int(configuration)
        self.manager.notify()

    def _check(self, revision: int) -> None:
        if revision != self.revision or self.manager._closed or self.manager._add_entities is None:
            raise ServiceValidationError("Zeitpläne wurden inzwischen geändert. Bitte neu laden.")

    async def async_save(self, plan: dict, revision: int) -> None:
        async with self._lock:
            self._check(revision)
            plan = validate_plan(plan, self.manager)
            key = plan_key(plan)
            old = self.plans.get(key)
            activate = plan["enabled"] and (not old or not old["enabled"])
            runtime = deepcopy(self.runtime)
            affected = [
                rid
                for rid in self.manager.rooms
                if plan_key(self.plans.get(f"room:{rid}", plan)) == key
                and (
                    "room_id" in plan
                    and rid == plan["room_id"]
                    or "group_id" in plan
                    and self.manager.rooms[rid]["group_id"] == plan["group_id"]
                )
            ]
            if activate:
                for rid in affected:
                    if not self.manager.entities[rid].coordinator.supports_mode("heat"):
                        raise ServiceValidationError(
                            "Zeitpläne benötigen einen temperaturregelnden heat-Modus."
                        )
                    runtime[rid] = {"manual": False}
            await self._persist({**self.plans, key: plan}, runtime)
        if activate:
            for rid in affected:
                await self.manager.entities[rid].coordinator.async_set_intent(mode="heat")
        self.manager.schedule_reconcile()

    async def async_room_active(self, rid: str, active: bool) -> None:
        async with self._lock:
            plan = self.plan_for(rid)
            if active and not plan:
                raise ServiceValidationError(
                    "Zuerst einen Zeitplan für den Raum oder seine Gruppe anlegen."
                )
            if (
                rid not in self.manager.entities
                or active
                and not self.manager.entities[rid].coordinator.supports_mode("heat")
            ):
                raise ServiceValidationError(
                    "Zeitpläne benötigen einen verfügbaren Raum mit heat-Unterstützung."
                )
            plans = deepcopy(self.plans)
            if active or plan and "room_id" in plan:
                plans[plan_key(plan)]["enabled"] = active
            await self._persist(
                plans,
                {**self.runtime, rid: {"manual": not active}},
                configuration=plans != self.plans,
            )
        self.manager.schedule_reconcile()

    async def async_override(self, coordinator, target: float) -> None:
        async with self._lock:
            state = self.state_for(coordinator)
            if not state["schedule_active"]:
                return
            plan = self.plan_for(coordinator.entry.entry_id)
            until = (
                (dt_util.utcnow() + timedelta(hours=plan["override_hours"])).isoformat()
                if plan["override_hours"]
                else state["next_change"]
            )
            if not until:
                # A constant weekly plan has no switch: explicit bounded fallback.
                until = (dt_util.utcnow() + timedelta(hours=24)).isoformat()
            await self._persist(
                deepcopy(self.plans),
                {
                    **self.runtime,
                    coordinator.entry.entry_id: {
                        "manual": False,
                        "target": target,
                        "until": until,
                        "plan_key": plan_key(plan),
                    },
                },
                configuration=False,
            )

    async def async_copy(
        self,
        source: str,
        targets: list[str],
        revision: int,
        *,
        source_day: str | None = None,
        target_days: list[str] | None = None,
    ) -> None:
        async with self._lock:
            self._check(revision)
            if source_day is None and source in targets:
                raise ServiceValidationError("Eine Wochenkopie benötigt ein anderes Ziel.")
            if (
                source not in self.plans
                or not targets
                or len(targets) > 100
                or source_day is not None
                and source_day not in DAYS
                or target_days is not None
                and (not target_days or set(target_days) - set(DAYS))
            ):
                raise ServiceValidationError("Ungültige Kopierauswahl.")
            if (source_day is None) != (target_days is None):
                raise ServiceValidationError("Tageskopien benötigen Quelltag und Zieltage.")
            original = self.plans[source]
            candidates = deepcopy(self.plans)
            for target in targets:
                kind, separator, owner_id = target.partition(":")
                if separator != ":" or kind not in ("room", "group"):
                    raise ServiceValidationError("Ungültiges Kopierziel.")
                if source_day is None:
                    plan = {**deepcopy(original), "enabled": False}
                    plan.pop("room_id", None)
                    plan.pop("group_id", None)
                    plan[f"{kind}_id"] = owner_id
                else:
                    plan = deepcopy(
                        candidates.get(
                            target, {f"{kind}_id": owner_id, "enabled": False, "weekdays": {}}
                        )
                    )
                    for day in target_days:
                        plan["weekdays"][day] = deepcopy(original["weekdays"][source_day])
                candidates[target] = validate_plan(plan, self.manager)
            await self._persist(candidates, deepcopy(self.runtime))
        self.manager.schedule_reconcile()
