"""
reproducibility-runner Lambda handler.

Invoked by the Reproducibility Sub-Machine's Inline Map.
Re-runs a single mutation against DVWA and returns pass/fail.
"""
from __future__ import annotations

import json
import logging
import os

from src.lib.bedrock_client import BedrockClient
from src.lib.config_loader import ConfigLoader
from src.lib.dvwa_client import DVWAClient, DVWATimeoutError, DVWAUnreachableError
from src.lib.evaluators.phi_function import PhiFunction
from src.lib.evaluators.terminal_validator import TerminalValidator
from src.lib.models import Mutation

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_ENV = os.environ.get("AUTOREDTEAM_ENV", "dev")
_S3_BUCKET = os.environ.get("ARTIFACT_BUCKET", "autoredteam-artifacts")
_BEDROCK_MODEL = os.environ.get(
    "BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0"
)


def handler(event: dict, context) -> dict:
    """
    Re-run a single mutation and return pass/fail for the Reproducibility Gate.

    Args:
        event: {
            "run_id": str,
            "lane_id": str,
            "mutation": dict,       # Mutation.to_dict()
            "rerun_index": int,
            "current_phi_score": float,
        }
        context: Lambda context.

    Returns:
        {
            "rerun_index": int,
            "passed": bool,
            "phi_score": float,
            "terminal": bool,
        }
    """
    run_id = event["run_id"]
    lane_id = event["lane_id"]
    rerun_index = event.get("rerun_index", 0)
    current_phi = float(event.get("current_phi_score", 0.0))
    mutation = Mutation.from_dict(event["mutation"])

    logger.info(json.dumps({
        "event_type": "reproducibility_runner_start",
        "run_id": run_id,
        "lane_id": lane_id,
        "rerun_index": rerun_index,
    }))

    # Load config
    loader = ConfigLoader(env=_ENV)
    lane_config = loader.load_lane_config(lane_id)
    global_config = loader.load_global_config()

    # Connect to DVWA
    dvwa = DVWAClient(
        base_url=lane_config.target_url,
        username=global_config.dvwa_admin_username,
        password=global_config.dvwa_admin_password,
        timeout_ms=lane_config.http_timeout_ms,
    )

    # Execute the mutation
    try:
        result = dvwa.execute_request(mutation, run_id=run_id, lane_id=lane_id)
    except (DVWAUnreachableError, DVWATimeoutError) as exc:
        logger.warning(json.dumps({
            "event_type": "reproducibility_dvwa_error",
            "run_id": run_id,
            "lane_id": lane_id,
            "rerun_index": rerun_index,
            "error": str(exc),
        }))
        return {"rerun_index": rerun_index, "passed": False, "phi_score": 0.0, "terminal": False}

    # Terminal check
    validator = TerminalValidator()
    terminal_result = validator.evaluate(result, lane_config)
    if terminal_result.passed:
        return {"rerun_index": rerun_index, "passed": True, "phi_score": 1.0, "terminal": True}

    # Phi scoring
    bedrock = BedrockClient(
        model_id=_BEDROCK_MODEL,
        max_retries=lane_config.bedrock_max_retries,
        s3_bucket=_S3_BUCKET,
    )
    phi_scores = bedrock.score_experiment(result, lane_config, None, run_id, lane_id)
    phi_value = PhiFunction().compute(phi_scores, lane_config.phi_weights)

    passed = phi_value > current_phi

    logger.info(json.dumps({
        "event_type": "reproducibility_runner_complete",
        "run_id": run_id,
        "lane_id": lane_id,
        "rerun_index": rerun_index,
        "phi_score": phi_value,
        "passed": passed,
    }))

    return {
        "rerun_index": rerun_index,
        "passed": passed,
        "phi_score": phi_value,
        "terminal": False,
    }
