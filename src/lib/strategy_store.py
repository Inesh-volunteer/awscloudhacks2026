"""
StrategyStore — reads and writes Strategy objects to S3.

S3 key scheme:
  strategies/{lane_id}/current.json          — active strategy
  strategies/{lane_id}/history/{timestamp}.json — archived versions

Property coverage:
  Property 14: Artifact key scoping
  Property 26: Strategy promotion on all-gates-pass
  Property 28: Strategy history preservation
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from src.lib.models import Mutation, Strategy

logger = logging.getLogger(__name__)


class ArtifactStoreError(Exception):
    """Raised when an S3 read or write operation fails."""


class StrategyStore:
    """Reads and writes Strategy objects to S3.

    Args:
        bucket:    S3 bucket name.
        s3_client: Optional pre-built boto3 S3 client (for testing).
    """

    def __init__(self, bucket: str, s3_client=None) -> None:
        self._bucket = bucket
        self._s3 = s3_client or boto3.client("s3")

    # ------------------------------------------------------------------
    # Key helpers (Property 14)
    # ------------------------------------------------------------------

    @staticmethod
    def current_key(lane_id: str) -> str:
        """Return the S3 key for the active strategy."""
        return f"strategies/{lane_id}/current.json"

    @staticmethod
    def history_key(lane_id: str, timestamp: str) -> str:
        """Return the S3 key for an archived strategy version."""
        return f"strategies/{lane_id}/history/{timestamp}.json"

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_current(self, lane_id: str) -> Optional[Strategy]:
        """Fetch the current best strategy for a lane from S3.

        Returns None if no strategy exists yet (first run).

        Args:
            lane_id: The objective lane identifier.

        Returns:
            The current Strategy, or None if absent.

        Raises:
            ArtifactStoreError: On unexpected S3 errors.
        """
        key = self.current_key(lane_id)
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=key)
            data = json.loads(response["Body"].read().decode("utf-8"))
            return Strategy.from_dict(data)
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("NoSuchKey", "404"):
                return None
            raise ArtifactStoreError(
                f"S3 error reading strategy for lane '{lane_id}': {exc}"
            ) from exc
        except Exception as exc:
            raise ArtifactStoreError(
                f"Unexpected error reading strategy for lane '{lane_id}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Write / promote (Properties 26, 28)
    # ------------------------------------------------------------------

    def promote(self, lane_id: str, strategy: Strategy) -> None:
        """Promote a new strategy as the current best for a lane.

        Steps:
        1. Archive the existing current strategy to history/ (Property 28).
        2. Write the new strategy to current.json (Property 26).

        Args:
            lane_id:  The objective lane identifier.
            strategy: The new Strategy to promote.

        Raises:
            ArtifactStoreError: On S3 write failure.
        """
        # Step 1: archive existing current strategy if present
        existing = self.get_current(lane_id)
        if existing is not None:
            self.archive(lane_id, existing)

        # Step 2: write new strategy to current.json (Property 26)
        key = self.current_key(lane_id)
        self._put_json(key, strategy.to_dict())
        logger.info(
            "Strategy promoted for lane '%s' at key '%s' (phi=%.4f)",
            lane_id,
            key,
            strategy.phi_score,
        )

    def archive(self, lane_id: str, strategy: Strategy) -> None:
        """Archive a strategy version to history/.

        Property 28: Each promotion creates exactly one history entry,
        preserving the full prior strategy.

        Args:
            lane_id:  The objective lane identifier.
            strategy: The strategy version to archive.

        Raises:
            ArtifactStoreError: On S3 write failure.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        key = self.history_key(lane_id, timestamp)
        self._put_json(key, strategy.to_dict())
        logger.debug("Strategy archived for lane '%s' at key '%s'", lane_id, key)

    # ------------------------------------------------------------------
    # Seed strategy
    # ------------------------------------------------------------------

    def get_or_create_seed(self, lane_id: str, run_id: str) -> Strategy:
        """Return the current strategy, or create and store a seed if absent.

        Args:
            lane_id: The objective lane identifier.
            run_id:  The current run identifier (used in seed metadata).

        Returns:
            The existing or newly created seed Strategy.
        """
        existing = self.get_current(lane_id)
        if existing is not None:
            return existing

        now = datetime.now(timezone.utc).isoformat()
        seed = Strategy(
            lane_id=lane_id,
            version=0,
            phi_score=0.0,
            created_at=now,
            promoted_at=now,
            run_id=run_id,
            mutation=Mutation(
                attack_payload="",
                target_endpoint="/",
                http_method="GET",
                headers={},
                rationale="Seed strategy — no prior experiments",
            ),
            experiment_evidence=None,
        )
        key = self.current_key(lane_id)
        self._put_json(key, seed.to_dict())
        logger.info("Seed strategy created for lane '%s'", lane_id)
        return seed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _put_json(self, key: str, data: dict) -> None:
        """Write a JSON-serialisable dict to S3."""
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception as exc:
            raise ArtifactStoreError(
                f"S3 write failed for key '{key}': {exc}"
            ) from exc
