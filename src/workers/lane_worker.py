"""
lane-worker Lambda handler.

Executes one full experiment cycle for a single objective lane:
  1.  Load config from Parameter Store
  2.  Fetch current Strategy from S3
  3.  Set DVWA security level via /security.php
  4.  Call Bedrock (mutation planning)
  5.  Execute HTTP experiment against DVWA
  6.  Check Terminal Validator
  7.  Call Bedrock (scoring) → derive P_goal, C_pre, D_depth → Phi
  8.  If Phi improves: trigger Reproducibility sub-machine
  9.  Evaluate Evidence, Cost, and Noise gates
  10. Ratchet: promote or discard

Property coverage:
  Property 3:  Lane failure isolation (errors return structured payload)
  Property 16: Terminal success fast-path skips gates
  Property 17: Terminal success evidence persistence
  Property 37: Structured log format
  Property 38: CloudWatch metric emission
  Property 39: Timeout warning metric emission
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import boto3

from src.lib.bedrock_client import BedrockClient
from src.lib.config_loader import ConfigLoadError, ConfigLoader, MissingConfigError
from src.lib.dvwa_client import (
    DVWAClient,
    DVWATimeoutError,
    DVWAUnreachableError,
    SecurityLevelVerificationError,
)
from src.lib.evaluators.gates import GateEvaluator
from src.lib.evaluators.phi_function import PhiFunction
from src.lib.evaluators.terminal_validator import TerminalValidator
from src.lib.models import LaneStateUpdate, Mutation, Strategy
from src.lib.state_store import StateStore
from src.lib.strategy_store import StrategyStore

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_ENV = os.environ.get("AUTOREDTEAM_ENV", "dev")
_S3_BUCKET = os.environ.get("ARTIFACT_BUCKET", "autoredteam-artifacts")
_REPRO_SFN_ARN = os.environ.get("REPRODUCIBILITY_SFN_ARN", "")
_LAMBDA_TIMEOUT_MS = int(os.environ.get("LAMBDA_TIMEOUT_MS", "300000"))  # 5 min default

_cw_client = None
_sfn_client = None


def _get_cw():
    global _cw_client
    if _cw_client is None:
        _cw_client = boto3.client("cloudwatch")
    return _cw_client


def _get_sfn():
    global _sfn_client
    if _sfn_client is None:
        _sfn_client = boto3.client("stepfunctions")
    return _sfn_client


# ---------------------------------------------------------------------------
# Structured logging helper (Property 37)
# ---------------------------------------------------------------------------

def _log(event_type: str, lane_id: str, run_id: str, **kwargs) -> None:
    """Emit a structured JSON log entry.

    Property 37: Every log entry contains event_type, lane_id, and timestamp.
    """
    entry = {
        "event_type": event_type,
        "lane_id": lane_id,
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    logger.info(json.dumps(entry))


# ---------------------------------------------------------------------------
# CloudWatch metric helpers (Properties 38, 39)
# ---------------------------------------------------------------------------

def _emit_phi_metric(lane_id: str, run_id: str, phi_score: float) -> None:
    """Property 38: Emit RedTeam/PhiScore metric after each ratchet decision."""
    try:
        _get_cw().put_metric_data(
            Namespace="RedTeam",
            MetricData=[{
                "MetricName": "PhiScore",
                "Dimensions": [
                    {"Name": "LaneId", "Value": lane_id},
                    {"Name": "RunId", "Value": run_id},
                ],
                "Value": phi_score,
                "Unit": "None",
            }],
        )
    except Exception as exc:
        logger.warning("Failed to emit PhiScore metric: %s", exc)


def _emit_gate_failure_metric(lane_id: str, gate_name: str) -> None:
    """Property 38: Emit RedTeam/GateFailures metric on gate failure."""
    try:
        _get_cw().put_metric_data(
            Namespace="RedTeam",
            MetricData=[{
                "MetricName": "GateFailures",
                "Dimensions": [
                    {"Name": "LaneId", "Value": lane_id},
                    {"Name": "GateName", "Value": gate_name},
                ],
                "Value": 1,
                "Unit": "Count",
            }],
        )
    except Exception as exc:
        logger.warning("Failed to emit GateFailures metric: %s", exc)


def _emit_timeout_warning(lane_id: str) -> None:
    """Property 39: Emit RedTeam/TimeoutWarning if >80% of timeout elapsed."""
    try:
        _get_cw().put_metric_data(
            Namespace="RedTeam",
            MetricData=[{
                "MetricName": "TimeoutWarning",
                "Dimensions": [{"Name": "LaneId", "Value": lane_id}],
                "Value": 1,
                "Unit": "Count",
            }],
        )
    except Exception as exc:
        logger.warning("Failed to emit TimeoutWarning metric: %s", exc)


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    """
    Execute one full experiment cycle for a single objective lane.

    Property 3 (Lane failure isolation): All exceptions are caught and
    returned as structured error payloads so the Step Functions Map state
    can continue processing other lanes.

    Args:
        event: {
            "run_id": str,
            "lane_id": str,
            "config_prefix": str,
        }
        context: Lambda context.

    Returns:
        {
            "lane_id": str,
            "status": "SUCCESS" | "TERMINAL_SUCCESS" | "FAILED" | "DISCARDED",
            "phi_score": float,
            "terminal": bool,
            "error": str | None,
        }
    """
    run_id = event.get("run_id", "unknown")
    lane_id = event.get("lane_id", "unknown")
    invocation_start_ms = int(time.monotonic() * 1000)

    _log("lane_worker_start", lane_id, run_id)

    try:
        return _run_cycle(run_id, lane_id, invocation_start_ms, context)
    except Exception as exc:
        # Property 3: structured error payload — never let the exception propagate
        _log("lane_worker_error", lane_id, run_id, error=str(exc), error_type=type(exc).__name__)
        return {
            "lane_id": lane_id,
            "run_id": run_id,
            "status": "FAILED",
            "phi_score": 0.0,
            "terminal": False,
            "error": str(exc),
        }


def _run_cycle(run_id: str, lane_id: str, invocation_start_ms: int, context) -> dict:
    """Core experiment cycle logic."""

    # ------------------------------------------------------------------
    # Step 1: Load config (Property 37: log initialization)
    # ------------------------------------------------------------------
    _log("initialization", lane_id, run_id)
    loader = ConfigLoader(env=_ENV)
    try:
        lane_config = loader.load_lane_config(lane_id)
        global_config = loader.load_global_config()
    except (MissingConfigError, ConfigLoadError) as exc:
        raise RuntimeError(f"Config load failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Step 2: Fetch current Strategy
    # ------------------------------------------------------------------
    _log("strategy_fetch", lane_id, run_id)
    strategy_store = StrategyStore(bucket=_S3_BUCKET)
    strategy = strategy_store.get_or_create_seed(lane_id, run_id)

    state_store = StateStore()
    state_store.initialize_lane(lane_id, run_id)
    lane_state = state_store.get_lane_state(lane_id)
    current_phi = lane_state.phi_score if lane_state else 0.0

    # ------------------------------------------------------------------
    # Step 3: Set DVWA security level
    # ------------------------------------------------------------------
    _log("dvwa_security_level_set", lane_id, run_id,
         level=lane_config.dvwa_security_level)
    dvwa = DVWAClient(
        base_url=lane_config.target_url,
        username=global_config.dvwa_admin_username,
        password=global_config.dvwa_admin_password,
        timeout_ms=lane_config.http_timeout_ms,
    )
    dvwa.set_security_level(lane_config.dvwa_security_level)

    # ------------------------------------------------------------------
    # Step 4: Mutation planning
    # ------------------------------------------------------------------
    _log("mutation_proposal", lane_id, run_id)
    bedrock = BedrockClient(
        model_id=global_config.bedrock_model_id,
        max_retries=lane_config.bedrock_max_retries,
        s3_bucket=_S3_BUCKET,
    )
    mutation = bedrock.propose_mutation(
        lane_def=lane_config,
        strategy=strategy,
        last_result=strategy.experiment_evidence,
        run_id=run_id,
        lane_id=lane_id,
    )

    # ------------------------------------------------------------------
    # Step 5: Execute experiment
    # ------------------------------------------------------------------
    _log("experiment_execution", lane_id, run_id,
         endpoint=mutation.target_endpoint, method=mutation.http_method)
    try:
        experiment_result = dvwa.execute_request(mutation, run_id=run_id, lane_id=lane_id)
    except DVWAUnreachableError as exc:
        state_store.update_lane_state(lane_id, LaneStateUpdate(last_run_id=run_id))
        raise RuntimeError(f"DVWA unreachable: {exc}") from exc
    except DVWATimeoutError as exc:
        raise RuntimeError(f"DVWA timeout: {exc}") from exc

    # Persist raw experiment artifact
    _put_experiment_artifact(experiment_result, run_id, lane_id)

    # ------------------------------------------------------------------
    # Step 6: Terminal Validator (Property 16: fast-path skips gates)
    # ------------------------------------------------------------------
    _log("terminal_check", lane_id, run_id)
    validator = TerminalValidator()
    terminal_result = validator.evaluate(experiment_result, lane_config)

    if terminal_result.passed:
        # Property 16: terminal success → promote immediately, skip gates
        _log("terminal_success", lane_id, run_id,
             matched_indicator=terminal_result.matched_indicator)

        # Property 17: persist terminal evidence
        _put_terminal_evidence(experiment_result, mutation, terminal_result, run_id, lane_id)

        new_strategy = Strategy(
            lane_id=lane_id,
            version=(strategy.version + 1),
            phi_score=1.0,
            created_at=strategy.created_at,
            promoted_at=datetime.now(timezone.utc).isoformat(),
            run_id=run_id,
            mutation=mutation,
            experiment_evidence=experiment_result,
        )
        strategy_store.promote(lane_id, new_strategy)
        state_store.mark_terminal_success(lane_id, run_id, phi_score=1.0)
        _emit_phi_metric(lane_id, run_id, 1.0)

        return {
            "lane_id": lane_id,
            "run_id": run_id,
            "status": "TERMINAL_SUCCESS",
            "phi_score": 1.0,
            "terminal": True,
            "error": None,
        }

    # ------------------------------------------------------------------
    # Step 7: Phi scoring (separate Bedrock call — Property 18)
    # ------------------------------------------------------------------
    _log("phi_scoring", lane_id, run_id)
    phi_scores = bedrock.score_experiment(
        experiment_result=experiment_result,
        lane_rubric=lane_config.terminal_condition,
        strategy=strategy,
        run_id=run_id,
        lane_id=lane_id,
    )
    new_phi = PhiFunction().compute(phi_scores, lane_config.phi_weights)

    _log("phi_computed", lane_id, run_id,
         new_phi=new_phi, current_phi=current_phi,
         p_goal=phi_scores.p_goal, c_pre=phi_scores.c_pre, d_depth=phi_scores.d_depth)

    # Property 20: discard if Phi does not improve
    if new_phi <= current_phi:
        _log("ratchet_discard", lane_id, run_id,
             reason="phi_not_improved", new_phi=new_phi, current_phi=current_phi)
        state_store.increment_discard_counter(lane_id)
        state_store.update_lane_state(lane_id, LaneStateUpdate(last_run_id=run_id))
        _emit_phi_metric(lane_id, run_id, new_phi)
        _check_timeout_warning(lane_id, invocation_start_ms)
        return {
            "lane_id": lane_id,
            "run_id": run_id,
            "status": "DISCARDED",
            "phi_score": new_phi,
            "terminal": False,
            "error": None,
        }

    # ------------------------------------------------------------------
    # Step 8: Reproducibility Gate (nested Step Functions sub-machine)
    # ------------------------------------------------------------------
    _log("gate_evaluation_reproducibility", lane_id, run_id)
    repro_passed = _run_reproducibility_gate(
        run_id=run_id,
        lane_id=lane_id,
        mutation=mutation,
        current_phi=current_phi,
        lane_config=lane_config,
    )

    if not repro_passed:
        _log("gate_failure", lane_id, run_id, gate="reproducibility")
        state_store.update_lane_state(
            lane_id,
            LaneStateUpdate(last_run_id=run_id, last_gate_failure="reproducibility"),
        )
        state_store.increment_discard_counter(lane_id)
        _emit_gate_failure_metric(lane_id, "reproducibility")
        _emit_phi_metric(lane_id, run_id, new_phi)
        _check_timeout_warning(lane_id, invocation_start_ms)
        return {
            "lane_id": lane_id,
            "run_id": run_id,
            "status": "DISCARDED",
            "phi_score": new_phi,
            "terminal": False,
            "error": None,
        }

    # ------------------------------------------------------------------
    # Step 9: Evidence, Cost, Noise gates
    # ------------------------------------------------------------------
    gate_evaluator = GateEvaluator()
    elapsed_ms = int(time.monotonic() * 1000) - invocation_start_ms
    token_usage = (
        int(phi_scores.p_goal * 1000)  # placeholder — real usage tracked in bedrock_client
    )

    gates = [
        gate_evaluator.evaluate_evidence(experiment_result, lane_config),
        gate_evaluator.evaluate_cost(token_usage, elapsed_ms, lane_config),
        gate_evaluator.evaluate_noise(experiment_result, lane_config),
    ]

    for gate_result in gates:
        _log("gate_evaluation", lane_id, run_id,
             gate=gate_result.gate_name, passed=gate_result.passed,
             reason=gate_result.reason)
        if not gate_result.passed:
            state_store.update_lane_state(
                lane_id,
                LaneStateUpdate(
                    last_run_id=run_id,
                    last_gate_failure=gate_result.gate_name,
                ),
            )
            state_store.increment_discard_counter(lane_id)
            _emit_gate_failure_metric(lane_id, gate_result.gate_name)
            _emit_phi_metric(lane_id, run_id, new_phi)
            _check_timeout_warning(lane_id, invocation_start_ms)
            return {
                "lane_id": lane_id,
                "run_id": run_id,
                "status": "DISCARDED",
                "phi_score": new_phi,
                "terminal": False,
                "error": None,
            }

    # ------------------------------------------------------------------
    # Step 10: Ratchet — promote (Properties 26, 27)
    # ------------------------------------------------------------------
    _log("ratchet_promote", lane_id, run_id, new_phi=new_phi)

    new_strategy = Strategy(
        lane_id=lane_id,
        version=(strategy.version + 1),
        phi_score=new_phi,
        created_at=strategy.created_at,
        promoted_at=datetime.now(timezone.utc).isoformat(),
        run_id=run_id,
        mutation=mutation,
        experiment_evidence=experiment_result,
    )
    strategy_store.promote(lane_id, new_strategy)
    state_store.update_lane_state(
        lane_id,
        LaneStateUpdate(phi_score=new_phi, last_run_id=run_id),
    )
    _emit_phi_metric(lane_id, run_id, new_phi)
    _check_timeout_warning(lane_id, invocation_start_ms)

    return {
        "lane_id": lane_id,
        "run_id": run_id,
        "status": "SUCCESS",
        "phi_score": new_phi,
        "terminal": False,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_reproducibility_gate(
    run_id: str,
    lane_id: str,
    mutation: Mutation,
    current_phi: float,
    lane_config,
) -> bool:
    """Trigger the Reproducibility sub-machine synchronously and return pass/fail."""
    if not _REPRO_SFN_ARN:
        logger.warning("REPRODUCIBILITY_SFN_ARN not set — skipping reproducibility gate")
        return True

    reruns = lane_config.gate_thresholds.reproducibility_reruns
    min_fraction = lane_config.gate_thresholds.reproducibility_min_fraction

    sfn_input = {
        "run_id": run_id,
        "lane_id": lane_id,
        "mutation": mutation.to_dict(),
        "current_phi_score": current_phi,
        "reruns": [{"rerun_index": i} for i in range(reruns)],
        "min_fraction": min_fraction,
    }

    try:
        response = _get_sfn().start_sync_execution(
            stateMachineArn=_REPRO_SFN_ARN,
            input=json.dumps(sfn_input),
        )
        if response["status"] == "SUCCEEDED":
            output = json.loads(response.get("output", "{}"))
            return output.get("gate_passed", False)
        return False
    except Exception as exc:
        logger.warning("Reproducibility sub-machine failed: %s", exc)
        return False


def _put_experiment_artifact(experiment_result, run_id: str, lane_id: str) -> None:
    """Write raw experiment result to S3."""
    try:
        s3 = boto3.client("s3")
        key = f"runs/{run_id}/{lane_id}/experiment_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
        s3.put_object(
            Bucket=_S3_BUCKET,
            Key=key,
            Body=json.dumps(experiment_result.to_dict(), default=str).encode(),
            ContentType="application/json",
        )
    except Exception as exc:
        logger.warning("Failed to write experiment artifact: %s", exc)


def _put_terminal_evidence(
    experiment_result, mutation: Mutation, terminal_result, run_id: str, lane_id: str
) -> None:
    """Property 17: Write terminal success evidence to S3."""
    try:
        s3 = boto3.client("s3")
        key = f"runs/{run_id}/{lane_id}/terminal_success.json"
        evidence = {
            "experiment_result": experiment_result.to_dict(),
            "mutation": mutation.to_dict(),
            "matched_indicator": terminal_result.matched_indicator,
            "reason": terminal_result.reason,
        }
        s3.put_object(
            Bucket=_S3_BUCKET,
            Key=key,
            Body=json.dumps(evidence, default=str).encode(),
            ContentType="application/json",
        )
    except Exception as exc:
        logger.warning("Failed to write terminal evidence: %s", exc)


def _check_timeout_warning(lane_id: str, invocation_start_ms: int) -> None:
    """Property 39: Emit TimeoutWarning if >80% of Lambda timeout elapsed."""
    elapsed = int(time.monotonic() * 1000) - invocation_start_ms
    if elapsed > 0.8 * _LAMBDA_TIMEOUT_MS:
        _emit_timeout_warning(lane_id)
