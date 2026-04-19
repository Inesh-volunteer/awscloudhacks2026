"""
GateEvaluator — evaluates the three inline gates (Evidence, Cost, Noise).
The Reproducibility Gate is handled by the nested Step Functions sub-machine.

Property coverage:
  Property 21: Reproducibility gate threshold (sub-machine aggregation helper)
  Property 22: Evidence gate marker containment
  Property 23: Cost gate threshold enforcement
  Property 24: Noise gate pattern exclusion
"""
from __future__ import annotations

from src.lib.models import ExperimentResult, GateResult, LaneConfig


# CostThresholds is part of GateThresholds in LaneConfig
from dataclasses import dataclass

@dataclass
class CostThresholds:
    max_tokens: int
    max_duration_ms: int


class GateEvaluator:
    """Stateless gate evaluator for Evidence, Cost, and Noise gates."""

    # ------------------------------------------------------------------
    # Evidence Gate (Property 22)
    # ------------------------------------------------------------------

    def evaluate_evidence(
        self,
        result: ExperimentResult,
        lane_config: LaneConfig,
    ) -> GateResult:
        """
        Pass if and only if every required evidence marker appears in the
        response body.

        Args:
            result:      The experiment result to inspect.
            lane_config: Lane config containing the required evidence markers.

        Returns:
            GateResult with passed=True if all markers present, else False.
        """
        if not result.succeeded or result.response is None:
            return GateResult(
                gate_name="evidence",
                passed=False,
                reason="No response to evaluate evidence against",
            )

        body = result.response.body
        required_markers = lane_config.gate_thresholds.evidence_markers

        missing = [m for m in required_markers if m not in body]
        if missing:
            return GateResult(
                gate_name="evidence",
                passed=False,
                reason=f"Missing evidence markers: {missing}",
            )

        return GateResult(
            gate_name="evidence",
            passed=True,
            reason="All required evidence markers present",
        )

    # ------------------------------------------------------------------
    # Cost Gate (Property 23)
    # ------------------------------------------------------------------

    def evaluate_cost(
        self,
        token_usage: int,
        duration_ms: int,
        lane_config: LaneConfig,
    ) -> GateResult:
        """
        Pass if and only if token_usage <= max_tokens AND
        duration_ms <= max_duration_ms.

        Args:
            token_usage:  Total Bedrock tokens consumed in this cycle.
            duration_ms:  Total Lambda execution duration in milliseconds.
            lane_config:  Lane config containing cost thresholds.

        Returns:
            GateResult with passed=True if within thresholds, else False.
        """
        thresholds = lane_config.gate_thresholds
        max_tokens = thresholds.cost_max_tokens
        max_duration = thresholds.cost_max_duration_ms

        if token_usage > max_tokens:
            return GateResult(
                gate_name="cost",
                passed=False,
                reason=(
                    f"Token usage {token_usage} exceeds max {max_tokens}"
                ),
            )

        if duration_ms > max_duration:
            return GateResult(
                gate_name="cost",
                passed=False,
                reason=(
                    f"Duration {duration_ms}ms exceeds max {max_duration}ms"
                ),
            )

        return GateResult(
            gate_name="cost",
            passed=True,
            reason="Token usage and duration within thresholds",
        )

    # ------------------------------------------------------------------
    # Noise Gate (Property 24)
    # ------------------------------------------------------------------

    def evaluate_noise(
        self,
        result: ExperimentResult,
        lane_config: LaneConfig,
    ) -> GateResult:
        """
        Pass if and only if no noise pattern appears in the response body.

        Args:
            result:      The experiment result to inspect.
            lane_config: Lane config containing noise patterns.

        Returns:
            GateResult with passed=True if no noise patterns found, else False.
        """
        if not result.succeeded or result.response is None:
            return GateResult(
                gate_name="noise",
                passed=False,
                reason="No response to evaluate noise against",
            )

        body = result.response.body
        noise_patterns = lane_config.gate_thresholds.noise_patterns

        for pattern in noise_patterns:
            if pattern and pattern in body:
                return GateResult(
                    gate_name="noise",
                    passed=False,
                    reason=f"Noise pattern found: '{pattern}'",
                )

        return GateResult(
            gate_name="noise",
            passed=True,
            reason="No noise patterns detected",
        )

    # ------------------------------------------------------------------
    # Reproducibility Gate aggregation helper (Property 21)
    # Used by the Step Functions sub-machine result aggregator.
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate_reproducibility(
        rerun_results: list[dict],
        min_fraction: float,
    ) -> GateResult:
        """
        Aggregate reproducibility re-run results from the nested SFN.

        Args:
            rerun_results: List of dicts with key 'passed' (bool).
            min_fraction:  Minimum fraction of passing re-runs required.

        Returns:
            GateResult with passed=True if fraction_passed >= min_fraction.
        """
        if not rerun_results:
            return GateResult(
                gate_name="reproducibility",
                passed=False,
                reason="No re-run results to aggregate",
            )

        total = len(rerun_results)
        passed_count = sum(1 for r in rerun_results if r.get("passed", False))
        fraction = passed_count / total

        if fraction >= min_fraction:
            return GateResult(
                gate_name="reproducibility",
                passed=True,
                reason=f"{passed_count}/{total} re-runs passed ({fraction:.0%} >= {min_fraction:.0%})",
            )

        return GateResult(
            gate_name="reproducibility",
            passed=False,
            reason=f"Only {passed_count}/{total} re-runs passed ({fraction:.0%} < {min_fraction:.0%})",
        )
