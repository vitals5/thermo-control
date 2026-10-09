"""Persistent room management independent of Home Assistant config flows."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .configuration import validate_room, validate_settings
from .const import CONF_TRVS, DEFAULTS, DEVICE_DEFAULTS, DOMAIN, SYSTEM_DEFAULTS
from .schedule import ScheduleManager
from .system import HeatingSystem

if TYPE_CHECKING:
    from .climate import ThermoControlClimate

SIGNAL_ROOMS = f"{DOMAIN}_rooms_updated"
_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RoomConfig:
    """Minimal room identity shared with the existing control engine."""

    entry_id: str
    data: dict[str, Any]
    options: dict[str, Any] = field(default_factory=dict)


class RoomManager:
    """Serialize configuration edits and preserve room IDs and heating intent."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.rooms: dict[str, dict[str, Any]] = {}
        self.entities: dict[str, ThermoControlClimate] = {}
        self.revision = 0
        self.settings = deepcopy(SYSTEM_DEFAULTS)
        self.groups = {}
        self.system = HeatingSystem(self)
        self.schedules = ScheduleManager(self)
        self._reconcile_task = None
        self._reconcile_again = False
        self.config_entry_id: str | None = None
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.rooms")
        self._lock = asyncio.Lock()
        self._add_entities: AddEntitiesCallback | None = None
        self._closed = False
        self._migrated_entries: set[str] = set()

    async def async_initialize(self) -> None:
        if stored := await self._store.async_load():
            rooms = stored.get("rooms", {})
            validated: dict[str, dict[str, Any]] = {}
            for room_id, config in rooms.items():
                validated[room_id] = validate_room(
                    self.hass, config, validated, room_id, check_entities=False
                )
            self.rooms = validated
            self.revision = stored.get("revision", 0)
            self._migrated_entries = set(stored.get("migrated_entries", []))
            self.settings = validate_settings(
                self.hass, stored.get("settings", deepcopy(SYSTEM_DEFAULTS)), check_entities=False
            )
        await self.schedules.async_initialize()
        self.system.bind()

    def _payload(self, rooms: dict[str, Any], revision: int) -> dict[str, Any]:
        return {
            "rooms": rooms,
            "revision": revision,
            "migrated_entries": sorted(self._migrated_entries),
            "settings": self.settings,
        }

    async def async_import_legacy(self, entries: list[ConfigEntry]) -> None:
        """Import old rooms once, without starting or presenting a config flow."""
        candidate = dict(self.rooms)
        imported = set(self._migrated_entries)
        for entry in entries:
            if CONF_TRVS not in entry.data or entry.entry_id in imported:
                continue
            if entry.entry_id not in candidate:
                config = {**entry.data, **entry.options}
                candidate[entry.entry_id] = validate_room(
                    self.hass, config, candidate, entry.entry_id, check_entities=False
                )
            imported.add(entry.entry_id)
        if imported != self._migrated_entries:
            await self._store.async_save(
                {
                    "rooms": candidate,
                    "revision": self.revision + 1,
                    "migrated_entries": sorted(imported),
                    "settings": self.settings,
                }
            )
            self.rooms = candidate
            self._migrated_entries = imported
            self.revision += 1

    async def async_bind_platform(self, add_entities: AddEntitiesCallback) -> None:
        """The integration climate platform owns the dynamic virtual entities."""
        from .climate import ThermoControlClimate
        from .coordinator import ThermoControlCoordinator

        async with self._lock:
            self._add_entities = add_entities
            for room_id, config in self.rooms.items():
                registry = er.async_get(self.hass)
                registered_id = registry.async_get_entity_id("climate", DOMAIN, room_id)
                if (
                    registered_id
                    and registry.async_get(registered_id).config_entry_id in self._migrated_entries
                ):
                    registry.async_update_entity(
                        registered_id, config_entry_id=None, device_id=None
                    )
                coordinator = ThermoControlCoordinator(
                    self.hass, RoomConfig(room_id, config), manager=self
                )
                await coordinator.async_initialize()
                self.entities[room_id] = ThermoControlClimate(coordinator, manager=self)
            self.schedules.bind()
            add_entities(list(self.entities.values()))
            await self._sync_groups()
            self.notify()

    def _check_revision(self, revision: int) -> None:
        if revision != self.revision:
            raise ServiceValidationError(
                "Die Konfiguration wurde inzwischen geändert. Bitte neu laden."
            )
        if self._closed or self._add_entities is None:
            raise ServiceValidationError("Thermo Control ist noch nicht bereit.")

    async def async_save_room(
        self, config: dict[str, Any], revision: int, room_id: str | None = None
    ) -> str:
        from .climate import ThermoControlClimate
        from .coordinator import ThermoControlCoordinator

        async with self._lock:
            self._check_revision(revision)
            if room_id is not None and room_id not in self.rooms:
                raise ServiceValidationError("Der Raum existiert nicht mehr.")
            validated = validate_room(self.hass, config, self.rooms, room_id)
            if validated["group_id"] is not None and validated["group_id"] not in {
                group["id"] for group in self.settings["groups"]
            }:
                raise ServiceValidationError("Die Gruppe existiert nicht mehr.")
            room_id = room_id or uuid4().hex
            previous = self.entities.get(room_id)
            coordinator = ThermoControlCoordinator(
                self.hass, RoomConfig(room_id, validated), manager=self
            )
            await coordinator.async_initialize()
            candidate = {**self.rooms, room_id: validated}
            # Persist before publishing or removing a working room. Failed disk
            # writes leave the running room and its configuration untouched.
            await self._store.async_save(self._payload(candidate, self.revision + 1))
            if previous is not None:
                coordinator.mode = previous.coordinator.mode
                coordinator.target = previous.coordinator.target
                coordinator.manual_target = previous.coordinator.manual_target
                coordinator.preset = previous.coordinator.preset
                coordinator.maintenance.restore(previous.coordinator.maintenance.dump())
                coordinator.window_blocked = previous.coordinator.window_blocked
                coordinator._preheat_latch = deepcopy(previous.coordinator._preheat_latch)
                coordinator._calibration = deepcopy(previous.coordinator._calibration)
                coordinator.controller.restore(
                    previous.coordinator.controller.dump(), dt_util.utcnow().timestamp()
                )
                low, high = coordinator.base_temperature_limits()
                coordinator.target = min(high, max(low, coordinator.target))
                coordinator.manual_target = min(high, max(low, coordinator.manual_target))
                if getattr(previous, "hass", None) is not None:
                    await previous.async_remove()
                else:
                    await previous.coordinator.async_shutdown()
            self.rooms = candidate
            self.revision += 1
            entity = self.entities[room_id] = ThermoControlClimate(
                coordinator, manager=self, restore=previous is None
            )
            self._add_entities([entity])
            self.notify()
            return room_id

    async def async_delete_room(self, room_id: str, revision: int) -> None:
        async with self._lock:
            self._check_revision(revision)
            if room_id not in self.rooms:
                raise ServiceValidationError("Der Raum existiert nicht mehr.")
            candidate = {key: value for key, value in self.rooms.items() if key != room_id}
            await self._store.async_save(self._payload(candidate, self.revision + 1))
            entity = self.entities.pop(room_id)
            if getattr(entity, "hass", None) is not None:
                await entity.async_remove()
            else:
                await entity.coordinator.async_shutdown()
            registry = er.async_get(self.hass)
            if entity.entity_id and (registered := registry.async_get(entity.entity_id)):
                device_id = registered.device_id
                registry.async_remove(entity.entity_id)
                if device_id and not er.async_entries_for_device(registry, device_id):
                    dr.async_get(self.hass).async_remove_device(device_id)
            await entity.coordinator._store.async_remove()
            self.rooms = candidate
            self.revision += 1
            self.notify()

    @callback
    def notify(self) -> None:
        if not self._closed:
            async_dispatcher_send(self.hass, SIGNAL_ROOMS)

    def control_for(self, config: dict[str, Any]) -> dict[str, Any]:
        result = dict(config)
        if config["heating_type"] == "floor" and config["use_global_control"]:
            result.update(self.settings["control"])
        group = next(
            (item for item in self.settings["groups"] if item["id"] == config["group_id"]), None
        )
        if group and config["heating_type"] == "floor":
            result.update(group["control"])
        return result

    @callback
    def schedule_reconcile(self) -> None:
        if self._closed:
            return
        self._reconcile_again = True
        if self._reconcile_task is None or self._reconcile_task.done():
            self._reconcile_task = self.hass.async_create_task(
                self.async_reconcile(), "thermo_control system change"
            )

    async def async_reconcile(self) -> None:
        while self._reconcile_again and not self._closed:
            self._reconcile_again = False
            for entity in list(self.entities.values()):
                try:
                    await entity.coordinator._tick()
                except OSError:
                    _LOGGER.exception(
                        "Control state could not be persisted; hardware command withheld"
                    )
            self.notify()

    async def async_save_settings(self, config: dict[str, Any], revision: int) -> None:
        async with self._lock:
            self._check_revision(revision)
            validated = validate_settings(self.hass, config)
            ids = {group["id"] for group in validated["groups"]}
            if any(
                room["group_id"] and room["group_id"] not in ids for room in self.rooms.values()
            ):
                raise ServiceValidationError(
                    "Vor dem Löschen einer Gruppe ihre Räume neu zuordnen."
                )
            await self._store.async_save(
                {**self._payload(self.rooms, self.revision + 1), "settings": validated}
            )
            self.settings = validated
            self.revision += 1
            self.system.bind()
            await self._sync_groups()
            self.notify()
            self.schedule_reconcile()

    async def async_set_master_offset(self, offset: float) -> None:
        # Read the latest document and revision under the same edit lock.
        async with self._lock:
            self._check_revision(self.revision)
            settings = validate_settings(
                self.hass, {**self.settings, "master_offset": offset}, check_entities=False
            )
            await self._store.async_save(
                {**self._payload(self.rooms, self.revision + 1), "settings": settings}
            )
            self.settings = settings
            self.revision += 1
            self.notify()
            self.schedule_reconcile()

    async def _sync_groups(self) -> None:
        from .groups import ThermoControlGroup

        configured = {group["id"]: group for group in self.settings["groups"]}
        for group_id in list(self.groups):
            entity = self.groups[group_id]
            if group_id not in configured:
                if getattr(entity, "hass", None):
                    await entity.async_remove()
                if entity.entity_id and er.async_get(self.hass).async_get(entity.entity_id):
                    er.async_get(self.hass).async_remove(entity.entity_id)
                del self.groups[group_id]
            else:
                entity._attr_name = configured[group_id]["name"]
        for group_id, config in configured.items():
            if group_id not in self.groups:
                entity = self.groups[group_id] = ThermoControlGroup(self, group_id, config["name"])
                self._add_entities([entity])

    @callback
    def snapshot(self) -> dict[str, Any]:
        return {
            **self.schedules.snapshot(),
            "defaults": deepcopy(DEFAULTS),
            "device_defaults": deepcopy(DEVICE_DEFAULTS),
            "settings": deepcopy(self.settings),
            "system_defaults": deepcopy(SYSTEM_DEFAULTS),
            "system": self.system.snapshot(),
            "groups": [
                {"id": group_id, "entity_id": group.entity_id}
                for group_id, group in self.groups.items()
            ],
            "revision": self.revision,
            "rooms": [
                {
                    "id": room_id,
                    "config": deepcopy(config),
                    "entity_id": self.entities[room_id].entity_id
                    if room_id in self.entities
                    else None,
                }
                for room_id, config in self.rooms.items()
            ],
        }

    async def async_shutdown(self) -> None:
        self._closed = True
        self.system.close()
        self.schedules.close()
        if self._reconcile_task and not self._reconcile_task.done():
            self._reconcile_task.cancel()
            await asyncio.gather(self._reconcile_task, return_exceptions=True)
        for entity in list(self.entities.values()):
            await entity.coordinator.async_shutdown()
