"""
BedrockClient — wraps Amazon Bedrock Converse API for mutation planning and
Phi scoring in the AutoRedTeam Lambda Harness.

Property coverage:
  - Property 7:  Mutation planning prompt completeness — the prompt sent to
    Bedrock contains the lane_def, strategy, and last_result verbatim so the
    model has full context for proposing the next mutation.
  - Property 8:  Mutation object structural completeness — every Mutation
    returned by propose_mutation has all five required fields populated:
    attack_payload, target_endpoint, http_method, headers, rationale.
  - Property 9:  Bedrock retry count enforcement — on persistent parse failures
    propose_mutation / score_experiment make exactly max_retries + 1 total
    Bedrock API calls before raising BedrockParseError.
  - Property 10: Bedrock audit log completeness — the S3 artifact written after
    each Bedrock call contains both the full prompt text and the raw response
    text, enabling offline replay and audit.
  - Property 18: Scoring call conditionality — documented in lane_worker; this
    module always scores when called and does not gate on preconditions.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from src.lib.models import ExperimentResult, Mutation, PhiScores, Strategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class BedrockParseError(Exception):
    """Raised when the Bedrock response cannot be parsed into the expected model."""


class BedrockAPIError(Exception):
    """Raised when the Bedrock API returns an unrecoverable error after retries."""


# ---------------------------------------------------------------------------
# BedrockClient
# ---------------------------------------------------------------------------


class BedrockClient:
    """Wraps the Amazon Bedrock Converse API for mutation planning and scoring.

    Args:
        model_id:        Bedrock model identifier, e.g.
                         ``"amazon.nova-pro-v1:0"``.
        max_retries:     Maximum number of parse-level retries before raising
                         BedrockParseError (Property 9).
        s3_bucket:       S3 bucket name for audit log storage (Property 10).
        s3_client:       Optional pre-built boto3 S3 client (for testing).
        bedrock_client:  Optional pre-built boto3 bedrock-runtime client (for
                         testing / dependency injection).
    """

    _BACKOFF_BASE_S: float = 1.0
    _BACKOFF_MAX_S: float = 30.0
    _RETRYABLE_ERROR_CODES = {
        "ThrottlingException",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelTimeoutException",
    }

    def __init__(
        self,
        model_id: str,
        max_retries: int,
        s3_bucket: str,
        s3_client: Optional[Any] = None,
        bedrock_client: Optional[Any] = None,
    ) -> None:
        self._model_id = model_id
        self._max_retries = max_retries
        self._s3_bucket = s3_bucket
        self._s3 = s3_client or boto3.client("s3")
        self._bedrock = bedrock_client or boto3.client("bedrock-runtime")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose_mutation(
        self,
        lane_def: Any,
        strategy: Optional[Strategy],
        last_result: Optional[ExperimentResult],
        run_id: str,
        lane_id: str,
    ) -> Mutation:
        """Ask Bedrock to propose the next attack mutation for a lane.

        Property 7 (Mutation planning prompt completeness): The prompt
        includes the full lane_def, the current strategy, and the last
        experiment result so the model has complete context.

        Property 8 (Mutation object structural completeness): The returned
        Mutation always has all five fields populated — attack_payload,
        target_endpoint, http_method, headers, and rationale.

        Property 9 (Bedrock retry count enforcement): On repeated parse
        failures this method makes exactly max_retries + 1 total API calls
        before raising BedrockParseError.

        Property 10 (Bedrock audit log completeness): Each call is logged to
        S3 at ``logs/{run_id}/{lane_id}/bedrock_mutation_{timestamp}.json``
        with the full prompt and raw response.

        Args:
            lane_def:    Lane configuration / definition object (serialisable).
            strategy:    Current best strategy for this lane, or None.
            last_result: Most recent ExperimentResult, or None.
            run_id:      Harness run identifier.
            lane_id:     Lane identifier.

        Returns:
            A fully populated Mutation object.

        Raises:
            BedrockParseError: After exhausting max_retries parse attempts.
            BedrockAPIError:   After exhausting API-level retries.
        """
        # Property 7: embed all three context objects in the prompt
        prompt = self._build_mutation_prompt(lane_def, strategy, last_result)

        last_parse_error: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):  # Property 9: N+1 calls
            raw_response, token_usage = self._call_bedrock_with_backoff(
                prompt, context="mutation"
            )

            # Property 10: write audit log before attempting parse
            self._write_s3_log(
                run_id=run_id,
                lane_id=lane_id,
                log_type="bedrock_mutation",
                prompt=prompt,
                raw_response=raw_response,
                token_usage=token_usage,
                attempt=attempt,
            )

            try:
                mutation = self._parse_mutation(raw_response)
                return mutation  # Property 8: validated inside _parse_mutation
            except BedrockParseError as exc:
                last_parse_error = exc
                logger.warning(
                    "Mutation parse failed (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )

        raise BedrockParseError(
            f"Failed to parse mutation after {self._max_retries + 1} attempts. "
            f"Last error: {last_parse_error}"
        )

    def score_experiment(
        self,
        experiment_result: ExperimentResult,
        lane_rubric: Any,
        strategy: Optional[Strategy],
        run_id: str,
        lane_id: str,
    ) -> PhiScores:
        """Ask Bedrock to score an experiment result against the lane rubric.

        Property 9 (Bedrock retry count enforcement): Same retry semantics as
        propose_mutation — exactly max_retries + 1 total API calls on failure.

        Property 10 (Bedrock audit log completeness): Each call is logged to
        S3 at ``logs/{run_id}/{lane_id}/bedrock_scoring_{timestamp}.json``
        with the full prompt and raw response.

        Args:
            experiment_result: The ExperimentResult to score.
            lane_rubric:       Scoring rubric / criteria for this lane.
            strategy:          Current best strategy (for context), or None.
            run_id:            Harness run identifier.
            lane_id:           Lane identifier.

        Returns:
            PhiScores with p_goal, c_pre, d_depth all in [0.0, 1.0].

        Raises:
            BedrockParseError: After exhausting max_retries parse attempts.
            BedrockAPIError:   After exhausting API-level retries.
        """
        prompt = self._build_scoring_prompt(experiment_result, lane_rubric, strategy)

        last_parse_error: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):  # Property 9: N+1 calls
            raw_response, token_usage = self._call_bedrock_with_backoff(
                prompt, context="scoring"
            )

            # Property 10: write audit log before attempting parse
            self._write_s3_log(
                run_id=run_id,
                lane_id=lane_id,
                log_type="bedrock_scoring",
                prompt=prompt,
                raw_response=raw_response,
                token_usage=token_usage,
                attempt=attempt,
            )

            try:
                scores = self._parse_phi_scores(raw_response)
                return scores
            except BedrockParseError as exc:
                last_parse_error = exc
                logger.warning(
                    "Scoring parse failed (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )

        raise BedrockParseError(
            f"Failed to parse PhiScores after {self._max_retries + 1} attempts. "
            f"Last error: {last_parse_error}"
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_mutation_prompt(
        self,
        lane_def: Any,
        strategy: Optional[Strategy],
        last_result: Optional[ExperimentResult],
    ) -> str:
        """Build the mutation planning prompt.

        Property 7: All three context objects are serialised and embedded so
        the model receives complete information.
        """
        lane_def_json = (
            json.dumps(lane_def, default=str, indent=2)
            if not isinstance(lane_def, str)
            else lane_def
        )
        strategy_json = (
            json.dumps(strategy.to_dict(), indent=2)
            if strategy is not None
            else "null"
        )
        last_result_json = (
            json.dumps(last_result.to_dict(), indent=2)
            if last_result is not None
            else "null"
        )

        return f"""You are an expert red-team security researcher.

