"""
Property-based and unit tests for run-summarizer.

Properties covered:
  Property 4: Run summary completeness
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.workers.run_summarizer import handler

_lane_id_st = st.text(min_size=1, max_size=20, alphabet=st.characters(
    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"
))

_status_st = st.sampled_from(["SUCCESS", "TERMINAL_SUCCESS", "FAILED", "DISCARDED"])


def _make_lane_result(lane_id="L1", status="SUCCESS", phi=0.5, terminal=False):
    return {
        "lane_id": lane_id,
        "status": status,
        "phi_score": phi,
        "terminal": terminal,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Property 4: Run summary completeness
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 4: Run summary completeness
@settings(max_examples=100)
@given(
    lane_ids=st.lists(_lane_id_st, min_size=1, max_size=10, unique=True),
    statuses=st.lists(_status_st, min_size=1, max_size=10),
)
def test_summary_contains_entry_for_every_lane(lane_ids, statuses):
    """The summary must contain an entry for every lane in lane_results."""
    # Pair lane_ids with statuses (cycle statuses if fewer than lanes)
    lane_results = [
        _make_lane_result(lane_id=lid, status=statuses[i % len(statuses)])
        for i, lid in enumerate(lane_ids)
    ]

    mock_s3 = MagicMock()
    written_body = {}

    def fake_put_object(Bucket, Key, Body, ContentType):
        written_body["data"] = json.loads(Body.decode())

    mock_s3.put_object.side_effect = fake_put_object

    import src.workers.run_summarizer as rs
    original_s3 = rs._s3_client
    rs._s3_client = mock_s3

    try:
        result = handler(
            {"run_id": "r1", "timestamp": "2024-01-01T00:00:00Z", "lane_results": lane_results},
            None,
        )
    finally:
        rs._s3_client = original_s3

    summary = written_body["data"]

    # Property 4: entry for every lane
    assert len(summary["lanes"]) == len(lane_ids)
    returned_lane_ids = {entry["lane_id"] for entry in summary["lanes"]}
    assert returned_lane_ids == set(lane_ids)

    # Property 4: each entry has outcome, phi_score, terminal_status
    for entry in summary["lanes"]:
        assert "outcome" in entry
        assert "phi_score" in entry
        assert "terminal_status" in entry


# Feature: lambda-redteam-harness, Property 4: Run summary completeness with edge cases
@settings(max_examples=100)
@given(
    lane_results=st.lists(
        st.fixed_dictionaries({
            "lane_id": st.one_of(st.none(), _lane_id_st),
            "status": st.one_of(st.none(), _status_st),
            "phi_score": st.one_of(st.none(), st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False)),
            "terminal": st.one_of(st.none(), st.booleans()),
            "error": st.one_of(st.none(), st.text(min_size=0, max_size=100)),
        }),
        min_size=1,
        max_size=10,
    )
)
def test_summary_completeness_with_missing_fields(lane_results):
    """Property 4: Summary must handle missing/None fields gracefully and still contain required fields."""
    mock_s3 = MagicMock()
    written_body = {}

    def fake_put_object(Bucket, Key, Body, ContentType):
        written_body["data"] = json.loads(Body.decode())

    mock_s3.put_object.side_effect = fake_put_object

    import src.workers.run_summarizer as rs
    original_s3 = rs._s3_client
    rs._s3_client = mock_s3

    try:
        result = handler(
            {"run_id": "test-run", "timestamp": "2024-01-01T00:00:00Z", "lane_results": lane_results},
            None,
        )
    finally:
        rs._s3_client = original_s3

    summary = written_body["data"]

    # Property 4: entry for every input lane result
    assert len(summary["lanes"]) == len(lane_results)

    # Property 4: each entry has required fields with proper defaults
    for i, entry in enumerate(summary["lanes"]):
        # Required fields must always be present
        assert "outcome" in entry
        assert "phi_score" in entry
        assert "terminal_status" in entry
        assert "lane_id" in entry
        
        # Verify proper handling of missing/None values
        original_result = lane_results[i]
        
        # lane_id defaults to "unknown" if missing/None
        expected_lane_id = original_result.get("lane_id") or "unknown"
        assert entry["lane_id"] == expected_lane_id
        
        # status defaults to "UNKNOWN" if missing/None
        expected_status = original_result.get("status") or "UNKNOWN"
        assert entry["outcome"] == expected_status
        
        # phi_score defaults to 0.0 if missing/None, must be float
        phi_score_raw = original_result.get("phi_score")
        expected_phi = float(phi_score_raw if phi_score_raw is not None else 0.0)
        assert entry["phi_score"] == expected_phi
        assert isinstance(entry["phi_score"], float)
        
        # terminal_status derived from terminal field
        terminal_val = bool(original_result.get("terminal", False))
        expected_terminal_status = "TERMINAL_SUCCESS" if terminal_val else "ACTIVE"
        assert entry["terminal_status"] == expected_terminal_status


# Feature: lambda-redteam-harness, Property 4: Summary key is runs/{run_id}/summary.json
def test_summary_written_to_correct_s3_key():
    """Summary must be written to runs/{run_id}/summary.json."""
    mock_s3 = MagicMock()

    import src.workers.run_summarizer as rs
    original_s3 = rs._s3_client
    rs._s3_client = mock_s3

    try:
        handler(
            {"run_id": "run-abc123", "lane_results": [_make_lane_result()]},
            None,
        )
    finally:
        rs._s3_client = original_s3

    call_kwargs = mock_s3.put_object.call_args.kwargs
    assert call_kwargs["Key"] == "runs/run-abc123/summary.json"


# Unit: empty lane_results → summary with zero lanes
def test_summary_with_empty_lane_results():
    mock_s3 = MagicMock()
    written = {}

    def fake_put(Bucket, Key, Body, ContentType):
        written["data"] = json.loads(Body.decode())

    mock_s3.put_object.side_effect = fake_put

    import src.workers.run_summarizer as rs
    original_s3 = rs._s3_client
    rs._s3_client = mock_s3

    try:
        handler({"run_id": "r1", "lane_results": []}, None)
    finally:
        rs._s3_client = original_s3

    assert written["data"]["lane_count"] == 0
    assert written["data"]["lanes"] == []
