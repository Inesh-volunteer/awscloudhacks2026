"""
Property-based tests for orchestrator-init Lambda handler.

Properties covered:
  Property 1: Execution payload completeness (run_id + timestamp present)
  Property 2: Lane list round-trip (exact list from SSM returned)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.workers.orchestrator_init import handler


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid lane identifiers
_lane_id = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ_",
    min_size=3,
    max_size=20
).filter(lambda x: x and not x.startswith("_") and not x.endswith("_"))

# Non-empty lists of lane identifiers
_lane_list = st.lists(_lane_id, min_size=1, max_size=10, unique=True)

# Valid run IDs
_run_id = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=5,
    max_size=50
).filter(lambda x: x and not x.startswith("-") and not x.endswith("-"))

# Valid ISO8601 timestamps
_iso_timestamp = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31)
).map(lambda dt: dt.replace(tzinfo=timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Property 1: Execution payload completeness
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 1: Execution payload completeness
@settings(max_examples=100)
@given(
    active_lanes=_lane_list,
    input_run_id=st.one_of(st.none(), _run_id),
    input_timestamp=st.one_of(st.none(), _iso_timestamp),
)
def test_execution_payload_completeness(active_lanes, input_run_id, input_timestamp):
    """
    For any invocation timestamp, the execution payload produced by orchestrator-init
    SHALL contain a non-empty run_id string and a valid ISO8601 timestamp field.
    """
    # Mock SSM response
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(active_lanes)}
    }
    
    # Build input event
    event = {}
    if input_run_id is not None:
        event["run_id"] = input_run_id
    if input_timestamp is not None:
        event["timestamp"] = input_timestamp
    
    with patch("src.workers.orchestrator_init._get_ssm", return_value=mock_ssm):
        result = handler(event, None)
    
    # Property 1: run_id and timestamp must be present and non-empty
    assert "run_id" in result
    assert "timestamp" in result
    assert isinstance(result["run_id"], str)
    assert isinstance(result["timestamp"], str)
    assert len(result["run_id"]) > 0
    assert len(result["timestamp"]) > 0
    
    # If input provided run_id/timestamp, they should be preserved
    if input_run_id is not None:
        assert result["run_id"] == input_run_id
    if input_timestamp is not None:
        assert result["timestamp"] == input_timestamp
    
    # Generated run_id should follow expected pattern if not provided
    if input_run_id is None:
        assert result["run_id"].startswith("run-")
        assert len(result["run_id"]) == 16  # "run-" + 12 hex chars
    
    # Generated timestamp should be valid ISO8601 if not provided
    if input_timestamp is None:
        # Should be parseable as ISO8601
        datetime.fromisoformat(result["timestamp"].replace("Z", "+00:00"))


# Feature: lambda-redteam-harness, Property 1: Execution payload always has lanes field
@settings(max_examples=100)
@given(active_lanes=_lane_list)
def test_execution_payload_has_lanes_field(active_lanes):
    """The execution payload must always contain a lanes field."""
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(active_lanes)}
    }
    
    with patch("src.workers.orchestrator_init._get_ssm", return_value=mock_ssm):
        result = handler({}, None)
    
    assert "lanes" in result
    assert isinstance(result["lanes"], list)


# ---------------------------------------------------------------------------
# Property 2: Lane list round-trip
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 2: Lane list round-trip
@settings(max_examples=100)
@given(active_lanes=_lane_list)
def test_lane_list_round_trip(active_lanes):
    """
    For any list of active lane identifiers stored in Parameter Store,
    orchestrator-init SHALL return exactly that list in its output payload
    — no lanes added, none dropped.
    """
    # Mock SSM response with the exact lane list
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(active_lanes)}
    }
    
    with patch("src.workers.orchestrator_init._get_ssm", return_value=mock_ssm):
        result = handler({}, None)
    
    # Extract lane_ids from the result
    returned_lane_ids = [lane["lane_id"] for lane in result["lanes"]]
    
    # Property 2: exact same list, same order
    assert returned_lane_ids == active_lanes
    
    # Verify each lane descriptor has required fields
    for i, lane in enumerate(result["lanes"]):
        assert "lane_id" in lane
        assert "config_prefix" in lane
        assert lane["lane_id"] == active_lanes[i]
        assert lane["config_prefix"] == f"/autoredteam/test/lanes/{active_lanes[i]}"


# Feature: lambda-redteam-harness, Property 2: Lane list preserves order
@settings(max_examples=100)
@given(
    lanes=st.lists(_lane_id, min_size=2, max_size=5, unique=True),
    shuffle_seed=st.integers(0, 1000)
)
def test_lane_list_preserves_order(lanes, shuffle_seed):
    """The order of lanes in SSM must be preserved in the output."""
    import random
    
    # Shuffle the lanes to test order preservation
    shuffled_lanes = lanes.copy()
    random.Random(shuffle_seed).shuffle(shuffled_lanes)
    
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(shuffled_lanes)}
    }
    
    with patch("src.workers.orchestrator_init._get_ssm", return_value=mock_ssm):
        result = handler({}, None)
    
    returned_lane_ids = [lane["lane_id"] for lane in result["lanes"]]
    assert returned_lane_ids == shuffled_lanes


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

def test_empty_lanes_raises_value_error():
    """Empty active_lanes list should raise ValueError."""
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps([])}
    }
    
    with patch("src.workers.orchestrator_init._get_ssm", return_value=mock_ssm):
        with pytest.raises(ValueError, match="No active lanes found"):
            handler({}, None)


def test_ssm_parameter_name_is_correct():
    """Verify the correct SSM parameter path is used."""
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(["OBJ_TEST"])}
    }
    
    with patch("src.workers.orchestrator_init._get_ssm", return_value=mock_ssm):
        handler({}, None)
    
    # Verify SSM was called with correct parameter name
    mock_ssm.get_parameter.assert_called_once_with(
        Name="/autoredteam/test/active_lanes",
        WithDecryption=False
    )


def test_config_prefix_format():
    """Verify config_prefix follows the expected format."""
    lanes = ["OBJ_WEB_BYPASS", "OBJ_IDENTITY_ESCALATION"]
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(lanes)}
    }
    
    with patch("src.workers.orchestrator_init._get_ssm", return_value=mock_ssm):
        result = handler({}, None)
    
    for i, lane in enumerate(result["lanes"]):
        expected_prefix = f"/autoredteam/test/lanes/{lanes[i]}"
        assert lane["config_prefix"] == expected_prefix


def test_generated_run_id_format():
    """Verify generated run_id follows expected format."""
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(["OBJ_TEST"])}
    }
    
    with patch("src.workers.orchestrator_init._get_ssm", return_value=mock_ssm):
        result = handler({}, None)
    
    run_id = result["run_id"]
    assert run_id.startswith("run-")
    # Should be "run-" + 12 hex characters
    hex_part = run_id[4:]
    assert len(hex_part) == 12
    # Should be valid hex
    int(hex_part, 16)  # Will raise ValueError if not valid hex


def test_generated_timestamp_is_iso8601():
    """Verify generated timestamp is valid ISO8601."""
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(["OBJ_TEST"])}
    }
    
    with patch("src.workers.orchestrator_init._get_ssm", return_value=mock_ssm):
        result = handler({}, None)
    
    timestamp = result["timestamp"]
    # Should be parseable as ISO8601
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None  # Should have timezone info