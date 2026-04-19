"""
Property-based and unit tests for StateStore.

Properties covered:
  Property 20: Ratchet discard on non-improving Phi
  Property 25: Gate failure records gate name
  Property 27: State store update on promotion
  Property 29: Lane state record completeness
  Property 30: DynamoDB conditional write usage
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError
from hypothesis import given, settings
from hypothesis import strategies as st

from src.lib.models import LaneStateUpdate
from src.lib.state_store import StateConflictError, StateStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(mock_table=None):
    mock_dynamodb = MagicMock()
    table = mock_table or MagicMock()
    mock_dynamodb.Table.return_value = table
    return StateStore(table_name="ObjectiveLanes", dynamodb=mock_dynamodb), table


def _make_item(lane_id="OBJ_WEB_BYPASS", phi=0.5, status="ACTIVE", discards=0):
    return {
        "lane_id": lane_id,
        "phi_score": Decimal(str(phi)),
        "terminal_status": status,
        "discard_count": discards,
        "last_run_id": "r1",
        "last_updated": "2024-01-01T00:00:00Z",
        "last_gate_failure": None,
    }


# ---------------------------------------------------------------------------
# Property 29: Lane state record completeness
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 29: Lane state record completeness
def test_get_lane_state_returns_all_required_fields():
    """get_lane_state must return a LaneState with all 5 required fields."""
    store, table = _make_store()
    table.get_item.return_value = {"Item": _make_item()}

    state = store.get_lane_state("OBJ_WEB_BYPASS")

    assert state is not None
    assert isinstance(state.phi_score, float)
    assert isinstance(state.terminal_status, str)
    assert isinstance(state.discard_count, int)
    assert isinstance(state.last_run_id, str)
    assert isinstance(state.last_updated, str)


# Feature: lambda-redteam-harness, Property 29: None returned when lane absent
def test_get_lane_state_returns_none_when_absent():
    store, table = _make_store()
    table.get_item.return_value = {}
    assert store.get_lane_state("OBJ_WEB_BYPASS") is None


# ---------------------------------------------------------------------------
# Property 30: DynamoDB conditional write usage
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 30: DynamoDB conditional write usage
def test_update_lane_state_uses_condition_expression():
    """update_lane_state must pass a ConditionExpression to DynamoDB."""
    store, table = _make_store()
    store.update_lane_state("OBJ_WEB_BYPASS", LaneStateUpdate(phi_score=0.6))

    call_kwargs = table.update_item.call_args.kwargs
    assert "ConditionExpression" in call_kwargs


# Feature: lambda-redteam-harness, Property 30: increment_discard uses condition
def test_increment_discard_counter_uses_condition_expression():
    """increment_discard_counter must pass a ConditionExpression to DynamoDB."""
    store, table = _make_store()
    store.increment_discard_counter("OBJ_WEB_BYPASS")

    call_kwargs = table.update_item.call_args.kwargs
    assert "ConditionExpression" in call_kwargs


# ---------------------------------------------------------------------------
# Property 27: State store update on promotion
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 27: State store update on promotion
def test_mark_terminal_success_updates_phi_status_and_run_id():
    """mark_terminal_success must update phi_score, terminal_status, and last_run_id."""
    store, table = _make_store()
    store.mark_terminal_success("OBJ_WEB_BYPASS", run_id="r42", phi_score=0.95)

    call_kwargs = table.update_item.call_args.kwargs
    expr_values = call_kwargs["ExpressionAttributeValues"]

    assert ":phi_score" in expr_values
    assert float(expr_values[":phi_score"]) == pytest.approx(0.95)
    assert expr_values.get(":terminal_status") == "TERMINAL_SUCCESS"
    assert expr_values.get(":last_run_id") == "r42"


# ---------------------------------------------------------------------------
# Property 20: Ratchet discard increments counter
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 20: Ratchet discard on non-improving Phi
def test_increment_discard_counter_increments_by_one():
    """increment_discard_counter must add exactly 1 to discard_count."""
    store, table = _make_store()
    store.increment_discard_counter("OBJ_WEB_BYPASS")

    call_kwargs = table.update_item.call_args.kwargs
    expr_values = call_kwargs["ExpressionAttributeValues"]
    assert expr_values[":one"] == 1


# ---------------------------------------------------------------------------
# Property 25: Gate failure records gate name
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 25: Gate failure records gate name
@settings(max_examples=50)
@given(gate_name=st.sampled_from(["evidence", "cost", "noise", "reproducibility"]))
def test_update_lane_state_records_gate_failure_name(gate_name):
    """update_lane_state with last_gate_failure must write the gate name to DynamoDB."""
    store, table = _make_store()
    store.update_lane_state(
        "OBJ_WEB_BYPASS",
        LaneStateUpdate(last_gate_failure=gate_name),
    )

    call_kwargs = table.update_item.call_args.kwargs
    expr_values = call_kwargs["ExpressionAttributeValues"]
    assert expr_values.get(":last_gate_failure") == gate_name


# ---------------------------------------------------------------------------
# Unit: ConditionalCheckFailedException → StateConflictError
# ---------------------------------------------------------------------------

def test_update_lane_state_raises_state_conflict_on_condition_failure():
    store, table = _make_store()
    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}},
        "UpdateItem",
    )
    with pytest.raises(StateConflictError):
        store.update_lane_state("OBJ_WEB_BYPASS", LaneStateUpdate(phi_score=0.5))
