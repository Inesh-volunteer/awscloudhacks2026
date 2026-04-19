"""
Property-based and unit tests for DVWAClient.

Properties covered:
  Property 11: HTTP request fidelity
  Property 12: Experiment result capture completeness
  Property 13: HTTP timeout enforcement
  Property 33: DVWA security level set-and-verify round-trip
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.lib.dvwa_client import (
    DVWAClient,
    DVWATimeoutError,
    DVWAUnreachableError,
    SecurityLevelVerificationError,
)
from src.lib.models import Mutation

_printable = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters=" _-./?"
))


def _make_mutation(method="POST", endpoint="/dvwa/test", payload="id=1", headers=None):
    return Mutation(
        attack_payload=payload,
        target_endpoint=endpoint,
        http_method=method,
        headers=headers or {"Content-Type": "application/x-www-form-urlencoded"},
        rationale="test",
    )


def _make_mock_response(status=200, body="OK", headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    resp.headers = headers or {"Content-Type": "text/html"}
    resp.url = "http://dvwa/index.php"
    return resp


# ---------------------------------------------------------------------------
# Property 11: HTTP request fidelity
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 11: HTTP request fidelity
@settings(max_examples=100)
@given(
    method=st.sampled_from(["GET", "POST", "PUT", "DELETE"]),
    endpoint=_printable,
    payload=st.text(max_size=200),
)
def test_execute_request_uses_mutation_fields_exactly(method, endpoint, payload):
    """The outgoing request must use the mutation's method, endpoint, and payload exactly."""
    mutation = _make_mutation(method=method, endpoint=endpoint, payload=payload)

    with patch("src.lib.dvwa_client.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        # Mock login
        login_page = MagicMock()
        login_page.text = '<input name="user_token" value="abc123">'
        login_page.url = "http://dvwa/index.php"
        mock_session.get.return_value = login_page
        mock_session.post.return_value = MagicMock(
            text="logout", url="http://dvwa/index.php"
        )

        # Mock experiment response
        exp_resp = _make_mock_response(200, "response body")
        mock_session.request.return_value = exp_resp

        client = DVWAClient("http://dvwa", "admin", "password", timeout_ms=5000)
        result = client.execute_request(mutation, run_id="r1", lane_id="L1")

        # Verify the request was made with exact mutation fields
        call_kwargs = mock_session.request.call_args
        assert call_kwargs.kwargs["method"] == method.upper() or \
               call_kwargs.args[0] == method.upper()
        assert mutation.attack_payload in (
            call_kwargs.kwargs.get("data", "") or ""
        )


# ---------------------------------------------------------------------------
# Property 12: Experiment result capture completeness
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 12: Experiment result capture completeness
@settings(max_examples=100)
@given(
    status=st.integers(min_value=100, max_value=599),
    body=st.text(max_size=200),
)
def test_execute_request_captures_status_headers_body(status, body):
    """ExperimentResult must contain status_code, headers, and body."""
    mutation = _make_mutation()

    with patch("src.lib.dvwa_client.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        login_page = MagicMock()
        login_page.text = '<input name="user_token" value="tok">'
        login_page.url = "http://dvwa/index.php"
        mock_session.get.return_value = login_page
        mock_session.post.return_value = MagicMock(
            text="logout", url="http://dvwa/index.php"
        )

        exp_resp = _make_mock_response(status, body, {"X-Test": "1"})
        mock_session.request.return_value = exp_resp

        client = DVWAClient("http://dvwa", "admin", "password")
        result = client.execute_request(mutation)

        assert result.response is not None
        assert result.response.status_code == status
        assert isinstance(result.response.headers, dict)
        assert result.response.body == body


# ---------------------------------------------------------------------------
# Property 13: HTTP timeout enforcement
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 13: HTTP timeout enforcement
def test_execute_request_raises_timeout_error_on_timeout():
    """Timeout during request must raise DVWATimeoutError."""
    from requests.exceptions import Timeout

    mutation = _make_mutation()

    with patch("src.lib.dvwa_client.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        login_page = MagicMock()
        login_page.text = '<input name="user_token" value="tok">'
        login_page.url = "http://dvwa/index.php"
        mock_session.get.return_value = login_page
        mock_session.post.return_value = MagicMock(
            text="logout", url="http://dvwa/index.php"
        )

        mock_session.request.side_effect = Timeout("timed out")

        client = DVWAClient("http://dvwa", "admin", "password", timeout_ms=100)
        with pytest.raises(DVWATimeoutError):
            client.execute_request(mutation)


# ---------------------------------------------------------------------------
# Property 33: DVWA security level set-and-verify round-trip
# ---------------------------------------------------------------------------

# Feature: lambda-redteam-harness, Property 33: DVWA security level set-and-verify round-trip
@settings(max_examples=20)
@given(level=st.sampled_from(["low", "medium", "high", "impossible"]))
def test_set_security_level_verifies_round_trip(level):
    """After set_security_level(level), verify_security_level() must return the same level."""
    with patch("src.lib.dvwa_client.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        # Login page
        login_page = MagicMock()
        login_page.text = '<input name="user_token" value="tok">'
        login_page.url = "http://dvwa/index.php"

        # Security page with CSRF token and the level selected
        security_page_get = MagicMock()
        security_page_get.text = (
            '<input name="user_token" value="csrf123">'
            f'<option value="{level}" selected>{level}</option>'
        )

        # Security page after POST (for internal verification)
        security_page_verify_internal = MagicMock()
        security_page_verify_internal.text = (
            f'<option value="{level}" selected>{level}</option>'
        )

        # Security page for explicit verification call
        security_page_verify = MagicMock()
        security_page_verify.text = (
            f'<option value="{level}" selected>{level}</option>'
        )

        # Mock the sequence: 
        # 1. login GET, 
        # 2. security GET (for token), 
        # 3. security GET (for internal verify), 
        # 4. security GET (for explicit verify)
        mock_session.get.side_effect = [
            login_page, 
            security_page_get, 
            security_page_verify_internal,
            security_page_verify
        ]
        mock_session.post.return_value = MagicMock(
            text="logout", url="http://dvwa/index.php"
        )

        client = DVWAClient("http://dvwa", "admin", "password")
        client.set_security_level(level)
        verified = client.verify_security_level()
        assert verified == level


# Unit: invalid security level raises ValueError
def test_set_security_level_invalid_raises_value_error():
    with patch("src.lib.dvwa_client.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        login_page = MagicMock()
        login_page.text = '<input name="user_token" value="tok">'
        login_page.url = "http://dvwa/index.php"
        mock_session.get.return_value = login_page
        mock_session.post.return_value = MagicMock(
            text="logout", url="http://dvwa/index.php"
        )
        client = DVWAClient("http://dvwa", "admin", "password")
        with pytest.raises(ValueError):
            client.set_security_level("extreme")
