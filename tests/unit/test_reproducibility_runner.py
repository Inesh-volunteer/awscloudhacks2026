"""
Unit tests for reproducibility-runner Lambda handler.

The reproducibility-runner is invoked by the Reproducibility Sub-Machine's Inline Map
and re-runs a single mutation to return pass/fail results.

Key functionality tested:
- Handler input/output structure validation
- Mutation execution against DVWA
- Terminal validation logic
- Phi scoring computation
- Pass/fail determination logic
- Error handling scenarios
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.lib.dvwa_client import DVWATimeoutError, DVWAUnreachableError
from src.lib.models import (
    ExperimentResult,
    HttpRequest,
    HttpResponse,
    LaneConfig,
    Mutation,
    PhiScores,
    PhiWeights,
    TerminalConditionConfig,
    TerminalResult,
)
from src.workers.reproducibility_runner import handler


# ---------------------------------------------------------------------------
# Test Data Factories
# ---------------------------------------------------------------------------

def _make_mutation(
    payload="1' OR '1'='1",
    endpoint="/dvwa/vulnerabilities/sqli/",
    method="POST",
    headers=None,
    rationale="SQL injection test"
):
    """Create a test Mutation object."""
    return Mutation(
        attack_payload=payload,
        target_endpoint=endpoint,
        http_method=method,
        headers=headers or {"Content-Type": "application/x-www-form-urlencoded"},
        rationale=rationale,
    )


def _make_experiment_result(status_code=200, body="Success", error=None):
    """Create a test ExperimentResult object."""
    return ExperimentResult(
        run_id="test-run-123",
        lane_id="OBJ_WEB_BYPASS",
        timestamp="2024-01-01T00:00:00Z",
        request=HttpRequest("POST", "http://dvwa/test", {}, "payload"),
        response=HttpResponse(status_code, {}, body, 100) if error is None else None,
        error=error,
    )


def _make_lane_config():
    """Create a test LaneConfig object."""
    return LaneConfig(
        lane_id="OBJ_WEB_BYPASS",
        target_url="http://10.0.1.50/dvwa",
        dvwa_security_level="low",
        terminal_condition=TerminalConditionConfig(
            lane_type="WEB_BYPASS",
            success_indicator="Welcome to the password protected area",
        ),
        phi_weights=PhiWeights(alpha=0.4, beta=0.35, gamma=0.25),
        gate_thresholds=MagicMock(),  # Not used in reproducibility-runner
        bedrock_max_retries=3,
        http_timeout_ms=10000,
    )


def _make_event(
    run_id="test-run-123",
    lane_id="OBJ_WEB_BYPASS",
    mutation=None,
    rerun_index=0,
    current_phi_score=0.5
):
    """Create a test event payload."""
    if mutation is None:
        mutation = _make_mutation()
    
    return {
        "run_id": run_id,
        "lane_id": lane_id,
        "mutation": mutation.to_dict(),
        "rerun_index": rerun_index,
        "current_phi_score": current_phi_score,
    }


# ---------------------------------------------------------------------------
# Handler Input/Output Structure Tests
# ---------------------------------------------------------------------------

def test_handler_returns_required_fields():
    """Handler must return rerun_index, passed, phi_score, and terminal fields."""
    event = _make_event()
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        # Setup mocks
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = 0.7
        
        result = handler(event, None)
        
        # Verify required fields are present
        assert "rerun_index" in result
        assert "passed" in result
        assert "phi_score" in result
        assert "terminal" in result
        
        # Verify types
        assert isinstance(result["rerun_index"], int)
        assert isinstance(result["passed"], bool)
        assert isinstance(result["phi_score"], (int, float))
        assert isinstance(result["terminal"], bool)


def test_handler_preserves_rerun_index():
    """Handler must return the same rerun_index from the input event."""
    for rerun_index in [0, 1, 5, 10]:
        event = _make_event(rerun_index=rerun_index)
        
        with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
             patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
             patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator:
            
            mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
            mock_config_loader.return_value.load_global_config.return_value = MagicMock(
                dvwa_admin_username="admin",
                dvwa_admin_password="password"
            )
            mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
            mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=True)
            
            result = handler(event, None)
            assert result["rerun_index"] == rerun_index


# ---------------------------------------------------------------------------
# Terminal Success Fast-Path Tests
# ---------------------------------------------------------------------------

def test_terminal_success_returns_immediately():
    """When terminal validator returns True, handler should return immediately without Bedrock scoring."""
    event = _make_event()
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=True)
        
        result = handler(event, None)
        
        # Verify terminal success response
        assert result["passed"] is True
        assert result["phi_score"] == 1.0
        assert result["terminal"] is True
        
        # Verify Bedrock was NOT called
        mock_bedrock_client.assert_not_called()


def test_non_terminal_triggers_phi_scoring():
    """When terminal validator returns False, handler should call Bedrock for Phi scoring."""
    event = _make_event(current_phi_score=0.5)
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = 0.7
        
        result = handler(event, None)
        
        # Verify Bedrock was called
        mock_bedrock_client.return_value.score_experiment.assert_called_once()
        mock_phi_function.return_value.compute.assert_called_once()
        
        # Verify non-terminal response
        assert result["terminal"] is False
        assert result["phi_score"] == 0.7


# ---------------------------------------------------------------------------
# Pass/Fail Logic Tests
# ---------------------------------------------------------------------------

def test_phi_improvement_passes():
    """When new Phi score > current Phi score, passed should be True."""
    event = _make_event(current_phi_score=0.5)
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = 0.7  # > 0.5
        
        result = handler(event, None)
        assert result["passed"] is True


def test_phi_no_improvement_fails():
    """When new Phi score <= current Phi score, passed should be False."""
    event = _make_event(current_phi_score=0.5)
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = 0.3  # < 0.5
        
        result = handler(event, None)
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# DVWA Error Handling Tests
# ---------------------------------------------------------------------------

def test_dvwa_unreachable_error_returns_failure():
    """When DVWA is unreachable, handler should return passed=False."""
    event = _make_event()
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.side_effect = DVWAUnreachableError("Connection failed")
        
        result = handler(event, None)
        
        assert result["passed"] is False
        assert result["phi_score"] == 0.0
        assert result["terminal"] is False


def test_dvwa_timeout_error_returns_failure():
    """When DVWA times out, handler should return passed=False."""
    event = _make_event()
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.side_effect = DVWATimeoutError("Request timed out")
        
        result = handler(event, None)
        
        assert result["passed"] is False
        assert result["phi_score"] == 0.0
        assert result["terminal"] is False


# ---------------------------------------------------------------------------
# Configuration Loading Tests
# ---------------------------------------------------------------------------

def test_loads_lane_and_global_config():
    """Handler should load both lane-specific and global configuration."""
    event = _make_event(lane_id="OBJ_IDENTITY_ESCALATION")
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=True)
        
        handler(event, None)
        
        # Verify config loading was called
        mock_config_loader.return_value.load_lane_config.assert_called_once_with("OBJ_IDENTITY_ESCALATION")
        mock_config_loader.return_value.load_global_config.assert_called_once()


# ---------------------------------------------------------------------------
# DVWA Client Configuration Tests
# ---------------------------------------------------------------------------

def test_dvwa_client_configured_with_lane_config():
    """DVWAClient should be configured with values from lane config."""
    event = _make_event()
    lane_config = _make_lane_config()
    lane_config.target_url = "http://custom-dvwa:8080/dvwa"
    lane_config.http_timeout_ms = 15000
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator:
        
        mock_config_loader.return_value.load_lane_config.return_value = lane_config
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="testuser",
            dvwa_admin_password="testpass"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=True)
        
        handler(event, None)
        
        # Verify DVWAClient was initialized with correct parameters
        mock_dvwa_client.assert_called_once_with(
            base_url="http://custom-dvwa:8080/dvwa",
            username="testuser",
            password="testpass",
            timeout_ms=15000,
        )


# ---------------------------------------------------------------------------
# Bedrock Client Configuration Tests
# ---------------------------------------------------------------------------

def test_bedrock_client_configured_correctly():
    """BedrockClient should be configured with correct model ID and retry count."""
    event = _make_event()
    lane_config = _make_lane_config()
    lane_config.bedrock_max_retries = 5
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = lane_config
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = 0.7
        
        handler(event, None)
        
        # Verify BedrockClient was initialized with correct parameters
        mock_bedrock_client.assert_called_once_with(
            model_id="amazon.nova-pro-v1:0",
            max_retries=5,
            s3_bucket="test-bucket",
        )


# ---------------------------------------------------------------------------
# Mutation Parsing Tests
# ---------------------------------------------------------------------------

def test_mutation_parsed_from_event():
    """Handler should correctly parse Mutation object from event."""
    mutation = _make_mutation(
        payload="custom payload",
        endpoint="/custom/endpoint",
        method="PUT",
        headers={"X-Custom": "header"},
        rationale="Custom test"
    )
    event = _make_event(mutation=mutation)
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=True)
        
        handler(event, None)
        
        # Verify the mutation was passed to execute_request
        call_args = mock_dvwa_client.return_value.execute_request.call_args
        passed_mutation = call_args[0][0]  # First positional argument
        
        assert passed_mutation.attack_payload == "custom payload"
        assert passed_mutation.target_endpoint == "/custom/endpoint"
        assert passed_mutation.http_method == "PUT"
        assert passed_mutation.headers == {"X-Custom": "header"}
        assert passed_mutation.rationale == "Custom test"


# ---------------------------------------------------------------------------
# Logging Tests
# ---------------------------------------------------------------------------

@patch("src.workers.reproducibility_runner.logger")
def test_logs_start_and_complete_events(mock_logger):
    """Handler should log structured start and complete events."""
    event = _make_event(run_id="test-run-456", lane_id="OBJ_WAF_BYPASS", rerun_index=3)
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = 0.7
        
        handler(event, None)
        
        # Verify start log
        start_log_call = mock_logger.info.call_args_list[0]
        start_log_data = json.loads(start_log_call[0][0])
        assert start_log_data["event_type"] == "reproducibility_runner_start"
        assert start_log_data["run_id"] == "test-run-456"
        assert start_log_data["lane_id"] == "OBJ_WAF_BYPASS"
        assert start_log_data["rerun_index"] == 3
        
        # Verify complete log
        complete_log_call = mock_logger.info.call_args_list[1]
        complete_log_data = json.loads(complete_log_call[0][0])
        assert complete_log_data["event_type"] == "reproducibility_runner_complete"
        assert complete_log_data["run_id"] == "test-run-456"
        assert complete_log_data["lane_id"] == "OBJ_WAF_BYPASS"
        assert complete_log_data["rerun_index"] == 3
        assert "phi_score" in complete_log_data
        assert "passed" in complete_log_data


@patch("src.workers.reproducibility_runner.logger")
def test_logs_dvwa_error_event(mock_logger):
    """Handler should log DVWA error events."""
    event = _make_event()
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.side_effect = DVWAUnreachableError("Connection failed")
        
        handler(event, None)
        
        # Verify error log
        error_log_call = mock_logger.warning.call_args
        error_log_data = json.loads(error_log_call[0][0])
        assert error_log_data["event_type"] == "reproducibility_dvwa_error"
        assert "error" in error_log_data


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------

@settings(max_examples=50)
@given(
    current_phi=st.floats(min_value=0.0, max_value=1.0),
    new_phi=st.floats(min_value=0.0, max_value=1.0),
)
def test_pass_fail_logic_property(current_phi, new_phi):
    """Pass/fail logic should be consistent: passed = (new_phi > current_phi)."""
    event = _make_event(current_phi_score=current_phi)
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = new_phi
        
        result = handler(event, None)
        
        expected_passed = new_phi > current_phi
        assert result["passed"] == expected_passed
        assert result["phi_score"] == new_phi


@settings(max_examples=30)
@given(rerun_index=st.integers(min_value=0, max_value=100))
def test_rerun_index_preservation_property(rerun_index):
    """The rerun_index from input should always be preserved in output."""
    event = _make_event(rerun_index=rerun_index)
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=True)
        
        result = handler(event, None)
        assert result["rerun_index"] == rerun_index


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------

def test_missing_rerun_index_defaults_to_zero():
    """Handler should default rerun_index to 0 if not provided in event."""
    event = _make_event()
    del event["rerun_index"]  # Remove rerun_index
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=True)
        
        result = handler(event, None)
        assert result["rerun_index"] == 0


def test_missing_current_phi_score_defaults_to_zero():
    """Handler should default current_phi_score to 0.0 if not provided in event."""
    event = _make_event()
    del event["current_phi_score"]  # Remove current_phi_score
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = 0.1  # Any positive value should pass
        
        result = handler(event, None)
        # Since current_phi defaults to 0.0, any positive phi_score should result in passed=True
        assert result["passed"] is True


def test_default_environment_variables_used():
    """Handler should use default environment variables when not overridden."""
    event = _make_event()
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = 0.7
        
        handler(event, None)
        
        # Verify ConfigLoader was initialized with test environment (from conftest.py)
        mock_config_loader.assert_called_once_with(env="test")
        
        # Verify BedrockClient was initialized with default model and test bucket
        mock_bedrock_client.assert_called_once_with(
            model_id="amazon.nova-pro-v1:0",
            max_retries=3,  # From lane config
            s3_bucket="test-bucket",
        )


def test_phi_score_exactly_equal_to_current_fails():
    """When new Phi score equals current Phi score, passed should be False."""
    current_phi = 0.5
    event = _make_event(current_phi_score=current_phi)
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = current_phi  # Exactly equal
        
        result = handler(event, None)
        assert result["passed"] is False


def test_execute_request_called_with_run_and_lane_ids():
    """DVWAClient.execute_request should be called with run_id and lane_id."""
    event = _make_event(run_id="custom-run-789", lane_id="OBJ_CUSTOM_LANE")
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator:
        
        mock_config_loader.return_value.load_lane_config.return_value = _make_lane_config()
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=True)
        
        handler(event, None)
        
        # Verify execute_request was called with correct run_id and lane_id
        call_kwargs = mock_dvwa_client.return_value.execute_request.call_args.kwargs
        assert call_kwargs["run_id"] == "custom-run-789"
        assert call_kwargs["lane_id"] == "OBJ_CUSTOM_LANE"


def test_bedrock_score_experiment_called_with_correct_parameters():
    """BedrockClient.score_experiment should be called with correct parameters."""
    event = _make_event(run_id="score-test-run", lane_id="OBJ_SCORE_LANE")
    lane_config = _make_lane_config()
    experiment_result = _make_experiment_result()
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = lane_config
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = experiment_result
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = PhiScores(0.6, 0.4, 0.3)
        mock_phi_function.return_value.compute.return_value = 0.7
        
        handler(event, None)
        
        # Verify score_experiment was called with correct parameters
        call_args = mock_bedrock_client.return_value.score_experiment.call_args
        assert call_args[0][0] == experiment_result  # result
        assert call_args[0][1] == lane_config  # lane_config
        assert call_args[0][2] is None  # strategy (None for reproducibility runner)
        assert call_args[0][3] == "score-test-run"  # run_id
        assert call_args[0][4] == "OBJ_SCORE_LANE"  # lane_id


def test_phi_function_called_with_scores_and_weights():
    """PhiFunction.compute should be called with scores and weights from config."""
    event = _make_event()
    lane_config = _make_lane_config()
    phi_scores = PhiScores(0.6, 0.4, 0.3)
    
    with patch("src.workers.reproducibility_runner.ConfigLoader") as mock_config_loader, \
         patch("src.workers.reproducibility_runner.DVWAClient") as mock_dvwa_client, \
         patch("src.workers.reproducibility_runner.TerminalValidator") as mock_terminal_validator, \
         patch("src.workers.reproducibility_runner.BedrockClient") as mock_bedrock_client, \
         patch("src.workers.reproducibility_runner.PhiFunction") as mock_phi_function:
        
        mock_config_loader.return_value.load_lane_config.return_value = lane_config
        mock_config_loader.return_value.load_global_config.return_value = MagicMock(
            dvwa_admin_username="admin",
            dvwa_admin_password="password"
        )
        mock_dvwa_client.return_value.execute_request.return_value = _make_experiment_result()
        mock_terminal_validator.return_value.evaluate.return_value = TerminalResult(passed=False)
        mock_bedrock_client.return_value.score_experiment.return_value = phi_scores
        mock_phi_function.return_value.compute.return_value = 0.7
        
        handler(event, None)
        
        # Verify PhiFunction.compute was called with correct parameters
        call_args = mock_phi_function.return_value.compute.call_args
        assert call_args[0][0] == phi_scores  # scores
        assert call_args[0][1] == lane_config.phi_weights  # weights