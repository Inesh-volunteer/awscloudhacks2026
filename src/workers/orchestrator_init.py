"""
orchestrator-init Lambda handler.

Invoked as the first step in the Main Orchestrator Step Functions state machine.
Loads the list of active objective lanes from Parameter Store and returns them
as the input for the Inline Map fan-out.

Property coverage:
  Property 1: Execution payload completeness (run_id + timestamp present)
  Property 2: Lane list round-trip (exact list from SSM returned)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_ENV = os.environ.get("AUTOREDTEAM_ENV", "dev")
_SSM_PREFIX = f"/autoredteam/{_ENV}"
_ACTIVE_LANES_KEY = f"{_SSM_PREFIX}/active_lanes"

_ssm_client = None


def _get_ssm():
    global _ssm_client
    if _ssm_client is None:
        _ssm_client = boto3.client("ssm")
    return _ssm_client


def handler(event: dict, context) -> dict:
    """
    Load active lanes from Parameter Store and return the run payload.

    Property 1: The returned payload always contains a non-empty run_id
    and a valid ISO8601 timestamp.

    Property 2: The lanes list in the output exactly matches the list
    stored in Parameter Store — no lanes added or dropped.

    Args:
        event:   Step Functions input, may contain run_id and timestamp
                 (injected by EventBridge Scheduler).
        context: Lambda context object.

    Returns:
        {
            "run_id": str,
            "timestamp": str,       # ISO8601
            "lanes": [
                {"lane_id": str, "config_prefix": str},
                ...
            ]
        }
    """
    # Property 1: generate run_id if not provided
    run_id = event.get("run_id") or f"run-{uuid.uuid4().hex[:12]}"
    timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat()

    logger.info(
        json.dumps({
            "event_type": "orchestrator_init",
            "run_id": run_id,
            "timestamp": timestamp,
        })
    )

    # Property 2: load active lanes from SSM
    ssm = _get_ssm()
    response = ssm.get_parameter(Name=_ACTIVE_LANES_KEY, WithDecryption=False)
    active_lanes: list[str] = json.loads(response["Parameter"]["Value"])

    if not active_lanes:
        raise ValueError(
            f"No active lanes found at SSM key '{_ACTIVE_LANES_KEY}'"
        )

    # Build lane descriptors for the Inline Map
    lanes = [
        {
            "lane_id": lane_id,
            "config_prefix": f"{_SSM_PREFIX}/lanes/{lane_id}",
        }
        for lane_id in active_lanes
    ]

    logger.info(
        json.dumps({
            "event_type": "orchestrator_init_complete",
            "run_id": run_id,
            "lane_count": len(lanes),
            "lanes": [l["lane_id"] for l in lanes],
        })
    )

    # Property 1: run_id and timestamp always present in output
    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "lanes": lanes,
    }
