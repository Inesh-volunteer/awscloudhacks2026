"""
Unit and property-based tests for status_lambda.py
Feature: redteam-ui-dashboard
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure src/dashboard is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "dashboard"))

import status_lambda  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(method="GET", execution_arn=None):
    params = {"execution_arn": execution_arn} if execution_arn else None
    return {
        "httpMethod": method,
        "requestContext": {"http": {"method": method}},
        "queryStringParameters": params,
    }


def _make_sfn_response(status="RUNNING", run_id="run-20240115-a3f9c2"):
    """Build a minimal sfn.describe_execution response."""
    from datetime import datetime, timezone
    start = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    stop = datetime(2024, 1, 15, 10, 35, 0, tzinfo=timezone.utc) if status != "RUNNING" else None
    resp = {
        "executionArn": "arn:aws:states:us-east-1:123456789012:execution:MyMachine:abc",
        "stateMachineArn": "arn:aws:states:us-east-1:123456789012:stateMachine:MyMachine",
        "name": "abc",
        "status": status,
        "startDate": start,
        "input": json.dumps({"run_id": run_id, "timestamp": "2024-01-15T10:30:00Z"}),
    }
    if stop:
        resp["stopDate"] = stop
    return resp


def _make_client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "GetObject")


# ---------------------------------------------------------------------------
# Property 5: response always contains status, start_date, stop_date,
#             execution_arn for any valid arn
# Feature: redteam-ui-dashboard, Property 5: Status Lambda response completeness
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(arn=st.text(min_size=1, max_size=200, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=":/-_.")))
def test_property5_response_completeness(arn):
    # Feature: redteam-ui-dashboard, Property 5: Status Lambda response completeness
    with patch.dict(os.environ, {"ARTIFACT_BUCKET": "test-bucket"}):
        with patch("status_lambda.boto3") as mock_boto3:
            mock_sfn = MagicMock()
            mock_boto3.client.return_value = mock_sfn
            mock_sfn.describe_execution.return_value = _make_sfn_response(status="RUNNING")

            event = make_event("GET", execution_arn=arn)
            response = status_lambda.lambda_handler(event, None)

            body = json.loads(response["body"])
            assert "status" in body, "response body must contain 'status'"
            assert "start_date" in body, "response body must contain 'start_date'"
            assert "stop_date" in body, "response body must contain 'stop_date'"
            assert "execution_arn" in body, "response body must contain 'execution_arn'"


# ---------------------------------------------------------------------------
# Property 6: CORS header present on all response paths
# Feature: redteam-ui-dashboard, Property 6: Status Lambda CORS headers on all responses
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(path=st.sampled_from(["options", "success", "missing_arn", "missing_bucket"]))
def test_property6_cors_header_all_paths(path):
    # Feature: redteam-ui-dashboard, Property 6: Status Lambda CORS headers on all responses
    import status_lambda

    if path == "options":
        event = make_event("OPTIONS")
        env = {"ARTIFACT_BUCKET": "test-bucket"}
        with patch.dict(os.environ, env):
            with patch("status_lambda.boto3"):
                response = status_lambda.lambda_handler(event, None)

    elif path == "success":
        event = make_event("GET", execution_arn="arn:aws:states:us-east-1:123:execution:M:x")
        env = {"ARTIFACT_BUCKET": "test-bucket"}
        with patch.dict(os.environ, env):
            with patch("status_lambda.boto3") as mock_boto3:
                mock_sfn = MagicMock()
                mock_boto3.client.return_value = mock_sfn
                mock_sfn.describe_execution.return_value = _make_sfn_response(status="RUNNING")
                response = status_lambda.lambda_handler(event, None)

    elif path == "missing_arn":
        event = make_event("GET")  # no execution_arn
        env = {"ARTIFACT_BUCKET": "test-bucket"}
        with patch.dict(os.environ, env):
            with patch("status_lambda.boto3"):
                response = status_lambda.lambda_handler(event, None)

    else:  # missing_bucket
        event = make_event("GET", execution_arn="arn:aws:states:us-east-1:123:execution:M:x")
        # Remove ARTIFACT_BUCKET if present
        clean_env = {k: v for k, v in os.environ.items() if k != "ARTIFACT_BUCKET"}
        with patch.dict(os.environ, clean_env, clear=True):
            with patch("status_lambda.boto3"):
                response = status_lambda.lambda_handler(event, None)

    headers = response.get("headers", {})
    assert "Access-Control-Allow-Origin" in headers, (
        f"CORS header missing on path={path}, response={response}"
    )
    assert headers["Access-Control-Allow-Origin"] == "*", (
        f"CORS header value wrong on path={path}"
    )


# ---------------------------------------------------------------------------
# Property 7: S3 key is always runs/{run_id}/summary.json for any run_id
# Feature: redteam-ui-dashboard, Property 7: S3 key construction from run_id
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(run_id=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_.")))
def test_property7_s3_key_construction(run_id):
    # Feature: redteam-ui-dashboard, Property 7: S3 key construction from run_id
    execution_arn = "arn:aws:states:us-east-1:123456789012:execution:M:x"
    event = make_event("GET", execution_arn=execution_arn)

    with patch.dict(os.environ, {"ARTIFACT_BUCKET": "test-bucket"}):
        with patch("status_lambda.boto3") as mock_boto3:
            mock_sfn = MagicMock()
            mock_s3 = MagicMock()

            def client_factory(service, **kwargs):
                if service == "stepfunctions":
                    return mock_sfn
                return mock_s3

            mock_boto3.client.side_effect = client_factory
            mock_sfn.describe_execution.return_value = _make_sfn_response(
                status="SUCCEEDED", run_id=run_id
            )
            # Return a valid summary body
            mock_s3.get_object.return_value = {
                "Body": MagicMock(read=lambda: b'{"run_id": "x"}')
            }

            status_lambda.lambda_handler(event, None)

            # Verify the S3 key used
            mock_s3.get_object.assert_called_once()
            call_kwargs = mock_s3.get_object.call_args
            key_used = call_kwargs.kwargs.get("Key") or call_kwargs[1].get("Key")
            assert key_used == f"runs/{run_id}/summary.json", (
                f"Expected key 'runs/{run_id}/summary.json', got '{key_used}'"
            )


# ---------------------------------------------------------------------------
# Example test 5.4: missing execution_arn param returns 400 with correct message
# ---------------------------------------------------------------------------

def test_missing_execution_arn_returns_400():
    event = make_event("GET")  # no execution_arn
    with patch.dict(os.environ, {"ARTIFACT_BUCKET": "test-bucket"}):
        with patch("status_lambda.boto3"):
            response = status_lambda.lambda_handler(event, None)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body.get("error") == "execution_arn parameter required"


# ---------------------------------------------------------------------------
# Example test 5.5: S3 NoSuchKey returns summary: null (not an error response)
# ---------------------------------------------------------------------------

def test_s3_no_such_key_returns_summary_null():
    execution_arn = "arn:aws:states:us-east-1:123456789012:execution:M:x"
    event = make_event("GET", execution_arn=execution_arn)

    with patch.dict(os.environ, {"ARTIFACT_BUCKET": "test-bucket"}):
        with patch("status_lambda.boto3") as mock_boto3:
            mock_sfn = MagicMock()
            mock_s3 = MagicMock()

            def client_factory(service, **kwargs):
                if service == "stepfunctions":
                    return mock_sfn
                return mock_s3

            mock_boto3.client.side_effect = client_factory
            mock_sfn.describe_execution.return_value = _make_sfn_response(
                status="SUCCEEDED", run_id="run-20240115-abc123"
            )
            mock_s3.get_object.side_effect = _make_client_error("NoSuchKey")

            response = status_lambda.lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body.get("summary") is None, "summary should be null when S3 key not found"
    assert "error" not in body, "response should not contain 'error' key for NoSuchKey"


# ---------------------------------------------------------------------------
# Example test 5.6: RUNNING status does not trigger S3 read
# ---------------------------------------------------------------------------

def test_running_status_does_not_read_s3():
    execution_arn = "arn:aws:states:us-east-1:123456789012:execution:M:x"
    event = make_event("GET", execution_arn=execution_arn)

    with patch.dict(os.environ, {"ARTIFACT_BUCKET": "test-bucket"}):
        with patch("status_lambda.boto3") as mock_boto3:
            mock_sfn = MagicMock()
            mock_s3 = MagicMock()

            def client_factory(service, **kwargs):
                if service == "stepfunctions":
                    return mock_sfn
                return mock_s3

            mock_boto3.client.side_effect = client_factory
            mock_sfn.describe_execution.return_value = _make_sfn_response(status="RUNNING")

            response = status_lambda.lambda_handler(event, None)

    assert response["statusCode"] == 200
    mock_s3.get_object.assert_not_called()
