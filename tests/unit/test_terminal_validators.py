"""
Property-based and unit tests for TerminalValidator.

Properties covered:
  Property 15: Terminal validator always returns bool (never None/exception)
  Property 34: OBJ_WEB_BYPASS terminal condition
  Property 35: OBJ_IDENTITY_ESCALATION terminal condition
  Property 36: OBJ_WAF_BYPASS terminal condition
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.lib.evaluators.terminal_validator import TerminalValidator
from src.lib.models import (
    ExperimentResult,
    GateThresholds,
    HttpRequest,
    HttpResponse,
    LaneConfig,
    PhiWeights,
    TerminalConditionConfig,
    TerminalResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status: int, body: str) -> HttpResponse:
    return HttpResponse(status_code=status, headers={}, body=body, elapsed_ms=50)


def _make_result(status: int, body: str) -> ExperimentResult:
    return ExperimentResult(
        run_id="run-001",
        lane_id="TEST",
        timestamp="2024-01-01T00:00:00Z",
        request=HttpRequest(method="POST", url="http://dvwa/test", headers={}, body=""),
        response=_make_response(status, body),
    )


def _make_failed_result() -> ExperimentResult:
    return ExperimentResult(
        run_id="run-001",
        lane_id="TEST",
        timestamp="2024-01-01T00:00:00Z",
        request=HttpRequest(method="POST", url="http://dvwa/test", headers={}, body=""),
        response=None,
        error="Connection refused",
    )


def _make_lane_config(cond: TerminalConditionConfig) -> LaneConfig:
    return LaneConfig(
        lane_id="TEST",
        target_url="http://dvwa",
        dvwa_security_level="low",
        terminal_condition=cond,
        phi_weights=PhiWeights(alpha=0.4, beta=0.35, gamma=0.25),
        gate_thresholds=GateThresholds(
            reproducibility_min_fraction=0.8,
            reproducibility_reruns=3,
            evidence_markers=[],
            cost_max_tokens=50000,
            cost_max_duration_ms=240000,
            noise_patterns=[],
        ),
        bedrock_max_retries=3,
        http_timeout_ms=10000,
    )


_printable = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters=" _-."
))

# ---------------------------------------------------------------------------
# Property 15: Terminal validator always returns TerminalResult (never None/exception)
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 15: Terminal validator returns boolean
@settings(max_examples=100)
@given(
    status=st.integers(min_value=100, max_value=599),
    body=st.text(max_size=200),
    indicator=_printable,
)
def test_web_bypass_always_returns_terminal_result(status, body, indicator):
    """evaluate() must always return a TerminalResult, never raise."""
    cond = TerminalConditionConfig(lane_type="WEB_BYPASS", success_indicator=indicator)
    cfg = _make_lane_config(cond)
    result = _make_result(status, body)
    tr = TerminalValidator().evaluate(result, cfg)
    assert isinstance(tr, TerminalResult)
    assert isinstance(tr.passed, bool)


# Feature: lambda-redteam-harness, Property 15: Terminal validator returns boolean (failed experiment)
def test_failed_experiment_returns_false_not_exception():
    """A failed experiment (no response) must return passed=False, not raise."""
    cond = TerminalConditionConfig(lane_type="WEB_BYPASS", success_indicator="Welcome")
    cfg = _make_lane_config(cond)
    tr = TerminalValidator().evaluate(_make_failed_result(), cfg)
    assert tr.passed is False


# ---------------------------------------------------------------------------
# Property 34: OBJ_WEB_BYPASS terminal condition
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 34: OBJ_WEB_BYPASS terminal condition
@settings(max_examples=100)
@given(
    indicator=_printable,
    extra=st.text(max_size=100),
)
def test_web_bypass_passes_on_200_with_indicator(indicator, extra):
    """status==200 AND indicator in body → passed=True."""
    body = extra + indicator + extra
    cond = TerminalConditionConfig(lane_type="WEB_BYPASS", success_indicator=indicator)
    cfg = _make_lane_config(cond)
    tr = TerminalValidator().evaluate(_make_result(200, body), cfg)
    assert tr.passed is True
    assert tr.matched_indicator == indicator


# Feature: lambda-redteam-harness, Property 34: OBJ_WEB_BYPASS non-200 always fails
@settings(max_examples=100)
@given(
    status=st.one_of(
        st.integers(min_value=300, max_value=399),
        st.integers(min_value=400, max_value=499),
        st.integers(min_value=500, max_value=599),
    ),
    indicator=_printable,
)
def test_web_bypass_fails_on_non_200(status, indicator):
    """3xx/4xx/5xx must always return passed=False regardless of body."""
    body = indicator  # indicator IS in body, but status is wrong
    cond = TerminalConditionConfig(lane_type="WEB_BYPASS", success_indicator=indicator)
    cfg = _make_lane_config(cond)
    tr = TerminalValidator().evaluate(_make_result(status, body), cfg)
    assert tr.passed is False


# Feature: lambda-redteam-harness, Property 34: OBJ_WEB_BYPASS indicator absent → fails
@settings(max_examples=100)
@given(indicator=_printable)
def test_web_bypass_fails_when_indicator_absent(indicator):
    """200 response without indicator in body → passed=False."""
    body = "some other content that does not contain the indicator"
    # Ensure indicator is not accidentally in body
    if indicator in body:
        body = "XXXXXX"
    cond = TerminalConditionConfig(lane_type="WEB_BYPASS", success_indicator=indicator)
    cfg = _make_lane_config(cond)
    tr = TerminalValidator().evaluate(_make_result(200, body), cfg)
    # Only fails if indicator truly absent
    if indicator not in body:
        assert tr.passed is False


# ---------------------------------------------------------------------------
# Property 35: OBJ_IDENTITY_ESCALATION terminal condition
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 35: OBJ_IDENTITY_ESCALATION terminal condition
@settings(max_examples=100)
@given(
    privilege_string=_printable,
    extra=st.text(max_size=50),
)
def test_identity_escalation_passes_with_non_admin_session(privilege_string, extra):
    """privilege_string in body + non-admin session → passed=True."""
    body = extra + privilege_string + extra
    cond = TerminalConditionConfig(
        lane_type="IDENTITY_ESCALATION",
        privilege_string=privilege_string,
    )
    cfg = _make_lane_config(cond)
    tr = TerminalValidator().evaluate(_make_result(200, body), cfg, session_is_admin=False)
    assert tr.passed is True
    assert tr.matched_indicator == privilege_string


# Feature: lambda-redteam-harness, Property 35: Admin session always fails
@settings(max_examples=100)
@given(
    privilege_string=_printable,
    extra=st.text(max_size=50),
)
def test_identity_escalation_fails_with_admin_session(privilege_string, extra):
    """Admin session must always return passed=False even if privilege_string in body."""
    body = extra + privilege_string + extra
    cond = TerminalConditionConfig(
        lane_type="IDENTITY_ESCALATION",
        privilege_string=privilege_string,
    )
    cfg = _make_lane_config(cond)
    tr = TerminalValidator().evaluate(_make_result(200, body), cfg, session_is_admin=True)
    assert tr.passed is False


# ---------------------------------------------------------------------------
# Property 36: OBJ_WAF_BYPASS terminal condition
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 36: OBJ_WAF_BYPASS terminal condition
@settings(max_examples=100)
@given(
    marker=_printable,
    extra=st.text(max_size=50),
)
def test_waf_bypass_passes_without_block_with_marker(marker, extra):
    """No block indicator + interpretation marker in body → passed=True."""
    body = extra + marker + extra
    cond = TerminalConditionConfig(
        lane_type="WAF_BYPASS",
        waf_block_indicator="BLOCKED",
        interpretation_markers=[marker],
    )
    cfg = _make_lane_config(cond)
    tr = TerminalValidator().evaluate(_make_result(200, body), cfg)
    assert tr.passed is True
    assert tr.matched_indicator == marker


# Feature: lambda-redteam-harness, Property 36: WAF block indicator always fails
@settings(max_examples=100)
@given(
    marker=_printable,
    extra=st.text(max_size=50),
)
def test_waf_bypass_fails_when_block_indicator_present(marker, extra):
    """WAF block indicator in body → passed=False even if marker also present."""
    block = "BLOCKED_BY_WAF"
    body = extra + marker + extra + block
    cond = TerminalConditionConfig(
        lane_type="WAF_BYPASS",
        waf_block_indicator=block,
        interpretation_markers=[marker],
    )
    cfg = _make_lane_config(cond)
    tr = TerminalValidator().evaluate(_make_result(200, body), cfg)
    assert tr.passed is False


# Feature: lambda-redteam-harness, Property 36: No markers → fails
def test_waf_bypass_fails_when_no_markers_present():
    """No interpretation markers in body → passed=False."""
    cond = TerminalConditionConfig(
        lane_type="WAF_BYPASS",
        waf_block_indicator="BLOCKED",
        interpretation_markers=["SQL syntax", "mysql_fetch"],
    )
    cfg = _make_lane_config(cond)
    tr = TerminalValidator().evaluate(_make_result(200, "clean response"), cfg)
    assert tr.passed is False
