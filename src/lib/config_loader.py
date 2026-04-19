"""
ConfigLoader — reads all required parameters from AWS SSM Parameter Store
at Lambda startup and caches them for the duration of the invocation.

Property coverage:
  Property 5:  MissingConfigError raised for every missing key
  Property 6:  Worker error payload contains lane_id + failure_reason
  Property 31: SSM called only once per invocation (cache)
  Property 32: All SSM paths start with the configured root prefix
"""
from __future__ import annotations

import json
import os
from typing import Optional

import boto3

from src.lib.models import (
    GateThresholds,
    GlobalConfig,
    LaneConfig,
    PhiWeights,
    TerminalConditionConfig,
)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class ConfigLoadError(Exception):
    """Raised when SSM is unreachable."""


class MissingConfigError(Exception):
    """Raised when one or more required SSM keys are absent."""
    def __init__(self, missing_keys: list[str]):
        self.missing_keys = missing_keys
        super().__init__(
            f"Required parameters not found: {', '.join(missing_keys)}"
        )


# ---------------------------------------------------------------------------
# ConfigLoader
# ---------------------------------------------------------------------------

class ConfigLoader:
    """
    Loads and caches all configuration from SSM Parameter Store.

    Usage:
        loader = ConfigLoader(env="prod")
        global_cfg = loader.load_global_config()
        lane_cfg   = loader.load_lane_config("OBJ_WEB_BYPASS")
    """

    def __init__(
        self,
        env: Optional[str] = None,
        ssm_client=None,
    ):
        self._env = env or os.environ.get("AUTOREDTEAM_ENV", "dev")
        self._prefix = f"/autoredteam/{self._env}"
        self._ssm = ssm_client or boto3.client("ssm")
        self._cache: dict[str, str] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_global_config(self) -> GlobalConfig:
        """Load global (non-lane-specific) configuration."""
        self._ensure_loaded_global()
        return GlobalConfig(
            schedule_expression=self._require(f"{self._prefix}/schedule_expression"),
            active_lanes=json.loads(self._require(f"{self._prefix}/active_lanes")),
            bedrock_model_id=self._require(f"{self._prefix}/bedrock_model_id"),
            map_max_concurrency=int(self._require(f"{self._prefix}/map_max_concurrency")),
            dvwa_admin_username=self._require(f"{self._prefix}/dvwa/admin_username"),
            dvwa_admin_password=self._require(f"{self._prefix}/dvwa/admin_password"),
        )

    def load_lane_config(self, lane_id: str) -> LaneConfig:
        """Load lane-specific configuration."""
        self._ensure_loaded_lane(lane_id)
        base = f"{self._prefix}/lanes/{lane_id}"

        terminal_raw = json.loads(self._require(f"{base}/terminal_condition"))
        terminal = TerminalConditionConfig(
            lane_type=terminal_raw["lane_type"],
            success_indicator=terminal_raw.get("success_indicator"),
            privilege_string=terminal_raw.get("privilege_string"),
            waf_block_indicator=terminal_raw.get("waf_block_indicator"),
            interpretation_markers=terminal_raw.get("interpretation_markers", []),
            admin_session_marker=terminal_raw.get("admin_session_marker"),
        )

        weights = PhiWeights(
            alpha=float(self._require(f"{base}/phi_weights/alpha")),
            beta=float(self._require(f"{base}/phi_weights/beta")),
            gamma=float(self._require(f"{base}/phi_weights/gamma")),
        )

        thresholds = GateThresholds(
            reproducibility_min_fraction=float(
                self._require(f"{base}/gate_thresholds/reproducibility_min_fraction")
            ),
            reproducibility_reruns=int(
                self._require(f"{base}/gate_thresholds/reproducibility_reruns")
            ),
            evidence_markers=json.loads(
                self._require(f"{base}/gate_thresholds/evidence_markers")
            ),
            cost_max_tokens=int(
                self._require(f"{base}/gate_thresholds/cost_max_tokens")
            ),
            cost_max_duration_ms=int(
                self._require(f"{base}/gate_thresholds/cost_max_duration_ms")
            ),
            noise_patterns=json.loads(
                self._require(f"{base}/gate_thresholds/noise_patterns")
            ),
        )

        return LaneConfig(
            lane_id=lane_id,
            target_url=self._require(f"{base}/target_url"),
            dvwa_security_level=self._require(f"{base}/dvwa_security_level"),
            terminal_condition=terminal,
            phi_weights=weights,
            gate_thresholds=thresholds,
            bedrock_max_retries=int(self._require(f"{base}/bedrock_max_retries")),
            http_timeout_ms=int(self._require(f"{base}/http_timeout_ms")),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require(self, key: str) -> str:
        """Return cached value for key; raises MissingConfigError if absent."""
        if key not in self._cache:
            raise MissingConfigError([key])
        return self._cache[key]

    def _ensure_loaded_global(self) -> None:
        """Batch-load all global parameters if not already cached."""
        global_paths = [
            f"{self._prefix}/schedule_expression",
            f"{self._prefix}/active_lanes",
            f"{self._prefix}/bedrock_model_id",
            f"{self._prefix}/map_max_concurrency",
            f"{self._prefix}/dvwa/admin_username",
            f"{self._prefix}/dvwa/admin_password",
        ]
        self._batch_load(global_paths)

    def _ensure_loaded_lane(self, lane_id: str) -> None:
        """Batch-load all lane-specific parameters if not already cached."""
        base = f"{self._prefix}/lanes/{lane_id}"
        lane_paths = [
            f"{base}/target_url",
            f"{base}/dvwa_security_level",
            f"{base}/terminal_condition",
            f"{base}/phi_weights/alpha",
            f"{base}/phi_weights/beta",
            f"{base}/phi_weights/gamma",
            f"{base}/gate_thresholds/reproducibility_min_fraction",
            f"{base}/gate_thresholds/reproducibility_reruns",
            f"{base}/gate_thresholds/evidence_markers",
            f"{base}/gate_thresholds/cost_max_tokens",
            f"{base}/gate_thresholds/cost_max_duration_ms",
            f"{base}/gate_thresholds/noise_patterns",
            f"{base}/bedrock_max_retries",
            f"{base}/http_timeout_ms",
        ]
        self._batch_load(lane_paths)

    def _batch_load(self, paths: list[str]) -> None:
        """
        Load parameters in batches of 10 (SSM GetParameters limit).
        Only fetches paths not already in cache.
        Raises MissingConfigError for any path that SSM does not return.
        Raises ConfigLoadError on SSM connectivity failure.
        """
        uncached = [p for p in paths if p not in self._cache]
        if not uncached:
            return

        try:
            # SSM GetParameters accepts up to 10 names per call
            chunk_size = 10
            missing: list[str] = []

            for i in range(0, len(uncached), chunk_size):
                chunk = uncached[i : i + chunk_size]
                response = self._ssm.get_parameters(
                    Names=chunk,
                    WithDecryption=True,
                )
                for param in response.get("Parameters", []):
                    self._cache[param["Name"]] = param["Value"]

                # Collect any keys SSM did not return
                returned = {p["Name"] for p in response.get("Parameters", [])}
                missing.extend(k for k in chunk if k not in returned)

            if missing:
                raise MissingConfigError(missing)

        except MissingConfigError:
            raise
        except Exception as exc:
            raise ConfigLoadError(
                f"Failed to load parameters from SSM: {exc}"
            ) from exc