## Lane Definition
{lane_def_json}

## Current Best Strategy
{strategy_json}

## Last Experiment Result
{last_result_json}

## Task
Based on the lane definition, the current strategy, and the last experiment
result, propose the single most promising next HTTP attack mutation to advance
toward the lane's goal.

Respond with ONLY a JSON object — no markdown fences, no explanation — in
exactly this format:
{{
  "attack_payload": "<payload string or POST body>",
  "target_endpoint": "<relative URL path, e.g. /vulnerabilities/sqli/>",
  "http_method": "<GET|POST|PUT|DELETE>",
  "headers": {{"<header-name>": "<header-value>"}},
  "rationale": "<one sentence explaining why this mutation is promising>"
}}"""

    def _build_scoring_prompt(
        self,
        experiment_result: ExperimentResult,
        lane_rubric: Any,
        strategy: Optional[Strategy],
    ) -> str:
        """Build the Phi scoring prompt."""
        result_json = json.dumps(experiment_result.to_dict(), indent=2)
        rubric_json = (
            json.dumps(lane_rubric, default=str, indent=2)
            if not isinstance(lane_rubric, str)
            else lane_rubric
        )
        strategy_json = (
            json.dumps(strategy.to_dict(), indent=2)
            if strategy is not None
            else "null"
        )

        return f"""You are an expert red-team security evaluator.

