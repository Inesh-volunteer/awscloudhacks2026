"""
run-summarizer Lambda handler.

Aggregates per-lane results from the Step Functions Map state and writes
a consolidated run summary to S3.

Property coverage:
  Property 4: Run summary completeness
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_S3_BUCKET = os.environ.get("ARTIFACT_BUCKET", "autoredteam-artifacts")

_s3_client = None


def _get_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def handler(event: dict, context) -> dict:
    """
    Aggregate per-lane results and write runs/{run_id}/summary.json to S3.

    Property 4 (Run summary completeness): The summary JSON contains an
    entry for every lane, each with outcome, phi_score, and terminal_status.

    Args:
        event: {
            "run_id": str,
            "timestamp": str,
            "lane_results": [
                {
                    "lane_id": str,
                    "status": str,
                    "phi_score": float,
                    "terminal": bool,
                    "error": str | None,
                },
                ...
            ]
        }
        context: Lambda context.

    Returns:
        {"summary_key": str}
    """
    run_id = event["run_id"]
    timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())
    lane_results: list[dict] = event.get("lane_results", [])

    logger.info(json.dumps({
        "event_type": "run_summarizer_start",
        "run_id": run_id,
        "lane_count": len(lane_results),
        "timestamp": timestamp,
    }))

    # Property 4: build per-lane summary entries
    lane_summaries = []
    promotions = 0
    terminal_successes = 0
    failures = 0

    for result in lane_results:
        lane_id = result.get("lane_id") or "unknown"
        status = result.get("status") or "UNKNOWN"
        phi_score_raw = result.get("phi_score")
        phi_score = float(phi_score_raw if phi_score_raw is not None else 0.0)
        terminal = bool(result.get("terminal", False))

        # Property 4: each entry has outcome, phi_score, terminal_status
        lane_summaries.append({
            "lane_id": lane_id,
            "outcome": status,
            "phi_score": phi_score,
            "terminal_status": "TERMINAL_SUCCESS" if terminal else "ACTIVE",
            "error": result.get("error"),
        })

        if status == "SUCCESS":
            promotions += 1
        elif status == "TERMINAL_SUCCESS":
            terminal_successes += 1
        elif status == "FAILED":
            failures += 1

    overall_status = "COMPLETE"
    if failures > 0 and failures < len(lane_results):
        overall_status = "PARTIAL_FAILURE"
    elif failures == len(lane_results):
        overall_status = "FAILED"

    summary = {
        "run_id": run_id,
        "timestamp": timestamp,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": overall_status,
        "lane_count": len(lane_results),
        "promotions": promotions,
        "terminal_successes": terminal_successes,
        "failures": failures,
        "lanes": lane_summaries,  # Property 4: entry for every lane
    }

    # Write to S3
    key = f"runs/{run_id}/summary.json"
    _get_s3().put_object(
        Bucket=_S3_BUCKET,
        Key=key,
        Body=json.dumps(summary, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
    )

    logger.info(json.dumps({
        "event_type": "run_summarizer_complete",
        "run_id": run_id,
        "summary_key": key,
        "status": overall_status,
        "promotions": promotions,
        "terminal_successes": terminal_successes,
        "failures": failures,
    }))

    return {"summary_key": key}
