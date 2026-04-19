"""
Property-based and unit tests for ConfigLoader.

Properties covered:
  Property 5:  MissingConfigError raised for every missing key
  Property 6:  Worker error payload contains lane_id + failure_reason
  Property 31: SSM called only once per invocation (cache)
  Property 32: All SSM paths start with the configured root prefix
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.lib.config_loader import ConfigLoadError, ConfigLoader, MissingConfigError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ssm_response(params: dict[str, str]) -> dict:
    """Build a mock SSM get_parameters response from a name→value dict."""
    return {
        "Parameters": [{"Name": k, "Value": v} for k, v in params.items()],
        "InvalidParameters": [],
    }


def _full_global_params(prefix: str) -> dict[str, str]:
    return {
        f"{prefix}/schedule_expression": "rate(5 minutes)",
        f"{prefix}/active_lanes": '["OBJ_WEB_BYPASS"]',
        f"{prefix}/bedrock_model_id": "amazon.nova-pro-v1:0",
        f"{prefix}/map_max_concurrency": "10",
        f"{prefix}/dvwa/admin_username": "admin",
        f"{prefix}/dvwa/admin_password": "password",
    }


def _full_lane_params(prefix: str, lane_id: str) -> dict[str, str]:
    base = f"{prefix}/lanes/{lane_id}"
    return {
        f"{base}/target_url": "http://10.0.1.50/dvwa",
        f"{base}/dvwa_security_level": "low",
        f"{base}/terminal_condition": json.dumps({
            "lane_type": "WEB_BYPASS",
            "success_indicator": "Welcome to DVWA",
        }),
        f"{base}/phi_weights/alpha": "0.4",
        f"{base}/phi_weights/beta": "0.35",
        f"{base}/phi_weights/gamma": "0.25",
        f"{base}/gate_thresholds/reproducibility_min_fraction": "0.8",
        f"{base}/gate_thresholds/reproducibility_reruns": "5",
        f"{base}/gate_thresholds/evidence_markers": '["SQL syntax"]',
        f"{base}/gate_thresholds/cost_max_tokens": "50000",
        f"{base}/gate_thresholds/cost_max_duration_ms": "240000",
        f"{base}/gate_thresholds/noise_patterns": '["Login required"]',
        f"{base}/bedrock_max_retries": "3",
        f"{base}/http_timeout_ms": "10000",
    }


# ---------------------------------------------------------------------------
# Property 5: MissingConfigError raised for every missing key
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 5: Config completeness validation
@settings(max_examples=100)
@given(missing_key=st.sampled_from([
    "schedule_expression",
    "active_lanes",
    "bedrock_model_id",
    "map_max_concurrency",
    "dvwa/admin_username",
    "dvwa/admin_password",
]))
def test_missing_global_key_raises_missing_config_error(missing_key):
    """Any missing global key must raise MissingConfigError naming that key."""
    prefix = "/autoredteam/dev"
    params = _full_global_params(prefix)
    full_key = f"{prefix}/{missing_key}"
    del params[full_key]

    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = _make_ssm_response(params)

    loader = ConfigLoader(env="dev", ssm_client=mock_ssm)
    with pytest.raises(MissingConfigError) as exc_info:
        loader.load_global_config()

    assert full_key in exc_info.value.missing_keys


# Feature: lambda-redteam-harness, Property 5: Config completeness validation (lane)
@settings(max_examples=100)
@given(missing_suffix=st.sampled_from([
    "target_url",
    "dvwa_security_level",
    "terminal_condition",
    "phi_weights/alpha",
    "phi_weights/beta",
    "phi_weights/gamma",
    "gate_thresholds/reproducibility_min_fraction",
    "gate_thresholds/reproducibility_reruns",
    "gate_thresholds/evidence_markers",
    "gate_thresholds/cost_max_tokens",
    "gate_thresholds/cost_max_duration_ms",
    "gate_thresholds/noise_patterns",
    "bedrock_max_retries",
    "http_timeout_ms",
]))
def test_missing_lane_key_raises_missing_config_error(missing_suffix):
    """Any missing lane key must raise MissingConfigError naming that key."""
    prefix = "/autoredteam/dev"
    lane_id = "OBJ_WEB_BYPASS"
    params = _full_lane_params(prefix, lane_id)
    full_key = f"{prefix}/lanes/{lane_id}/{missing_suffix}"
    del params[full_key]

    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = _make_ssm_response(params)

    loader = ConfigLoader(env="dev", ssm_client=mock_ssm)
    with pytest.raises(MissingConfigError) as exc_info:
        loader.load_lane_config(lane_id)

    assert full_key in exc_info.value.missing_keys


# ---------------------------------------------------------------------------
# Property 31: SSM called only once per invocation (cache)
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 31: Config caching — single SSM read per invocation
def test_ssm_called_only_once_for_repeated_global_loads():
    """load_global_config called twice must only hit SSM once."""
    prefix = "/autoredteam/dev"
    params = _full_global_params(prefix)

    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = _make_ssm_response(params)

    loader = ConfigLoader(env="dev", ssm_client=mock_ssm)
    loader.load_global_config()
    loader.load_global_config()  # second call — should use cache

    assert mock_ssm.get_parameters.call_count == 1


# Feature: lambda-redteam-harness, Property 31: Config caching — single SSM read per invocation
def test_ssm_called_only_once_for_repeated_lane_loads():
    """load_lane_config called twice for the same lane must only hit SSM once per batch."""
    prefix = "/autoredteam/dev"
    lane_id = "OBJ_WEB_BYPASS"
    params = _full_lane_params(prefix, lane_id)

    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = _make_ssm_response(params)

    loader = ConfigLoader(env="dev", ssm_client=mock_ssm)
    loader.load_lane_config(lane_id)
    initial_call_count = mock_ssm.get_parameters.call_count
    loader.load_lane_config(lane_id)  # second call — should use cache

    # Should not make additional SSM calls on second load
    assert mock_ssm.get_parameters.call_count == initial_call_count


# ---------------------------------------------------------------------------
# Property 32: All SSM paths start with the configured root prefix
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 32: Parameter Store path prefix
@settings(max_examples=50)
@given(env=st.text(min_size=1, max_size=20, alphabet=st.characters(
    whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"
)))
def test_all_ssm_paths_start_with_prefix(env):
    """Every SSM path used must start with /autoredteam/{env}/."""
    prefix = f"/autoredteam/{env}"
    params = _full_global_params(prefix)

    captured_names: list[str] = []

    def fake_get_parameters(Names, WithDecryption=True):
        captured_names.extend(Names)
        return _make_ssm_response({k: v for k, v in params.items() if k in Names})

    mock_ssm = MagicMock()
    mock_ssm.get_parameters.side_effect = fake_get_parameters

    loader = ConfigLoader(env=env, ssm_client=mock_ssm)
    loader.load_global_config()

    for name in captured_names:
        assert name.startswith(f"/autoredteam/{env}/"), (
            f"SSM path '{name}' does not start with '/autoredteam/{env}/'"
        )


# ---------------------------------------------------------------------------
# Unit: ConfigLoadError on SSM connectivity failure
# ---------------------------------------------------------------------------

def test_ssm_unreachable_raises_config_load_error():
    """SSM connectivity failure must raise ConfigLoadError."""
    mock_ssm = MagicMock()
    mock_ssm.get_parameters.side_effect = Exception("Connection timeout")

    loader = ConfigLoader(env="dev", ssm_client=mock_ssm)
    with pytest.raises(ConfigLoadError):
        loader.load_global_config()


# ---------------------------------------------------------------------------
# Unit: Successful load returns fully populated LaneConfig
# ---------------------------------------------------------------------------

def test_load_lane_config_returns_all_fields():
    """A complete SSM response must produce a fully populated LaneConfig."""
    prefix = "/autoredteam/dev"
    lane_id = "OBJ_WEB_BYPASS"
    params = _full_lane_params(prefix, lane_id)

    mock_ssm = MagicMock()
    mock_ssm.get_parameters.return_value = _make_ssm_response(params)

    loader = ConfigLoader(env="dev", ssm_client=mock_ssm)
    cfg = loader.load_lane_config(lane_id)

    assert cfg.lane_id == lane_id
    assert cfg.target_url == "http://10.0.1.50/dvwa"
    assert cfg.dvwa_security_level == "low"
    assert cfg.phi_weights.alpha == 0.4
    assert cfg.phi_weights.beta == 0.35
    assert cfg.phi_weights.gamma == 0.25
    assert cfg.gate_thresholds.reproducibility_reruns == 5
    assert cfg.gate_thresholds.evidence_markers == ["SQL syntax"]
    assert cfg.bedrock_max_retries == 3
    assert cfg.http_timeout_ms == 10000
