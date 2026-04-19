"""
Shared data models for the AutoRedTeam Lambda Harness.
All dataclasses use slots=True for memory efficiency inside Lambda.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------

@dataclass
class Mutation:
    """A Bedrock-proposed attack variant to test against DVWA."""
    attack_payload: str
    target_endpoint: str
    http_method: str          # GET | POST | PUT | DELETE
    headers: dict[str, str]
    rationale: str

    def to_dict(self) -> dict:
        return {
            "attack_payload": self.attack_payload,
            "target_endpoint": self.target_endpoint,
            "http_method": self.http_method,
            "headers": self.headers,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Mutation":
        return cls(
            attack_payload=d["attack_payload"],
            target_endpoint=d["target_endpoint"],
            http_method=d["http_method"],
            headers=d.get("headers", {}),
            rationale=d["rationale"],
        )


# ---------------------------------------------------------------------------
# Experiment Result
# ---------------------------------------------------------------------------

@dataclass
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: str


@dataclass
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    body: str
    elapsed_ms: int


@dataclass
class ExperimentResult:
    """Raw HTTP request/response captured during an experiment."""
    run_id: str
    lane_id: str
    timestamp: str            # ISO8601
    request: HttpRequest
    response: Optional[HttpResponse] = None
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.response is not None and self.error is None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "lane_id": self.lane_id,
            "timestamp": self.timestamp,
            "request": {
                "method": self.request.method,
                "url": self.request.url,
                "headers": self.request.headers,
                "body": self.request.body,
            },
            "response": {
                "status_code": self.response.status_code,
                "headers": self.response.headers,
                "body": self.response.body,
                "elapsed_ms": self.response.elapsed_ms,
            } if self.response else None,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Phi Scores
# ---------------------------------------------------------------------------

@dataclass
class PhiScores:
    """Sub-scores derived from the Bedrock scoring call."""
    p_goal: float    # goal likelihood  [0.0, 1.0]
    c_pre: float     # precondition completion [0.0, 1.0]
    d_depth: float   # exploit chain depth [0.0, 1.0]

    def to_dict(self) -> dict:
        return {"p_goal": self.p_goal, "c_pre": self.c_pre, "d_depth": self.d_depth}


@dataclass
class PhiWeights:
    """Per-lane weights for the Phi weighted sum."""
    alpha: float   # weight for p_goal
    beta: float    # weight for c_pre
    gamma: float   # weight for d_depth


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

@dataclass
class Strategy:
    """Current best attack strategy for an objective lane, stored in S3."""
    lane_id: str
    version: int
    phi_score: float
    created_at: str           # ISO8601
    promoted_at: str          # ISO8601
    run_id: str
    mutation: Mutation
    experiment_evidence: Optional[ExperimentResult] = None

    def to_dict(self) -> dict:
        return {
            "lane_id": self.lane_id,
            "version": self.version,
            "phi_score": self.phi_score,
            "created_at": self.created_at,
            "promoted_at": self.promoted_at,
            "run_id": self.run_id,
            "mutation": self.mutation.to_dict(),
            "experiment_evidence": self.experiment_evidence.to_dict()
            if self.experiment_evidence else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Strategy":
        evidence = None
        if d.get("experiment_evidence"):
            ev = d["experiment_evidence"]
            req = ev["request"]
            resp = ev.get("response")
            evidence = ExperimentResult(
                run_id=ev["run_id"],
                lane_id=ev["lane_id"],
                timestamp=ev["timestamp"],
                request=HttpRequest(**req),
                response=HttpResponse(**resp) if resp else None,
                error=ev.get("error"),
            )
        return cls(
            lane_id=d["lane_id"],
            version=d["version"],
            phi_score=d["phi_score"],
            created_at=d["created_at"],
            promoted_at=d["promoted_at"],
            run_id=d["run_id"],
            mutation=Mutation.from_dict(d["mutation"]),
            experiment_evidence=evidence,
        )


# ---------------------------------------------------------------------------
# Gate Result
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    gate_name: str
    passed: bool
    reason: str

    def to_dict(self) -> dict:
        return {"gate_name": self.gate_name, "passed": self.passed, "reason": self.reason}


# ---------------------------------------------------------------------------
# Lane State (DynamoDB record)
# ---------------------------------------------------------------------------

@dataclass
class LaneState:
    lane_id: str
    phi_score: float
    terminal_status: str      # ACTIVE | TERMINAL_SUCCESS
    discard_count: int
    last_run_id: str
    last_updated: str         # ISO8601
    last_gate_failure: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "lane_id": self.lane_id,
            "phi_score": str(self.phi_score),   # DynamoDB Decimal-safe
            "terminal_status": self.terminal_status,
            "discard_count": self.discard_count,
            "last_run_id": self.last_run_id,
            "last_updated": self.last_updated,
            "last_gate_failure": self.last_gate_failure,
        }


@dataclass
class LaneStateUpdate:
    phi_score: Optional[float] = None
    terminal_status: Optional[str] = None
    last_run_id: Optional[str] = None
    last_gate_failure: Optional[str] = None


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

@dataclass
class TerminalConditionConfig:
    lane_type: str            # WEB_BYPASS | IDENTITY_ESCALATION | WAF_BYPASS
    success_indicator: Optional[str] = None
    privilege_string: Optional[str] = None
    waf_block_indicator: Optional[str] = None
    interpretation_markers: list[str] = field(default_factory=list)
    admin_session_marker: Optional[str] = None


@dataclass
class GateThresholds:
    reproducibility_min_fraction: float
    reproducibility_reruns: int
    evidence_markers: list[str]
    cost_max_tokens: int
    cost_max_duration_ms: int
    noise_patterns: list[str]


@dataclass
class LaneConfig:
    lane_id: str
    target_url: str
    dvwa_security_level: str
    terminal_condition: TerminalConditionConfig
    phi_weights: PhiWeights
    gate_thresholds: GateThresholds
    bedrock_max_retries: int
    http_timeout_ms: int


@dataclass
class GlobalConfig:
    schedule_expression: str
    active_lanes: list[str]
    bedrock_model_id: str
    map_max_concurrency: int
    dvwa_admin_username: str
    dvwa_admin_password: str


# ---------------------------------------------------------------------------
# Terminal Result
# ---------------------------------------------------------------------------

@dataclass
class TerminalResult:
    passed: bool
    matched_indicator: Optional[str] = None
    reason: str = ""
