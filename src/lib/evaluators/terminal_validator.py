"""
TerminalValidator — evaluates whether an experiment result meets the
terminal success condition for a given objective lane.

Per-lane logic:
  OBJ_WEB_BYPASS:          status==200 AND success_indicator in body
  OBJ_IDENTITY_ESCALATION: privilege_string in body AND non-admin session
  OBJ_WAF_BYPASS:          waf_block_indicator NOT in body AND
                           at least one interpretation_marker in body

Property coverage:
  Property 15: Terminal validator always returns bool (never None/exception)
  Property 34: OBJ_WEB_BYPASS terminal condition
  Property 35: OBJ_IDENTITY_ESCALATION terminal condition
  Property 36: OBJ_WAF_BYPASS terminal condition
"""
from __future__ import annotations

from src.lib.models import (
    ExperimentResult,
    LaneConfig,
    TerminalConditionConfig,
    TerminalResult,
)

# Lane type constants
WEB_BYPASS = "WEB_BYPASS"
IDENTITY_ESCALATION = "IDENTITY_ESCALATION"
WAF_BYPASS = "WAF_BYPASS"


class TerminalValidator:
    """Stateless per-lane terminal condition evaluator."""

    def evaluate(
        self,
        result: ExperimentResult,
        lane_config: LaneConfig,
        session_is_admin: bool = False,
    ) -> TerminalResult:
        """
        Evaluate whether the experiment result meets the terminal condition.

        Args:
            result:           The HTTP experiment result.
            lane_config:      Lane configuration including terminal condition def.
            session_is_admin: True if the DVWA session used is an admin session
                              (relevant for IDENTITY_ESCALATION only).

        Returns:
            TerminalResult with passed=True/False and matched indicator.
            Never raises for valid inputs; always returns a TerminalResult.
        """
        cond = lane_config.terminal_condition
        lane_type = cond.lane_type

        if not result.succeeded or result.response is None:
            return TerminalResult(passed=False, reason="Experiment did not produce a response")

        if lane_type == WEB_BYPASS:
            return self._evaluate_web_bypass(result, cond)
        elif lane_type == IDENTITY_ESCALATION:
            return self._evaluate_identity_escalation(result, cond, session_is_admin)
        elif lane_type == WAF_BYPASS:
            return self._evaluate_waf_bypass(result, cond)
        else:
            return TerminalResult(passed=False, reason=f"Unknown lane type: {lane_type}")

    # ------------------------------------------------------------------
    # OBJ_WEB_BYPASS
    # ------------------------------------------------------------------

    def _evaluate_web_bypass(
        self,
        result: ExperimentResult,
        cond: TerminalConditionConfig,
    ) -> TerminalResult:
        """
        Terminal if: status_code == 200 AND success_indicator in body.
        3xx / 4xx / 5xx always fail regardless of body.
        """
        resp = result.response
        status = resp.status_code

        # Reject non-200 immediately
        if status != 200:
            return TerminalResult(
                passed=False,
                reason=f"HTTP status {status} is not 200",
            )

        indicator = cond.success_indicator or ""
        if indicator and indicator in resp.body:
            return TerminalResult(
                passed=True,
                matched_indicator=indicator,
                reason="Success indicator found in 200 response",
            )

        return TerminalResult(
            passed=False,
            reason="Success indicator not found in response body",
        )

    # ------------------------------------------------------------------
    # OBJ_IDENTITY_ESCALATION
    # ------------------------------------------------------------------

    def _evaluate_identity_escalation(
        self,
        result: ExperimentResult,
        cond: TerminalConditionConfig,
        session_is_admin: bool,
    ) -> TerminalResult:
        """
        Terminal if: privilege_string in body AND session is NOT admin.
        Admin sessions always fail.
        """
        # Admin sessions must never count as a successful escalation
        if session_is_admin:
            return TerminalResult(
                passed=False,
                reason="Session is admin — escalation not valid",
            )

        resp = result.response
        privilege_string = cond.privilege_string or ""

        if privilege_string and privilege_string in resp.body:
            return TerminalResult(
                passed=True,
                matched_indicator=privilege_string,
                reason="Privilege string found in response with non-admin session",
            )

        return TerminalResult(
            passed=False,
            reason="Privilege string not found in response body",
        )

    # ------------------------------------------------------------------
    # OBJ_WAF_BYPASS
    # ------------------------------------------------------------------

    def _evaluate_waf_bypass(
        self,
        result: ExperimentResult,
        cond: TerminalConditionConfig,
    ) -> TerminalResult:
        """
        Terminal if: waf_block_indicator NOT in body AND
                     at least one interpretation_marker IS in body.
        Responses containing the WAF block indicator always fail.
        """
        resp = result.response
        body = resp.body

        block_indicator = cond.waf_block_indicator or ""
        if block_indicator and block_indicator in body:
            return TerminalResult(
                passed=False,
                reason=f"WAF block indicator '{block_indicator}' found in response",
            )

        # Check for at least one interpretation marker
        for marker in cond.interpretation_markers:
            if marker and marker in body:
                return TerminalResult(
                    passed=True,
                    matched_indicator=marker,
                    reason=f"Interpretation marker '{marker}' found without WAF block",
                )

        return TerminalResult(
            passed=False,
            reason="No interpretation markers found in response body",
        )
