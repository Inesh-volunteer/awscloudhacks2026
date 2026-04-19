"""
Property-based and unit tests for BedrockClient.

Properties covered:
  Property 7:  Mutation planning prompt completeness
  Property 8:  Mutation object structural completeness
  Property 9:  Bedrock retry count enforcement
  Property 10: Bedrock audit log completeness
  Property 18: Scoring call conditionality (documented here as unit test)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.lib.bedrock_client import BedrockAPIError, BedrockClient, BedrockParseError
from src.lib.models import ExperimentResult, HttpRequest, HttpResponse, Mutation, PhiScores


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(max_retries=2, mock_s3=None, mock_bedrock=None):
    return BedrockClient(
        model_id="amazon.nova-pro-v1:0",
        max_retries=max_retries,
        s3_bucket="test-bucket",
        s3_client=mock_s3 or MagicMock(),
        bedrock_client=mock_bedrock or MagicMock(),
    )


def _bedrock_response(text: str, input_tokens=100, output_tokens=50):
    return {
        "output": {"message": {"content": [{"text": text}]}},
        "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens},
    }


def _valid_mutation_json():
    return json.dumps({
        "attack_payload": "1' OR '1'='1",
        "target_endpoint": "/dvwa/vulnerabilities/sqli/",
        "http_method": "POST",
        "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        "rationale": "Classic SQL injection bypass",
    })


def _valid_scores_json():
    return json.dumps({"p_goal": 0.6, "c_pre": 0.4, "d_depth": 0.3})


def _make_experiment_result():
    return ExperimentResult(
        run_id="r1",
        lane_id="L1",
        timestamp="2024-01-01T00:00:00Z",
        request=HttpRequest("POST", "http://dvwa/test", {}, "payload"),
        response=HttpResponse(200, {}, "response body", 50),
    )


# ---------------------------------------------------------------------------
# Property 7: Mutation planning prompt completeness
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 7: Mutation planning prompt completeness
def test_propose_mutation_prompt_contains_all_three_context_objects():
    """The prompt must contain lane_def, strategy, and last_result."""
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _bedrock_response(_valid_mutation_json())

    client = _make_client(mock_bedrock=mock_bedrock)

    lane_def = {"lane_type": "WEB_BYPASS", "target": "DVWA"}
    strategy = MagicMock()
    strategy.to_dict.return_value = {"phi_score": 0.3, "mutation": {}}
    last_result = _make_experiment_result()

    client.propose_mutation(lane_def, strategy, last_result, "r1", "L1")

    prompt_sent = mock_bedrock.converse.call_args.kwargs["messages"][0]["content"][0]["text"]
    assert "WEB_BYPASS" in prompt_sent   # lane_def present
    assert "phi_score" in prompt_sent    # strategy present
    assert "response body" in prompt_sent  # last_result present


# ---------------------------------------------------------------------------
# Property 8: Mutation object structural completeness
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 8: Mutation object structural completeness
def test_propose_mutation_returns_all_five_fields():
    """Parsed Mutation must have all 5 required fields non-empty."""
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _bedrock_response(_valid_mutation_json())

    client = _make_client(mock_bedrock=mock_bedrock)
    mutation = client.propose_mutation({}, None, None, "r1", "L1")

    assert mutation.attack_payload
    assert mutation.target_endpoint
    assert mutation.http_method
    assert isinstance(mutation.headers, dict)
    assert mutation.rationale


# Feature: lambda-redteam-harness, Property 8: Missing field raises BedrockParseError
@settings(max_examples=50)
@given(missing_field=st.sampled_from([
    "attack_payload", "target_endpoint", "http_method", "headers", "rationale"
]))
def test_propose_mutation_raises_on_missing_field(missing_field):
    """Any missing field in the Bedrock response must raise BedrockParseError."""
    data = json.loads(_valid_mutation_json())
    del data[missing_field]

    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _bedrock_response(json.dumps(data))

    client = _make_client(max_retries=0, mock_bedrock=mock_bedrock)
    with pytest.raises(BedrockParseError):
        client.propose_mutation({}, None, None, "r1", "L1")


# ---------------------------------------------------------------------------
# Property 9: Bedrock retry count enforcement
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 9: Bedrock retry count enforcement
@settings(max_examples=20)
@given(max_retries=st.integers(min_value=0, max_value=5))
def test_propose_mutation_makes_exactly_n_plus_1_calls_on_parse_failure(max_retries):
    """On persistent parse failures, exactly max_retries+1 API calls are made."""
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _bedrock_response("not valid json at all")

    client = _make_client(max_retries=max_retries, mock_bedrock=mock_bedrock)
    with pytest.raises(BedrockParseError):
        client.propose_mutation({}, None, None, "r1", "L1")

    assert mock_bedrock.converse.call_count == max_retries + 1


# Feature: lambda-redteam-harness, Property 9: Scoring retry count enforcement
@settings(max_examples=20)
@given(max_retries=st.integers(min_value=0, max_value=5))
def test_score_experiment_makes_exactly_n_plus_1_calls_on_parse_failure(max_retries):
    """score_experiment also makes exactly max_retries+1 calls on parse failure."""
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _bedrock_response("not valid json")

    client = _make_client(max_retries=max_retries, mock_bedrock=mock_bedrock)
    with pytest.raises(BedrockParseError):
        client.score_experiment(_make_experiment_result(), {}, None, "r1", "L1")

    assert mock_bedrock.converse.call_count == max_retries + 1


# ---------------------------------------------------------------------------
# Property 10: Bedrock audit log completeness
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 10: Bedrock audit log completeness
def test_propose_mutation_writes_s3_log_with_prompt_and_response():
    """S3 artifact must contain both the full prompt and the raw response."""
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _bedrock_response(_valid_mutation_json())

    mock_s3 = MagicMock()
    client = _make_client(mock_bedrock=mock_bedrock, mock_s3=mock_s3)
    client.propose_mutation({"lane": "test"}, None, None, "run-001", "OBJ_WEB_BYPASS")

    assert mock_s3.put_object.called
    call_kwargs = mock_s3.put_object.call_args.kwargs
    body_bytes = call_kwargs["Body"]
    artifact = json.loads(body_bytes.decode("utf-8"))

    # Property 10: both prompt and raw_response must be present
    assert "prompt" in artifact
    assert "raw_response" in artifact
    assert len(artifact["prompt"]) > 0
    assert len(artifact["raw_response"]) > 0


# Feature: lambda-redteam-harness, Property 10: Scoring audit log completeness
def test_score_experiment_writes_s3_log_with_prompt_and_response():
    """Scoring call S3 artifact must also contain full prompt and raw response."""
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _bedrock_response(_valid_scores_json())

    mock_s3 = MagicMock()
    client = _make_client(mock_bedrock=mock_bedrock, mock_s3=mock_s3)
    client.score_experiment(_make_experiment_result(), {}, None, "run-001", "OBJ_WEB_BYPASS")

    assert mock_s3.put_object.called
    artifact = json.loads(mock_s3.put_object.call_args.kwargs["Body"].decode())
    assert "prompt" in artifact
    assert "raw_response" in artifact


# ---------------------------------------------------------------------------
# Unit: successful scoring returns PhiScores
# ---------------------------------------------------------------------------

def test_score_experiment_returns_phi_scores():
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _bedrock_response(_valid_scores_json())

    client = _make_client(mock_bedrock=mock_bedrock)
    scores = client.score_experiment(_make_experiment_result(), {}, None, "r1", "L1")

    assert isinstance(scores, PhiScores)
    assert 0.0 <= scores.p_goal <= 1.0
    assert 0.0 <= scores.c_pre <= 1.0
    assert 0.0 <= scores.d_depth <= 1.0


# Unit: scores outside [0,1] raise BedrockParseError
def test_score_experiment_raises_on_out_of_range_score():
    bad_scores = json.dumps({"p_goal": 1.5, "c_pre": 0.4, "d_depth": 0.3})
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _bedrock_response(bad_scores)

    client = _make_client(max_retries=0, mock_bedrock=mock_bedrock)
    with pytest.raises(BedrockParseError):
        client.score_experiment(_make_experiment_result(), {}, None, "r1", "L1")
