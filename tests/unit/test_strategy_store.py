"""
Property-based and unit tests for StrategyStore.

Properties covered:
  Property 14: Artifact key scoping
  Property 26: Strategy promotion on all-gates-pass
  Property 28: Strategy history preservation
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from hypothesis import given, settings
from hypothesis import strategies as st

from src.lib.models import Mutation, Strategy
from src.lib.strategy_store import ArtifactStoreError, StrategyStore

_lane_id_st = st.text(min_size=1, max_size=30, alphabet=st.characters(
    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"
))


def _make_strategy(lane_id="OBJ_WEB_BYPASS", phi=0.5, run_id="r1"):
    now = datetime.now(timezone.utc).isoformat()
    return Strategy(
        lane_id=lane_id,
        version=1,
        phi_score=phi,
        created_at=now,
        promoted_at=now,
        run_id=run_id,
        mutation=Mutation(
            attack_payload="payload",
            target_endpoint="/test",
            http_method="POST",
            headers={},
            rationale="test",
        ),
    )


def _s3_not_found_error():
    error = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
        "GetObject",
    )
    return error


# ---------------------------------------------------------------------------
# Property 14: Artifact key scoping
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 14: Artifact key scoping
@settings(max_examples=100)
@given(lane_id=_lane_id_st)
def test_current_key_contains_lane_id(lane_id):
    """Current strategy key must contain the lane_id as a path component."""
    key = StrategyStore.current_key(lane_id)
    assert lane_id in key
    assert key.startswith("strategies/")
    assert key.endswith("current.json")


# Feature: lambda-redteam-harness, Property 14: Artifact key scoping (history)
@settings(max_examples=100)
@given(lane_id=_lane_id_st, timestamp=st.text(min_size=1, max_size=30))
def test_history_key_contains_lane_id_and_timestamp(lane_id, timestamp):
    """History key must contain both lane_id and timestamp as path components."""
    key = StrategyStore.history_key(lane_id, timestamp)
    assert lane_id in key
    assert timestamp in key
    assert "history" in key


# ---------------------------------------------------------------------------
# Property 26: Strategy promotion writes to current.json
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 26: Strategy promotion on all-gates-pass
def test_promote_writes_strategy_to_current_key():
    """promote() must write the new strategy to strategies/{lane_id}/current.json."""
    mock_s3 = MagicMock()
    # No existing strategy
    mock_s3.get_object.side_effect = _s3_not_found_error()

    store = StrategyStore(bucket="test-bucket", s3_client=mock_s3)
    strategy = _make_strategy()
    store.promote("OBJ_WEB_BYPASS", strategy)

    # Verify put_object was called with the correct key
    call_kwargs = mock_s3.put_object.call_args.kwargs
    assert call_kwargs["Key"] == "strategies/OBJ_WEB_BYPASS/current.json"
    body = json.loads(call_kwargs["Body"].decode())
    assert body["phi_score"] == 0.5


# Feature: lambda-redteam-harness, Property 26: Promoted strategy contains mutation + phi
def test_promote_artifact_contains_mutation_and_phi():
    """The promoted strategy artifact must contain the mutation and phi_score."""
    mock_s3 = MagicMock()
    mock_s3.get_object.side_effect = _s3_not_found_error()

    store = StrategyStore(bucket="test-bucket", s3_client=mock_s3)
    strategy = _make_strategy(phi=0.75)
    store.promote("OBJ_WEB_BYPASS", strategy)

    body = json.loads(mock_s3.put_object.call_args.kwargs["Body"].decode())
    assert body["phi_score"] == 0.75
    assert "mutation" in body
    assert body["mutation"]["attack_payload"] == "payload"


# ---------------------------------------------------------------------------
# Property 28: Strategy history preservation
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 28: Strategy history preservation
def test_promote_archives_existing_strategy_before_writing_new():
    """promote() must archive the existing strategy before writing the new one."""
    existing = _make_strategy(phi=0.3)
    existing_json = json.dumps(existing.to_dict()).encode()

    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: existing_json)}

    store = StrategyStore(bucket="test-bucket", s3_client=mock_s3)
    new_strategy = _make_strategy(phi=0.6)
    store.promote("OBJ_WEB_BYPASS", new_strategy)

    # Two put_object calls: one for archive, one for current
    assert mock_s3.put_object.call_count == 2
    keys = [c.kwargs["Key"] for c in mock_s3.put_object.call_args_list]
    history_keys = [k for k in keys if "history" in k]
    current_keys = [k for k in keys if k.endswith("current.json")]
    assert len(history_keys) == 1
    assert len(current_keys) == 1


# Feature: lambda-redteam-harness, Property 28: N promotions → N history entries
def test_n_promotions_create_n_history_entries():
    """N sequential promotions must create exactly N history entries."""
    call_count = {"n": 0}
    stored: dict[str, bytes] = {}

    def fake_get_object(Bucket, Key):
        if Key not in stored:
            raise _s3_not_found_error()
        return {"Body": MagicMock(read=lambda: stored[Key])}

    def fake_put_object(Bucket, Key, Body, ContentType):
        stored[Key] = Body

    mock_s3 = MagicMock()
    mock_s3.get_object.side_effect = fake_get_object
    mock_s3.put_object.side_effect = fake_put_object

    store = StrategyStore(bucket="test-bucket", s3_client=mock_s3)
    n = 5
    for i in range(n):
        store.promote("OBJ_WEB_BYPASS", _make_strategy(phi=0.1 * (i + 1)))

    history_keys = [k for k in stored if "history" in k]
    assert len(history_keys) == n - 1  # first promotion has nothing to archive


# Unit: get_current returns None when key absent
def test_get_current_returns_none_when_absent():
    mock_s3 = MagicMock()
    mock_s3.get_object.side_effect = _s3_not_found_error()
    store = StrategyStore(bucket="test-bucket", s3_client=mock_s3)
    assert store.get_current("OBJ_WEB_BYPASS") is None


# Unit: S3 error raises ArtifactStoreError
def test_get_current_raises_on_unexpected_s3_error():
    mock_s3 = MagicMock()
    mock_s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "GetObject"
    )
    store = StrategyStore(bucket="test-bucket", s3_client=mock_s3)
    with pytest.raises(ArtifactStoreError):
        store.get_current("OBJ_WEB_BYPASS")
