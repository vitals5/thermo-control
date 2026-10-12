"""Unit tests for button, binary_sensor, switch, number, and sensor platforms."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.thermo_control import binary_sensor, button, number, sensor, switch


async def test_button_platform_entities(manager):
    added = []
    entry = MagicMock()
    entry.runtime_data = manager
    await button.async_setup_entry(manager.hass, entry, added.extend)
    assert len(added) == 3

    boost_btn, cancel_btn, valve_btn = added
    assert boost_btn.unique_id == "thermo_control_dhw_boost"
    assert cancel_btn.unique_id == "thermo_control_dhw_boost_cancel"
    assert valve_btn.unique_id == "thermo_control_valve_maintenance_trigger"

    # Turn heat pump on so boost button does not raise
    manager.settings["heat_pump_control"]["enabled"] = True
    manager.settings["heat_pump_control"]["dhw"]["enabled"] = True

    await boost_btn.async_press()
    assert manager.heat_pump.runtime.get("manual_dhw_boost") is True

    await cancel_btn.async_press()
    assert manager.heat_pump.runtime.get("manual_dhw_boost") is False

    await valve_btn.async_press()


async def test_binary_sensor_platform_entities(manager):
    added = []
    entry = MagicMock()
    entry.runtime_data = manager
    await binary_sensor.async_setup_entry(manager.hass, entry, added.extend)
    assert len(added) == 5

    dhw_bs, compressor_bs, permit_bs, pv_bs, req_bs = added
    assert dhw_bs.unique_id == "thermo_control_dhw_boost_active"
    assert dhw_bs.is_on is False

    manager.heat_pump.runtime["manual_dhw_boost"] = True
    assert dhw_bs.is_on is True

    assert compressor_bs.unique_id == "thermo_control_heat_pump_compressor"
    assert permit_bs.unique_id == "thermo_control_heat_pump_heat_permit"
    assert pv_bs.unique_id == "thermo_control_heat_pump_pv_signal"
    assert req_bs.unique_id == "thermo_control_heat_requested"


async def test_switch_platform_entities(manager, hass):
    config = manager.settings["heat_pump_control"]
    config["heating"].update(
        entity="climate.pump_heating",
        end_entity="number.pump_end",
        shift_entity="number.pump_shift",
    )
    config["dhw"].update(entity="water_heater.pump_water")
    hass.states.async_set(config["heating"]["entity"], "heat")
    hass.states.async_set(config["heating"]["end_entity"], "32")
    hass.states.async_set(config["heating"]["shift_entity"], "21")
    hass.states.async_set(config["dhw"]["entity"], "heat_pump")

    added = []
    entry = MagicMock()
    entry.runtime_data = manager
    await switch.async_setup_entry(manager.hass, entry, added.extend)
    assert len(added) == 5

    hp_master, hp_heating, hp_dhw, hp_interlock, valve_sw = added

    # Master switch
    assert hp_master.is_on is False
    await hp_master.async_turn_on()
    assert manager.settings["heat_pump_control"]["enabled"] is True
    assert hp_master.is_on is True
    await hp_master.async_turn_off()
    assert manager.settings["heat_pump_control"]["enabled"] is False

    # Heating switch
    assert hp_heating.is_on is True
    await hp_heating.async_turn_off()
    assert manager.settings["heat_pump_control"]["heating"]["enabled"] is False
    await hp_heating.async_turn_on()
    assert manager.settings["heat_pump_control"]["heating"]["enabled"] is True

    # DHW switch
    assert hp_dhw.is_on is True
    await hp_dhw.async_turn_off()
    assert manager.settings["heat_pump_control"]["dhw"]["enabled"] is False
    await hp_dhw.async_turn_on()
    assert manager.settings["heat_pump_control"]["dhw"]["enabled"] is True

    # Interlock switch
    manager.settings["heat_pump"]["flow_sensor"] = "sensor.pump_flow"
    manager.settings["heat_pump"]["mode_entity"] = "climate.pump_heating"
    assert hp_interlock.is_on is False
    await hp_interlock.async_turn_on()
    assert manager.settings["heat_pump"]["interlock"] is True
    assert hp_interlock.is_on is True
    await hp_interlock.async_turn_off()
    assert manager.settings["heat_pump"]["interlock"] is False
    assert hp_interlock.is_on is False

    # Valve maintenance switch
    assert valve_sw.is_on is False
    await valve_sw.async_turn_on()
    assert manager.settings["valve_maintenance"]["enabled"] is True
    assert valve_sw.is_on is True
    await valve_sw.async_turn_off()
    assert manager.settings["valve_maintenance"]["enabled"] is False
    assert valve_sw.is_on is False


async def test_number_platform_entities(manager):
    added = []
    entry = MagicMock()
    entry.runtime_data = manager
    await number.async_setup_entry(manager.hass, entry, added.extend)
    assert len(added) == 7

    offset, dhw_std, dhw_boost, dhw_block, curve_end, curve_shift, curve_corr = added

    # Master offset
    assert offset.native_value == 0.0
    await offset.async_set_native_value(1.5)
    assert manager.settings["master_offset"] == 1.5

    # DHW setpoints
    assert dhw_std.native_value == 42.0
    await dhw_std.async_set_native_value(45.0)
    assert manager.settings["heat_pump_control"]["dhw"]["profiles"]["standard"] == 45.0

    assert dhw_boost.native_value == 55.0
    await dhw_boost.async_set_native_value(58.0)
    assert manager.settings["heat_pump_control"]["dhw"]["profiles"]["boost"] == 58.0

    assert dhw_block.native_value == 30.0
    await dhw_block.async_set_native_value(32.0)
    assert manager.settings["heat_pump_control"]["dhw"]["profiles"]["blocked"] == 32.0

    # Heating curve
    assert curve_end.native_value == 32.0
    await curve_end.async_set_native_value(35.0)
    assert manager.settings["heat_pump_control"]["heating"]["profiles"]["standard"]["end"] == 35.0

    assert curve_shift.native_value == 21.0
    await curve_shift.async_set_native_value(23.0)
    assert manager.settings["heat_pump_control"]["heating"]["profiles"]["standard"]["shift"] == 23.0

    assert curve_corr.native_value == 0.0
    await curve_corr.async_set_native_value(2.0)
    assert (
        manager.settings["heat_pump_control"]["heating"]["profiles"]["standard"]["correction"]
        == 2.0
    )


async def test_expanded_sensor_platform_entities(manager):
    added = []
    entry = MagicMock()
    entry.runtime_data = manager
    await sensor.async_setup_entry(manager.hass, entry, added.extend)
    # 2 demand + 2 pump control + 3 statistics + 6 heat pump temperature sensors = 13 sensors
    assert len(added) == 13

    unique_ids = {s.unique_id for s in added}
    assert "thermo_control_demand" in unique_ids
    assert "thermo_control_eligible_demand" in unique_ids
    assert "thermo_control_heat_pump_heating" in unique_ids
    assert "thermo_control_heat_pump_dhw" in unique_ids
    assert "thermo_control_mean_demand" in unique_ids
    assert "thermo_control_heating_rooms" in unique_ids
    assert "thermo_control_demand_rooms" in unique_ids
    assert "thermo_control_heat_pump_flow" in unique_ids
    assert "thermo_control_heat_pump_return" in unique_ids
    assert "thermo_control_heat_pump_mixed_flow" in unique_ids
    assert "thermo_control_heat_pump_target" in unique_ids
    assert "thermo_control_heat_pump_dhw_temperature" in unique_ids
    assert "thermo_control_heat_pump_dhw_target" in unique_ids
