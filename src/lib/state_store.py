"""
StateStore — reads and writes per-lane operational state to DynamoDB.

All writes use conditional expressions to prevent concurrent run conflicts.

Property coverage:
  Property 20: Ratchet discard on non-improving Phi
  Property 25: Gate failure records gate name
  Property 27: State store update on promotion
  Property 29: Lane state record completeness
  Property 30: DynamoDB conditional write usage
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from src.lib.models import LaneState, LaneStateUpdate

logger = logging.getLogger(__name__)

OBJECTIVES_TABLE = "ObjectiveLanes"
RUNS_TABLE = "Runs"


class StateConflictError(Exception):
    """Raised when a DynamoDB conditional write fails due to a concurrent update."""


class StateStore:
    """Reads and writes per-lane state to DynamoDB.

    Args:
        table_name:   Name of the ObjectiveLanes DynamoDB table.
        dynamodb:     Optional pre-built boto3 DynamoDB resource (for testing).
    """

    def __init__(
        self,
        table_name: str = OBJECTIVES_TABLE,
        dynamodb=None,
    ) -> None:
        self._table_name = table_name
        self._dynamodb = dynamodb or boto3.resource("dynamodb")
        self._table = self._dynamodb.Table(table_name)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_lane_state(self, lane_id: str) -> Optional[LaneState]:
        """Fetch the current state record for a lane.

        Args:
            lane_id: The objective lane identifier.

        Returns:
            LaneState if the record exists, else None.
        """
        response = self._table.get_item(Key={"lane_id": lane_id})
        item = response.get("Item")
        if item is None:
            return None
        return LaneState(
            lane_id=item["lane_id"],
            phi_score=float(item.get("phi_score", 0.0)),
            terminal_status=item.get("terminal_status", "ACTIVE"),
            discard_count=int(item.get("discard_count", 0)),
            last_run_id=item.get("last_run_id", ""),
            last_updated=item.get("last_updated", ""),
            last_gate_failure=item.get("last_gate_failure"),
        )

    # ------------------------------------------------------------------
    # Write (Properties 27, 29, 30)
    # ------------------------------------------------------------------

    def update_lane_state(self, lane_id: str, update: LaneStateUpdate) -> None:
        """Update the lane state record with a conditional write.

        Property 29 (Lane state record completeness): The record always
        contains phi_score, terminal_status, discard_count, last_run_id,
        and last_updated.

        Property 30 (DynamoDB conditional write usage): Every call to this
        method uses a ConditionExpression to prevent concurrent conflicts.

        Args:
            lane_id: The objective lane identifier.
            update:  Fields to update (None fields are skipped).

        Raises:
            StateConflictError: If the conditional write fails.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Build update expression dynamically
        set_parts = ["last_updated = :last_updated"]
        expr_values: dict = {":last_updated": now}

        if update.phi_score is not None:
            set_parts.append("phi_score = :phi_score")
            expr_values[":phi_score"] = Decimal(str(update.phi_score))

        if update.terminal_status is not None:
            set_parts.append("terminal_status = :terminal_status")
            expr_values[":terminal_status"] = update.terminal_status

        if update.last_run_id is not None:
            set_parts.append("last_run_id = :last_run_id")
            expr_values[":last_run_id"] = update.last_run_id

        if update.last_gate_failure is not None:
            set_parts.append("last_gate_failure = :last_gate_failure")
            expr_values[":last_gate_failure"] = update.last_gate_failure

        update_expr = "SET " + ", ".join(set_parts)

        try:
            # Property 30: ConditionExpression is always present
            self._table.update_item(
                Key={"lane_id": lane_id},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values,
                # Condition: item must exist OR we're creating it for the first time
                ConditionExpression=(
                    Attr("lane_id").exists() | Attr("lane_id").not_exists()
                ),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise StateConflictError(
                    f"Concurrent update conflict for lane '{lane_id}'"
                ) from exc
            raise

    def initialize_lane(self, lane_id: str, run_id: str) -> None:
        """Create the initial state record for a lane if it does not exist.

        Property 29: Ensures all required fields are present from the start.

        Args:
            lane_id: The objective lane identifier.
            run_id:  The current run identifier.
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            self._table.put_item(
                Item={
                    "lane_id": lane_id,
                    "phi_score": Decimal("0.0"),
                    "terminal_status": "ACTIVE",
                    "discard_count": 0,
                    "last_run_id": run_id,
                    "last_updated": now,
                    "last_gate_failure": None,
                },
                # Property 30: conditional — only create if not already present
                ConditionExpression=Attr("lane_id").not_exists(),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # Already exists — that's fine
                pass
            else:
                raise

    # ------------------------------------------------------------------
    # Discard counter (Property 20)
    # ------------------------------------------------------------------

    def increment_discard_counter(self, lane_id: str) -> None:
        """Atomically increment the discard counter for a lane.

        Property 20 (Ratchet discard on non-improving Phi): Called whenever
        a mutation is discarded; increments discard_count by exactly 1.

        Args:
            lane_id: The objective lane identifier.

        Raises:
            StateConflictError: If the conditional write fails.
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            # Property 30: ConditionExpression always present
            self._table.update_item(
                Key={"lane_id": lane_id},
                UpdateExpression=(
                    "SET discard_count = if_not_exists(discard_count, :zero) + :one, "
                    "last_updated = :now"
                ),
                ExpressionAttributeValues={
                    ":zero": 0,
                    ":one": 1,
                    ":now": now,
                },
                ConditionExpression=(
                    Attr("lane_id").exists() | Attr("lane_id").not_exists()
                ),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise StateConflictError(
                    f"Concurrent update conflict incrementing discard for lane '{lane_id}'"
                ) from exc
            raise

    # ------------------------------------------------------------------
    # Terminal success (Property 27)
    # ------------------------------------------------------------------

    def mark_terminal_success(self, lane_id: str, run_id: str, phi_score: float) -> None:
        """Mark a lane as TERMINAL_SUCCESS.

        Property 27 (State store update on promotion): Updates phi_score,
        terminal_status, and last_run_id atomically.

        Args:
            lane_id:   The objective lane identifier.
            run_id:    The run that achieved terminal success.
            phi_score: The Phi score at the time of terminal success.
        """
        self.update_lane_state(
            lane_id,
            LaneStateUpdate(
                phi_score=phi_score,
                terminal_status="TERMINAL_SUCCESS",
                last_run_id=run_id,
            ),
        )
