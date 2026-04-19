"""
Unit and property-based tests for trigger_lambda.py

Feature: redteam-ui-dashboard
Tests cover Properties 2, 3, and 4 from the design document.
"""

import json
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure src/dashboard is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "dashboard"))

import trigger_lambda  # noqa: E402


RUN_ID_PATTERN = re.compile(r"^run-\d{8}-[0-9a-f]{6}$")
CORS_ORIGIN_HEADER = "Access-Control-Allow-Origin"


def make_event(method="POST"):
    return {"httpMethod": method, "requestContext": {"http": {"method": method}}}


# ---------------------------------------------------------------------------
# Property 2: run_id format correctness
# ---------------------------------------------------------------------------

# Feature: redteam-ui-dashboard, Property 2: run_id format matches ^run-\d{8}-[0-9a-f]{6}$
@settings(max_examples=100)
@given(st.none())  # no meaningful input variation needed; handler generates run_id internally
def test_property2_run_id_format(_):
    """For any invocation, the generated run_id must match ^run-\\d{8}-[0-9a-f]{6}$."""
    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123456789012:execution:MyMachine:abc"
    }
    with patch("trigger_lambda.boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_sfn
        with patch.dict(os.environ, {"STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:X"}):
            response = trigger_lambda.lambda_handler(make_event("POST"), {})

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    run_id = body["run_id"]
    assert RUN_ID_PATTERN.match(run_id), f"run_id {run_id!r} does not match expected pattern"


# ---------------------------------------------------------------------------
# Property 3: any exception from StartExecution yields HTTP 500 + non-empty error
# ---------------------------------------------------------------------------

# Feature: redteam-ui-dashboard, Property 3: any exception from StartExecution yields HTTP 500 with non-empty error
@settings(max_examples=100)
@given(st.text(min_size=0, max_size=500))
def test_property3_exception_yields_500(exc_message):
    """For any exception raised by start_execution, response must be 500 with non-empty error."""
    mock_sfn = MagicMock()
    mock_sfn.start_execution.side_effect = Exception(exc_message)
    with patch("trigger_lambda.boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_sfn
        with patch.dict(os.environ, {"STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:X"}):
            response = trigger_lambda.lambda_handler(make_event("POST"), {})

    assert response["statusCode"] == 500
    body = json.loads(response["body"])
    assert "error" in body
    assert isinstance(body["error"], str)
    assert len(body["error"]) > 0, "error field must be a non-empty string"


# ---------------------------------------------------------------------------
# Property 4: CORS header present on all response paths
# ---------------------------------------------------------------------------

# Feature: redteam-ui-dashboard, Property 4: CORS header present on all response paths
@settings(max_examples=100)
@given(st.sampled_from(["success", "error", "options"]))
def test_property4_cors_header_all_paths(path):
    """Access-Control-Allow-Origin: * must be present on success, error, and OPTIONS responses."""
    if path == "options":
        response = trigger_lambda.lambda_handler(make_event("OPTIONS"), {})
    elif path == "success":
        mock_sfn = MagicMock()
        mock_sfn.start_execution.return_value = {
            "executionArn": "arn:aws:states:us-east-1:123456789012:execution:MyMachine:abc"
        }
        with patch("trigger_lambda.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_sfn
            with patch.dict(os.environ, {"STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:X"}):
                response = trigger_lambda.lambda_handler(make_event("POST"), {})
    else:  # error path — missing ARN
        with patch.dict(os.environ, {}, clear=True):
            # Remove STATE_MACHINE_ARN if present
            env = {k: v for k, v in os.environ.items() if k != "STATE_MACHINE_ARN"}
            with patch.dict(os.environ, env, clear=True):
                response = trigger_lambda.lambda_handler(make_event("POST"), {})

    headers = response.get("headers", {})
    assert CORS_ORIGIN_HEADER in headers, f"Missing {CORS_ORIGIN_HEADER} header on {path} path"
    assert headers[CORS_ORIGIN_HEADER] == "*", (
        f"Expected Access-Control-Allow-Origin: * but got {headers[CORS_ORIGIN_HEADER]!r}"
    )


# ---------------------------------------------------------------------------
# Example tests
# ---------------------------------------------------------------------------

class TestTriggerLambdaExamples(unittest.TestCase):

    def test_options_returns_200_with_cors(self):
        """4.4: OPTIONS preflight returns 200 with CORS headers."""
        response = trigger_lambda.lambda_handler(make_event("OPTIONS"), {})
        self.assertEqual(response["statusCode"], 200)
        self.assertIn(CORS_ORIGIN_HEADER, response["headers"])
        self.assertEqual(response["headers"][CORS_ORIGIN_HEADER], "*")

    def test_missing_state_machine_arn_returns_500(self):
        """4.5: Missing STATE_MACHINE_ARN env var returns 500 with correct message."""
        env = {k: v for k, v in os.environ.items() if k != "STATE_MACHINE_ARN"}
        with patch.dict(os.environ, env, clear=True):
            response = trigger_lambda.lambda_handler(make_event("POST"), {})
        self.assertEqual(response["statusCode"], 500)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "STATE_MACHINE_ARN not configured")

    def test_successful_execution_returns_200_with_arn_and_run_id(self):
        """4.6: Successful StartExecution returns 200 with execution_arn and run_id."""
        fake_arn = "arn:aws:states:us-east-1:123456789012:execution:MyMachine:test-exec"
        mock_sfn = MagicMock()
        mock_sfn.start_execution.return_value = {"executionArn": fake_arn}
        with patch("trigger_lambda.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_sfn
            with patch.dict(os.environ, {"STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:X"}):
                response = trigger_lambda.lambda_handler(make_event("POST"), {})

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["execution_arn"], fake_arn)
        self.assertIn("run_id", body)
        self.assertRegex(body["run_id"], RUN_ID_PATTERN)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
