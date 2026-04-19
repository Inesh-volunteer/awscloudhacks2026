"""
PhiFunction — computes the scalar progress score Φ_i for an objective lane.

Φ_i = α_i × P_goal + β_i × C_pre + γ_i × D_depth

Result is clamped to [0.0, 1.0].

Property coverage:
  Property 19: Phi computation correctness and range
"""
from __future__ import annotations

from src.lib.models import PhiScores, PhiWeights


class PhiFunction:
    """Stateless weighted-sum scorer."""

    def compute(self, scores: PhiScores, weights: PhiWeights) -> float:
        """
        Compute Φ_i = α × P_goal + β × C_pre + γ × D_depth.

        Args:
            scores:  Sub-scores derived from the Bedrock scoring call.
            weights: Per-lane weights read from Parameter Store.

        Returns:
            A float in [0.0, 1.0].
        """
        raw = (
            weights.alpha * scores.p_goal
            + weights.beta * scores.c_pre
            + weights.gamma * scores.d_depth
        )
        return max(0.0, min(1.0, raw))
