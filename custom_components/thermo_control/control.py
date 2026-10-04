"""Bounded predictive PI/PWM control; all time values are UTC epoch seconds."""

from collections import deque
from typing import Any

from .helpers import finite


class FloorController:
    """Estimate trend from minute samples and latch a duty fraction per cycle."""

    def __init__(self) -> None:
        self.samples: deque[tuple[float, float]] = deque(maxlen=62)
        self.integral = 0.0
        self.last_time: float | None = None
        self.cycle_start: float | None = None
        self.cycle_duty = 0.0
        self.active = False
        self.switched_at: float | None = None
        self.rate: float | None = None
        self.predicted: float | None = None
        self.demand = 0.0
        self.pre_shutoff = False
        self.last_target: float | None = None

    def restore(self, data: dict[str, Any], now: float) -> None:
        """Restore only finite, recent history; do not integrate downtime."""
        for sample in data.get("samples", []):
            if not isinstance(sample, (list, tuple)) or len(sample) != 2:
                continue
            timestamp, value = (finite(item) for item in sample)
            if timestamp is not None and value is not None and now - 3600 <= timestamp <= now:
                if not self.samples or timestamp > self.samples[-1][0]:
                    self.samples.append((timestamp, value))
        self.integral = max(-0.3, min(0.8, finite(data.get("integral")) or 0))
        self.active = data.get("active") is True
        switched = finite(data.get("switched_at"))
        self.switched_at = switched if switched is not None and switched <= now else now
        # Start a fresh cycle after restart but retain the minimum dwell time.

    def dump(self) -> dict[str, Any]:
        return {
            "samples": list(self.samples),
            "integral": self.integral,
            "active": self.active,
            "switched_at": self.switched_at,
        }

    def update(
        self,
        now: float,
        temperature: float | None,
        target: float,
        enabled: bool,
        config: dict[str, Any],
        *,
        permitted: bool = True,
    ) -> bool:
        elapsed = max(0, min(120, now - self.last_time)) if self.last_time is not None else 0
        self.last_time = now
        if self.last_target is not None and abs(target - self.last_target) >= config["tolerance"]:
            self.cycle_start = None
            self.integral = 0
        self.last_target = target
        if temperature is None:
            self.samples.clear()
        else:
            if self.samples and now - self.samples[-1][0] > 600:
                self.samples.clear()
            if not self.samples or now - self.samples[-1][0] >= 60:
                self.samples.append((now, temperature))
            while self.samples and self.samples[0][0] < now - config["trend_window"] * 60:
                self.samples.popleft()
        self.rate = None
        if len(self.samples) >= 3 and self.samples[-1][0] - self.samples[0][0] >= 600:
            origin = self.samples[0][0]
            xs = [(time - origin) / 3600 for time, _ in self.samples]
            ys = [value for _, value in self.samples]
            mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
            variance = sum((x - mean_x) ** 2 for x in xs)
            if variance:
                self.rate = max(
                    -3,
                    min(
                        3,
                        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
                        / variance,
                    ),
                )
        horizon = min(config["lookahead"], 120 * config["inertia"]) / 60
        self.predicted = (
            None if temperature is None else temperature + max(0, self.rate or 0) * horizon
        )
        self.pre_shutoff = bool(
            enabled
            and self.rate is not None
            and self.rate > 0.02
            and self.predicted >= target - config["tolerance"] / 2
        )
        if not enabled or temperature is None:
            self.demand = self.cycle_duty = 0
            self.integral = 0  # Freeze/reset windup during windows and source interlocks.
            self.cycle_start = None
            desired = False  # Explicit off, missing readings and windows override dwell.
        else:
            error = target - self.predicted
            delta = (
                error * elapsed / (config["integral_hours"] * 3600 * config["proportional_band"])
            )
            raw = error / config["proportional_band"] + self.integral
            if not permitted:
                self.integral = 0
            elif (0 < raw < 1) or (raw >= 1 and delta < 0) or (raw <= 0 and delta > 0):
                self.integral = max(-0.3, min(0.8, self.integral + delta))
            self.demand = (
                0
                if self.pre_shutoff
                else max(0, min(1, error / config["proportional_band"] + self.integral))
            )
            cycle = config["cycle_minutes"] * 60
            if (
                self.cycle_start is None
                or now - self.cycle_start >= cycle
                or now < self.cycle_start
            ):
                self.cycle_start = (
                    now if self.cycle_start is None else now - (now - self.cycle_start) % cycle
                )
                duty = self.demand
                if duty * cycle < config["minimum_on"]:
                    duty = 0
                elif (1 - duty) * cycle < config["minimum_off"]:
                    duty = 1
                self.cycle_duty = duty
            desired = (
                not self.pre_shutoff
                and temperature < target + config["tolerance"]
                and now - self.cycle_start < self.cycle_duty * cycle
            )
            minimum = config["minimum_on"] if self.active else config["minimum_off"]
            if (
                desired != self.active
                and self.switched_at is not None
                and now - self.switched_at < minimum
            ):
                desired = self.active
            if not permitted:
                desired = False
                self.cycle_start = None
        if desired != self.active:
            self.active, self.switched_at = desired, now
        return self.active