## Lane Scoring Rubric
{rubric_json}

## Current Best Strategy
{strategy_json}

## Experiment Result to Score
{result_json}

## Task
Score the experiment result against the rubric using three sub-scores, each
a float in [0.0, 1.0]:

- p_goal:  Probability that the attack achieved the lane's primary goal.
- c_pre:   Degree to which preconditions for a full exploit were satisfied.
- d_depth: Depth of the exploit chain demonstrated (0 = no progress, 1 = full).

Respond with ONLY a JSON object — no markdown fences, no explanation — in
exactly this format:
{{
  "p_goal": <float 0.0-1.0>,
  "c_pre": <float 0.0-1.0>,
  "d_depth": <float 0.0-1.0>
}}"""

    # ------------------------------------------------------------------
    # Bedrock API call with exponential backoff
    # ------------------------------------------------------------------

    def _call_bedrock_with_backoff(
        self, prompt: str, context: str = ""
    ) -> tuple[str, int]:
        """Call the Bedrock Converse API with exponential backoff on API errors.

        Property 9: API-level retries (throttling / 5xx) use exponential
        backoff with base 1 s and cap 30 s.  Parse-level retries are handled
        by the callers.

        Args:
            prompt:  The user prompt text.
            context: Label for log messages (e.g. "mutation" or "scoring").

        Returns:
            Tuple of (raw_response_text, total_token_count).

        Raises:
            BedrockAPIError: After exhausting API retries.
        """
        api_retries = self._max_retries
        delay = self._BACKOFF_BASE_S

        for api_attempt in range(api_retries + 1):
            try:
                response = self._bedrock.converse(
                    modelId=self._model_id,
                    messages=[
                        {"role": "user", "content": [{"text": prompt}]}
                    ],
                    inferenceConfig={"maxTokens": 4096, "temperature": 0.7},
                )
                content = response["output"]["message"]["content"][0]["text"]
                token_usage = (
                    response["usage"]["inputTokens"]
                    + response["usage"]["outputTokens"]
                )
                return content, token_usage

            except ClientError as exc:
                error_code = exc.response["Error"]["Code"]
                if error_code in self._RETRYABLE_ERROR_CODES and api_attempt < api_retries:
                    sleep_s = min(delay, self._BACKOFF_MAX_S)
                    logger.warning(
                        "Bedrock %s API error '%s' (attempt %d/%d), "
                        "retrying in %.1f s",
                        context,
                        error_code,
                        api_attempt + 1,
                        api_retries + 1,
                        sleep_s,
                    )
                    time.sleep(sleep_s)
                    delay = min(delay * 2, self._BACKOFF_MAX_S)
                else:
                    raise BedrockAPIError(
                        f"Bedrock {context} API error after "
                        f"{api_attempt + 1} attempt(s): {exc}"
                    ) from exc

        # Should not be reached, but satisfies type checker
        raise BedrockAPIError(
            f"Bedrock {context} API exhausted all retries."
        )

    # ------------------------------------------------------------------
    # Response parsers
    # ------------------------------------------------------------------

    def _parse_mutation(self, raw: str) -> Mutation:
        """Parse a raw Bedrock response into a Mutation.

        Property 8 (Mutation object structural completeness): Validates that
        all five required fields are present and non-empty before constructing
        the Mutation.

        Raises:
            BedrockParseError: If the JSON is malformed or any field is missing.
        """
        data = self._extract_json(raw)

        required = {"attack_payload", "target_endpoint", "http_method", "headers", "rationale"}
        missing = required - data.keys()
        if missing:
            raise BedrockParseError(
                f"Mutation JSON missing required fields: {sorted(missing)}"
            )

        # Property 8: validate each field is non-None
        for field in required - {"headers"}:
            if not data[field]:
                raise BedrockParseError(
                    f"Mutation field '{field}' is empty or null."
                )

        if not isinstance(data["headers"], dict):
            raise BedrockParseError(
                "Mutation field 'headers' must be a JSON object."
            )

        return Mutation(
            attack_payload=str(data["attack_payload"]),
            target_endpoint=str(data["target_endpoint"]),
            http_method=str(data["http_method"]).upper(),
            headers={str(k): str(v) for k, v in data["headers"].items()},
            rationale=str(data["rationale"]),
        )

    def _parse_phi_scores(self, raw: str) -> PhiScores:
        """Parse a raw Bedrock response into PhiScores.

        Raises:
            BedrockParseError: If the JSON is malformed, fields are missing,
                               or any score is outside [0.0, 1.0].
        """
        data = self._extract_json(raw)

        required = {"p_goal", "c_pre", "d_depth"}
        missing = required - data.keys()
        if missing:
            raise BedrockParseError(
                f"PhiScores JSON missing required fields: {sorted(missing)}"
            )

        scores: dict[str, float] = {}
        for key in required:
            try:
                val = float(data[key])
            except (TypeError, ValueError) as exc:
                raise BedrockParseError(
                    f"PhiScores field '{key}' is not a valid float: {data[key]!r}"
                ) from exc
            if not (0.0 <= val <= 1.0):
                raise BedrockParseError(
                    f"PhiScores field '{key}' = {val} is outside [0.0, 1.0]."
                )
            scores[key] = val

        return PhiScores(
            p_goal=scores["p_goal"],
            c_pre=scores["c_pre"],
            d_depth=scores["d_depth"],
        )

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """Extract and parse the first JSON object from a raw string.

        Strips markdown code fences if present before parsing.

        Raises:
            BedrockParseError: If no valid JSON object is found.
        """
        import re

        text = raw.strip()

        # Strip ```json ... ``` or ``` ... ``` fences
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        # Find the first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise BedrockParseError(
                f"No JSON object found in Bedrock response: {text[:200]!r}"
            )

        json_str = text[start : end + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise BedrockParseError(
                f"JSON decode error in Bedrock response: {exc}. "
                f"Raw snippet: {json_str[:200]!r}"
            ) from exc

    # ------------------------------------------------------------------
    # S3 audit logging
    # ------------------------------------------------------------------

    def _write_s3_log(
        self,
        run_id: str,
        lane_id: str,
        log_type: str,
        prompt: str,
        raw_response: str,
        token_usage: int,
        attempt: int,
    ) -> None:
        """Write a Bedrock audit log entry to S3.

        Property 10 (Bedrock audit log completeness): The artifact contains
        both the full prompt and the raw response, plus metadata.

        The S3 key format is:
            ``logs/{run_id}/{lane_id}/{log_type}_{timestamp}.json``

        Args:
            run_id:       Harness run identifier.
            lane_id:      Lane identifier.
            log_type:     ``"bedrock_mutation"`` or ``"bedrock_scoring"``.
            prompt:       The full prompt text sent to Bedrock.
            raw_response: The raw text returned by Bedrock.
            token_usage:  Total tokens consumed (input + output).
            attempt:      Zero-based attempt index.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        key = f"logs/{run_id}/{lane_id}/{log_type}_{timestamp}.json"

        # Property 10: artifact must contain both prompt and response
        artifact = {
            "run_id": run_id,
            "lane_id": lane_id,
            "log_type": log_type,
            "model_id": self._model_id,
            "timestamp": timestamp,
            "attempt": attempt,
            "token_usage": token_usage,
            "prompt": prompt,          # full prompt — Property 10
            "raw_response": raw_response,  # full response — Property 10
        }

        try:
            self._s3.put_object(
                Bucket=self._s3_bucket,
                Key=key,
                Body=json.dumps(artifact, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
            )
            logger.debug("Bedrock audit log written to s3://%s/%s", self._s3_bucket, key)
        except Exception as exc:  # noqa: BLE001
            # Logging failure must not abort the main workflow
            logger.error(
                "Failed to write Bedrock audit log to s3://%s/%s: %s",
                self._s3_bucket,
                key,
                exc,
            )
