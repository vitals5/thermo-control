"""Deterministic time-series tests for predictive control and anti-cycling."""

from copy import deepcopy

import pytest

from custom_components.thermo_control.const import CONTROL_DEFAULTS
from custom_components.thermo_control.control import FloorController


def test_rising_floor_pre_shutoff_before_setpoint():
    controller = FloorController()
    config = deepcopy(CONTROL_DEFAULTS)
    assert controller.update(10000, 20, 22, True, config)
    for minute in range(1, 11):
        controller.update(10000 + minute * 60, 20 + minute * 0.02, 22, True, config)
    assert controller.rate == pytest.approx(1.2)
    assert controller.predicted == pytest.approx(22.6)
    assert controller.pre_shutoff
    assert not controller.active
    assert controller.demand == 0
    assert controller.samples[-1][1] < 22


def test_flat_floor_pwm_latches_duty_and_uses_long_cycles():
    controller = FloorController()
    config = {**CONTROL_DEFAULTS, "lookahead": 0}
    assert controller.update(10000, 20, 21, True, config)
    assert controller.cycle_duty == pytest.approx(0.5)
    for minute in range(1, 46):
        controller.update(10000 + minute * 60, 20, 21, True, config)
        if minute < 23:
            assert controller.active
        elif minute < 45:
            assert not controller.active
    assert controller.active  # Next cycle starts after 45 minutes, not each measurement.
    assert controller.rate == pytest.approx(0)
    assert controller.integral > 0


def test_minimum_dwell_and_safety_override():
    controller = FloorController()
    config = {**CONTROL_DEFAULTS, "lookahead": 0}
    assert controller.update(10000, 20, 21, True, config)
    assert controller.update(10030, 22, 21, True, config)  # Overshoot, but minimum on wins.
    assert not controller.update(10300, 22, 21, True, config)
    assert not controller.update(10330, 20, 21, True, config)  # Minimum rest wins.
    assert controller.update(10601, 20, 21, True, config)
    assert not controller.update(10602, 20, 21, False, config)  # A window/off overrides on time.
    assert controller.demand == 0
    assert controller.integral == 0


def test_interlock_keeps_need_visible_and_resets_windup():
    controller = FloorController()
    for minute in range(120):
        assert not controller.update(
            10000 + minute * 60, 18, 21, True, CONTROL_DEFAULTS, permitted=False
        )
    assert controller.integral == 0
    assert controller.demand == 1
    assert controller.update(17260, 18, 21, True, CONTROL_DEFAULTS)


def test_restart_preserves_dwell_and_discards_old_or_invalid_history():
    controller = FloorController()
    controller.update(10000, 20, 21, True, CONTROL_DEFAULTS)
    restored = FloorController()
    restored.restore(controller.dump(), 10030)
    assert restored.active
    assert restored.switched_at == 10000
    assert restored.update(10060, 22, 21, True, CONTROL_DEFAULTS)
    assert not restored.update(10300, 22, 21, True, CONTROL_DEFAULTS)
    bad = FloorController()
    bad.restore(
        {
            "samples": [
                [1, 20],
                [10001, float("nan")],
                [999999, 20],
                [10000, 20],
                [10000, 22],
                "bad",
                [10001],
            ],
            "integral": float("inf"),
            "switched_at": 999999,
        },
        10030,
    )
    assert list(bad.samples) == [(10000, 20)]
    assert bad.integral == 0
    assert bad.switched_at == 10030


def test_missing_reading_and_long_gap_reset_trend():
    controller = FloorController()
    for minute in range(61):
        controller.update(10000 + minute * 60, 20 + minute / 1000, 25, True, CONTROL_DEFAULTS)
    assert len(controller.samples) <= 46
    assert controller.rate is not None
    assert not controller.update(14000, None, 25, True, CONTROL_DEFAULTS)
    assert controller.rate is None
    assert not controller.samples
    controller.update(14060, 20, 25, True, CONTROL_DEFAULTS)
    controller.update(18000, 20, 25, True, CONTROL_DEFAULTS)
    assert len(controller.samples) == 1
    assert controller.rate is None


def test_small_demand_skips_short_pulses_and_setpoint_change_restarts_cycle():
    controller = FloorController()
    assert not controller.update(10000, 20.9, 21, True, CONTROL_DEFAULTS)
    assert controller.cycle_duty == 0
    assert controller.update(10001, 19, 22, True, CONTROL_DEFAULTS)
    assert controller.cycle_duty == 1
    assert controller.integral == 0


def test_rate_bounded_and_same_minute_reports_do_not_bias_regression():
    controller = FloorController()
    for minute in range(11):
        controller.update(10000 + minute * 60, 10 + minute, 30, True, CONTROL_DEFAULTS)
        controller.update(10001 + minute * 60, 10 + minute, 30, True, CONTROL_DEFAULTS)
    assert len(controller.samples) == 11
    assert controller.rate == 3
