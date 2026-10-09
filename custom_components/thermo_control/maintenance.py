"""Daily valve exercise without changing room intent or requesting heat."""

from copy import deepcopy
from datetime import timedelta

from homeassistant.util import dt as dt_util


class ValveMaintenance:
    """Persist phases before commands; never resume an opening after restart."""

    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        self.state = {}

    @property
    def phase(self) -> str | None:
        return self.state.get("phase")

    def restore(self, stored: dict) -> None:
        self.state = deepcopy(stored)
        if self.phase:
            self.state.update(phase="restore", last_result="interrupted")

    def dump(self) -> dict:
        return deepcopy(self.state)

    async def _save(self, **changes) -> None:
        previous = self.state
        self.state = {**previous, **changes}
        try:
            await self.coordinator._store.async_save(self.coordinator._storage_data())
        except OSError:
            self.state = previous
            raise

    async def async_cancel(self, result: str = "interrupted") -> None:
        if self.phase and self.phase != "restore":
            await self._save(phase="restore", last_result=result)

    async def async_finish(self) -> None:
        if self.phase == "restore":
            await self._save(phase=None, until=None, completed_at=dt_util.utcnow().isoformat())

    async def async_update(self) -> float | None:
        """Return a temporary low/high setpoint fraction, or ordinary control."""
        coordinator = self.coordinator
        manager = coordinator.manager
        if manager is None:
            return None
        config = manager.settings["valve_maintenance"]
        eligible = (
            config["enabled"]
            and coordinator.config["valve_maintenance"]
            and not coordinator.native_auto
            and not coordinator._windows_open()
            and not coordinator.window_blocked
            and coordinator._room_temperature() is not None
            and all(
                (device := coordinator._state(entity_id)) is not None
                and not coordinator._is_auto(device)
                and "heat" in device.attributes.get("hvac_modes", [])
                for entity_id in coordinator.trvs
            )
        )
        if self.phase and not eligible:
            await self.async_cancel()
        if self.phase == "restore":
            return None
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        today = local.date().isoformat()
        if not self.phase:
            if (
                not eligible
                or (self.state.get("last_date") or "") >= today
                or local.strftime("%H:%M") < config["time"]
                or any(
                    entity.coordinator is not coordinator and entity.coordinator.maintenance.phase
                    for entity in manager.entities.values()
                )
            ):
                return None
            # Claim this room synchronously before awaiting storage. Other rooms
            # observe the phase and cannot begin their own exercise concurrently.
            await self._save(
                phase="close",
                last_date=today,
                last_result="running",
                duration=config["duration"],
                until=(now + timedelta(seconds=config["duration"])).isoformat(),
            )
        until = dt_util.parse_datetime(self.state.get("until") or "")
        if not until or now >= until + timedelta(seconds=self.state["duration"]):
            # Missed ticks or a suspended host must not extend an extreme setpoint.
            await self.async_cancel()
            return None
        if now >= until:
            if self.phase == "close":
                await self._save(
                    phase="open",
                    until=(now + timedelta(seconds=self.state["duration"])).isoformat(),
                )
            else:
                await self._save(phase="restore", last_result="completed")
                return None
        return 0.0 if self.phase == "close" else 1.0
