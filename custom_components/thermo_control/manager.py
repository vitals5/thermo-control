"""Persistent room management independent of Home Assistant config flows."""

from __future__ import annotations

import asyncio
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

from .configuration import validate_room
from .const import CONF_TRVS, DEFAULTS, DEVICE_DEFAULTS, DOMAIN

if TYPE_CHECKING:
    from .climate import ThermoControlClimate

SIGNAL_ROOMS = f"{DOMAIN}_rooms_updated"


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

    def _payload(self, rooms: dict[str, Any], revision: int) -> dict[str, Any]:
        return {
            "rooms": rooms,
            "revision": revision,
            "migrated_entries": sorted(self._migrated_entries),
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
                coordinator = ThermoControlCoordinator(self.hass, RoomConfig(room_id, config))
                await coordinator.async_initialize()
                self.entities[room_id] = ThermoControlClimate(coordinator, manager=self)
            add_entities(list(self.entities.values()))
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
            room_id = room_id or uuid4().hex
            previous = self.entities.get(room_id)
            coordinator = ThermoControlCoordinator(self.hass, RoomConfig(room_id, validated))
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
                coordinator.window_blocked = previous.coordinator.window_blocked
                coordinator._calibration = deepcopy(previous.coordinator._calibration)
                low, high = coordinator.temperature_limits()
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
        async_dispatcher_send(self.hass, SIGNAL_ROOMS)

    @callback
    def snapshot(self) -> dict[str, Any]:
        return {
            "defaults": deepcopy(DEFAULTS),
            "device_defaults": deepcopy(DEVICE_DEFAULTS),
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
        for entity in list(self.entities.values()):
            await entity.coordinator.async_shutdown()
