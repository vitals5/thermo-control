"""The real HA flow creates one empty integration entry without any settings."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermo_control.const import DOMAIN, NAME


@pytest.fixture(autouse=True)
def mock_entry_setup(hass):
    with (
        patch.object(hass.config_entries, "async_setup", AsyncMock(return_value=True)),
        patch("homeassistant.components.frontend.async_setup", AsyncMock(return_value=True)),
    ):
        yield


async def test_confirm_only(hass):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert flow["type"] == FlowResultType.FORM
    assert flow["step_id"] == "user"
    assert flow["data_schema"].schema == {}
    assert hass.config_entries.async_entries(DOMAIN) == []
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {}
    assert result["result"].unique_id == DOMAIN
    assert result["result"].options == {}
    await hass.async_block_till_done()


@pytest.mark.parametrize("source", [SOURCE_USER, SOURCE_IMPORT])
async def test_no_duplicate_singleton(hass, source):
    MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}, data={} if source == SOURCE_IMPORT else None
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_legacy_entry_counts_as_existing(hass, entry):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_parallel_flows(hass):
    first = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    second = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert first["type"] == FlowResultType.FORM
    assert second["type"] == FlowResultType.ABORT
    assert second["reason"] == "already_in_progress"
    hass.config_entries.flow.async_abort(first["flow_id"])


async def test_empty_yaml_compatibility(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data={}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {}
    await hass.async_block_till_done()
