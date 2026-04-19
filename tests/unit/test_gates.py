"""
Property-based and unit tests for GateEvaluator.

Properties covered:
  Property 21: Reproducibility gate threshold
  Property 22: Evidence gate marker containment
  Property 23: Cost gate threshold enforcement
  Property 24: Noise gate pattern exclusion
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.lib.evaluators.gates import GateEvaluator
from src.lib.models import (
    ExperimentResult,
    GateThresholds,
    HttpRequest,
    HttpResponse,
    LaneConfig,
    PhiWeights,
    TerminalConditionConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(body: str, status: int = 200) -> ExperimentResult:
    return ExperimentResult(
        run_id="run-001",
        lane_id="TEST",
        timestamp="2024-01-01T00:00:00Z",
        request=HttpRequest(method="POST", url="http://dvwa/test", headers={}, body=""),
        response=HttpResponse(status_code=status, headers={}, body=body, elapsed_ms=50),
    )


def _make_failed_result() -> ExperimentResult:
    return ExperimentResult(
        run_id="run-001",
        lane_id="TEST",
        timestamp="2024-01-01T00:00:00Z",
        request=HttpRequest(method="POST", url="http://dvwa/test", headers={}, body=""),
        response=None,
        error="timeout",
    )


def _make_lane_config(
    evidence_markers: list[str] = None,
    cost_max_tokens: int = 50000,
    cost_max_duration_ms: int = 240000,
    noise_patterns: list[str] = None,
) -> LaneConfig:
    return LaneConfig(
        lane_id="TEST",
        target_url="http://dvwa",
        dvwa_security_level="low",
        terminal_condition=TerminalConditionConfig(lane_type="WEB_BYPASS"),
        phi_weights=PhiWeights(alpha=0.4, beta=0.35, gamma=0.25),
        gate_thresholds=GateThresholds(
            reproducibility_min_fraction=0.8,
            reproducibility_reruns=3,
            evidence_markers=evidence_markers or [],
            cost_max_tokens=cost_max_tokens,
            cost_max_duration_ms=cost_max_duration_ms,
            noise_patterns=noise_patterns or [],
        ),
        bedrock_max_retries=3,
        http_timeout_ms=10000,
    )


_printable = st.text(min_size=1, max_size=30, alphabet=st.characters(
    whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters=" _-."
))

# ---------------------------------------------------------------------------
# Property 22: Evidence gate marker containment
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 22: Evidence gate marker containment
@settings(max_examples=100)
@given(
    markers=st.lists(_printable, min_size=1, max_size=5),
    extra=st.text(max_size=50),
)
def test_evidence_gate_passes_when_all_markers_present(markers, extra):
    """Evidence gate passes iff every marker is in the response body."""
    body = extra + "".join(markers) + extra
    cfg = _make_lane_config(evidence_markers=markers)
    result = _make_result(body)
    gr = GateEvaluator().evaluate_evidence(result, cfg)
    # All markers are in body, so gate must pass
    assert gr.passed is True
    assert gr.gate_name == "evidence"


# Feature: lambda-redteam-harness, Property 22: Evidence gate fails if any marker missing
@settings(max_examples=100)
@given(
    markers=st.lists(_printable, min_size=2, max_size=5),
)
def test_evidence_gate_fails_when_marker_missing(markers):
    """Evidence gate fails if even one marker is absent from the body."""
    # Body contains all markers except the last one
    body = "".join(markers[:-1])
    missing_marker = markers[-1]
    # Ensure missing_marker is truly absent
    if missing_marker in body:
        body = "XXXXXX"
    cfg = _make_lane_config(evidence_markers=markers)
    result = _make_result(body)
    gr = GateEvaluator().evaluate_evidence(result, cfg)
    if missing_marker not in body:
        assert gr.passed is False


# ---------------------------------------------------------------------------
# Property 23: Cost gate threshold enforcement
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 23: Cost gate threshold enforcement
@settings(max_examples=100)
@given(
    max_tokens=st.integers(min_value=1, max_value=100000),
    max_duration=st.integers(min_value=1, max_value=300000),
    token_usage=st.integers(min_value=0, max_value=100000),
    duration_ms=st.integers(min_value=0, max_value=300000),
)
def test_cost_gate_passes_iff_within_both_thresholds(
    max_tokens, max_duration, token_usage, duration_ms
):
    """Cost gate passes iff token_usage <= max_tokens AND duration_ms <= max_duration."""
    cfg = _make_lane_config(cost_max_tokens=max_tokens, cost_max_duration_ms=max_duration)
    gr = GateEvaluator().evaluate_cost(token_usage, duration_ms, cfg)

    expected = token_usage <= max_tokens and duration_ms <= max_duration
    assert gr.passed is expected
    assert gr.gate_name == "cost"


# ---------------------------------------------------------------------------
# Property 24: Noise gate pattern exclusion
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 24: Noise gate pattern exclusion
@settings(max_examples=100)
@given(
    patterns=st.lists(_printable, min_size=1, max_size=5),
    extra=st.text(max_size=50),
)
def test_noise_gate_fails_when_any_pattern_present(patterns, extra):
    """Noise gate fails if any noise pattern appears in the response body."""
    # Body contains the first pattern
    body = extra + patterns[0] + extra
    cfg = _make_lane_config(noise_patterns=patterns)
    result = _make_result(body)
    gr = GateEvaluator().evaluate_noise(result, cfg)
    assert gr.passed is False
    assert gr.gate_name == "noise"


# Feature: lambda-redteam-harness, Property 24: Noise gate passes when no patterns present
@settings(max_examples=100)
@given(patterns=st.lists(_printable, min_size=1, max_size=5))
def test_noise_gate_passes_when_no_patterns_in_body(patterns):
    """Noise gate passes if no noise pattern appears in the response body."""
    body = "clean response with no noise"
    cfg = _make_lane_config(noise_patterns=patterns)
    result = _make_result(body)
    gr = GateEvaluator().evaluate_noise(result, cfg)
    # Only assert pass if truly none of the patterns are in body
    if not any(p in body for p in patterns):
        assert gr.passed is True


# ---------------------------------------------------------------------------
# Property 21: Reproducibility gate threshold
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 21: Reproducibility gate threshold
@settings(max_examples=100)
@given(
    total=st.integers(min_value=1, max_value=20),
    passed_count=st.integers(min_value=0, max_value=20),
    min_fraction=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
def test_reproducibility_gate_threshold(total, passed_count, min_fraction):
    """Reproducibility gate passes iff fraction_passed >= min_fraction."""
    passed_count = min(passed_count, total)
    rerun_results = (
        [{"passed": True}] * passed_count
        + [{"passed": False}] * (total - passed_count)
    )
    gr = GateEvaluator.aggregate_reproducibility(rerun_results, min_fraction)
    fraction = passed_count / total
    expected = fraction >= min_fraction
    assert gr.passed is expected
    assert gr.gate_name == "reproducibility"


# Unit: empty rerun results → fails
def test_reproducibility_gate_empty_results_fails():
    gr = GateEvaluator.aggregate_reproducibility([], min_fraction=0.8)
    assert gr.passed is False


# Unit: failed experiment → evidence gate fails
def test_evidence_gate_fails_on_no_response():
    cfg = _make_lane_config(evidence_markers=["SQL syntax"])
    gr = GateEvaluator().evaluate_evidence(_make_failed_result(), cfg)
    assert gr.passed is False


# Unit: failed experiment → noise gate fails
def test_noise_gate_fails_on_no_response():
    cfg = _make_lane_config(noise_patterns=["Login required"])
    gr = GateEvaluator().evaluate_noise(_make_failed_result(), cfg)
    assert gr.passed is False
