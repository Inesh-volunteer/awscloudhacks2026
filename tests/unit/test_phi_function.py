"""
Property-based tests for PhiFunction.

Properties covered:
  Property 19: Phi computation correctness and range
"""
from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.lib.evaluators.phi_function import PhiFunction
from src.lib.models import PhiScores, PhiWeights

_unit_float = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


# Feature: lambda-redteam-harness, Property 19: Phi computation correctness and range
@settings(max_examples=100)
@given(
    alpha=_unit_float,
    beta=_unit_float,
    gamma=_unit_float,
    p_goal=_unit_float,
    c_pre=_unit_float,
    d_depth=_unit_float,
)
def test_phi_computation_correctness_and_range(alpha, beta, gamma, p_goal, c_pre, d_depth):
    """
    For any weights and sub-scores in [0,1]:
    - result == clamp(α×P + β×C + γ×D, 0, 1)
    - result is always in [0.0, 1.0]
    """
    weights = PhiWeights(alpha=alpha, beta=beta, gamma=gamma)
    scores = PhiScores(p_goal=p_goal, c_pre=c_pre, d_depth=d_depth)

    result = PhiFunction().compute(scores, weights)

    expected_raw = alpha * p_goal + beta * c_pre + gamma * d_depth
    expected = max(0.0, min(1.0, expected_raw))

    assert 0.0 <= result <= 1.0
    assert math.isclose(result, expected, abs_tol=1e-9)


# Feature: lambda-redteam-harness, Property 19: Phi always in range even with large weights
@settings(max_examples=100)
@given(
    alpha=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    beta=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    gamma=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    p_goal=_unit_float,
    c_pre=_unit_float,
    d_depth=_unit_float,
)
def test_phi_always_clamped_to_unit_interval(alpha, beta, gamma, p_goal, c_pre, d_depth):
    """Even with weights > 1, the result must stay in [0.0, 1.0]."""
    weights = PhiWeights(alpha=alpha, beta=beta, gamma=gamma)
    scores = PhiScores(p_goal=p_goal, c_pre=c_pre, d_depth=d_depth)
    result = PhiFunction().compute(scores, weights)
    assert 0.0 <= result <= 1.0


# Unit: zero weights → zero score
def test_phi_zero_weights_returns_zero():
    weights = PhiWeights(alpha=0.0, beta=0.0, gamma=0.0)
    scores = PhiScores(p_goal=1.0, c_pre=1.0, d_depth=1.0)
    assert PhiFunction().compute(scores, weights) == 0.0


# Unit: unit weights, unit scores → clamped to 1.0
def test_phi_unit_weights_unit_scores_returns_one():
    weights = PhiWeights(alpha=1.0, beta=1.0, gamma=1.0)
    scores = PhiScores(p_goal=1.0, c_pre=1.0, d_depth=1.0)
    assert PhiFunction().compute(scores, weights) == 1.0


# Unit: standard weights sum to 1.0 with all-1 scores → 1.0
def test_phi_standard_weights_all_ones():
    weights = PhiWeights(alpha=0.4, beta=0.35, gamma=0.25)
    scores = PhiScores(p_goal=1.0, c_pre=1.0, d_depth=1.0)
    result = PhiFunction().compute(scores, weights)
    assert math.isclose(result, 1.0, abs_tol=1e-9)
