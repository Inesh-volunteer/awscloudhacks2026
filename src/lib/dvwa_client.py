"""
DVWAClient — HTTP client for interacting with Damn Vulnerable Web Application.

Property coverage:
  - Property 11: HTTP request fidelity — the request sent to DVWA matches the
    mutation's method, endpoint, headers, and payload exactly.
  - Property 12: Experiment result capture completeness — every ExperimentResult
    produced by execute_request contains a populated HttpResponse with
    status_code, headers, and body (or a non-None error string on failure).
  - Property 13: HTTP timeout enforcement — when the elapsed time exceeds
    timeout_ms, a DVWATimeoutError is raised before returning a result.
  - Property 33: DVWA security level set-and-verify round-trip — after
    set_security_level(level) completes without error, verify_security_level()
    returns the same level string.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

from src.lib.models import ExperimentResult, HttpRequest, HttpResponse, Mutation


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class DVWAUnreachableError(Exception):
    """Raised when a connection to DVWA cannot be established."""


class DVWATimeoutError(Exception):
    """Raised when a DVWA request exceeds the configured timeout."""


class SecurityLevelVerificationError(Exception):
    """Raised when the verified security level does not match the requested level."""


# ---------------------------------------------------------------------------
# DVWAClient
# ---------------------------------------------------------------------------


class DVWAClient:
    """HTTP client for DVWA with session management, security level control,
    and experiment execution.

    Args:
        base_url:    Root URL of the DVWA instance, e.g. ``http://localhost:80``.
        username:    DVWA admin username.
        password:    DVWA admin password.
        timeout_ms:  Per-request HTTP timeout in milliseconds.
    """

    _SECURITY_LEVELS = {"low", "medium", "high", "impossible"}

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout_ms: int = 5000,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout_s: float = timeout_ms / 1000.0
        self._session = requests.Session()
        self._login()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        """Build an absolute URL from a relative path."""
        return urljoin(self._base_url + "/", path.lstrip("/"))

    def _get_csrf_token(self, page_path: str) -> str:
        """Fetch a page and extract the ``user_token`` CSRF field value."""
        try:
            resp = self._session.get(
                self._url(page_path), timeout=self._timeout_s
            )
        except RequestsTimeout as exc:
            raise DVWATimeoutError(
                f"Timeout fetching CSRF token from {page_path}"
            ) from exc
        except RequestsConnectionError as exc:
            raise DVWAUnreachableError(
                f"Cannot reach DVWA at {self._base_url}"
            ) from exc

        # Simple token extraction — DVWA embeds it as a hidden input.
        token = self._parse_csrf_token(resp.text)
        if not token:
            raise DVWAUnreachableError(
                f"CSRF token not found on page {page_path}"
            )
        return token

    @staticmethod
    def _parse_csrf_token(html: str) -> Optional[str]:
        """Extract ``user_token`` value from an HTML page."""
        import re

        match = re.search(
            r'<input[^>]+name=["\']user_token["\'][^>]+value=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
        # Also try reversed attribute order
        match = re.search(
            r'<input[^>]+value=["\']([^"\']+)["\'][^>]+name=["\']user_token["\']',
            html,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def _login(self) -> None:
        """POST credentials to /login.php and store the session cookie.

        Raises:
            DVWAUnreachableError: If the connection fails.
            DVWATimeoutError:     If the request times out.
        """
        login_url = self._url("/login.php")
        token = self._get_csrf_token("/login.php")

        payload = {
            "username": self._username,
            "password": self._password,
            "Login": "Login",
            "user_token": token,
        }

        try:
            resp = self._session.post(
                login_url,
                data=payload,
                timeout=self._timeout_s,
                allow_redirects=True,
            )
        except RequestsTimeout as exc:
            raise DVWATimeoutError("Timeout during DVWA login") from exc
        except RequestsConnectionError as exc:
            raise DVWAUnreachableError(
                f"Cannot reach DVWA at {self._base_url}"
            ) from exc

        # DVWA redirects to index.php on success; a login page in the response
        # body indicates failure.
        if "login.php" in resp.url or "Login" in resp.text[:200]:
            # Check more carefully — DVWA may still show login on bad creds
            if "logout" not in resp.text.lower():
                raise DVWAUnreachableError(
                    "DVWA login failed — check credentials"
                )

    # ------------------------------------------------------------------
    # Security level management
    # ------------------------------------------------------------------

    def set_security_level(self, level: str) -> None:
        """Set the DVWA security level via POST to /security.php.

        Property 33: After this call succeeds, verify_security_level() must
        return the same ``level`` string (set-and-verify round-trip).

        Args:
            level: One of ``low``, ``medium``, ``high``, ``impossible``.

        Raises:
            ValueError:                    If ``level`` is not a valid DVWA level.
            DVWAUnreachableError:          On connection failure.
            DVWATimeoutError:              On request timeout.
            SecurityLevelVerificationError: If the post-set verification fails.
        """
        level = level.lower()
        if level not in self._SECURITY_LEVELS:
            raise ValueError(
                f"Invalid security level '{level}'. "
                f"Must be one of {sorted(self._SECURITY_LEVELS)}."
            )

        token = self._get_csrf_token("/security.php")

        payload = {
            "security": level,
            "seclev_submit": "Submit",
            "user_token": token,
        }

        try:
            self._session.post(
                self._url("/security.php"),
                data=payload,
                timeout=self._timeout_s,
                allow_redirects=True,
            )
        except RequestsTimeout as exc:
            raise DVWATimeoutError(
                f"Timeout setting security level to '{level}'"
            ) from exc
        except RequestsConnectionError as exc:
            raise DVWAUnreachableError(
                f"Cannot reach DVWA at {self._base_url}"
            ) from exc

        # Property 33: verify the level was actually applied
        verified = self.verify_security_level()
        if verified != level:
            raise SecurityLevelVerificationError(
                f"Security level mismatch: requested '{level}', "
                f"but DVWA reports '{verified}'."
            )

    def verify_security_level(self) -> str:
        """GET /security.php and parse the currently active security level.

        Property 33: This is the verification half of the set-and-verify
        round-trip; it must return the level that was last successfully set.

        Returns:
            The current security level string (e.g. ``"low"``).

        Raises:
            DVWAUnreachableError: On connection failure or unparseable response.
            DVWATimeoutError:     On request timeout.
        """
        try:
            resp = self._session.get(
                self._url("/security.php"), timeout=self._timeout_s
            )
        except RequestsTimeout as exc:
            raise DVWATimeoutError(
                "Timeout verifying DVWA security level"
            ) from exc
        except RequestsConnectionError as exc:
            raise DVWAUnreachableError(
                f"Cannot reach DVWA at {self._base_url}"
            ) from exc

        level = self._parse_security_level(resp.text)
        if not level:
            raise DVWAUnreachableError(
                "Could not parse current security level from /security.php"
            )
        return level

    @staticmethod
    def _parse_security_level(html: str) -> Optional[str]:
        """Extract the selected security level from the /security.php HTML."""
        import re

        # DVWA renders a <select name="security"> with the active option selected.
        match = re.search(
            r'<option[^>]+value=["\'](\w+)["\'][^>]+selected',
            html,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).lower()

        # Fallback: look for the text "Security Level is currently …"
        match = re.search(
            r"Security Level is currently\s+<[^>]+>(\w+)<",
            html,
            re.IGNORECASE,
        )
        return match.group(1).lower() if match else None

    # ------------------------------------------------------------------
    # Experiment execution
    # ------------------------------------------------------------------

    def execute_request(
        self,
        mutation: Mutation,
        run_id: str = "",
        lane_id: str = "",
    ) -> ExperimentResult:
        """Send the HTTP request defined by *mutation* and capture the full response.

        Property 11 (HTTP request fidelity): The outgoing request uses exactly
        the method, endpoint, headers, and payload specified in the mutation —
        no fields are silently dropped or transformed.

        Property 12 (Experiment result capture completeness): The returned
        ExperimentResult always contains either a fully populated HttpResponse
        (status_code, headers, body) or a non-None error string; it is never
        in an ambiguous half-populated state.

        Property 13 (HTTP timeout enforcement): If the DVWA server does not
        respond within ``timeout_ms`` milliseconds, a DVWATimeoutError is
        raised and no partial result is returned.

        Args:
            mutation: The attack variant to execute.
            run_id:   Identifier for the current harness run (for logging).
            lane_id:  Identifier for the current lane (for logging).

        Returns:
            An ExperimentResult with the captured request and response.

        Raises:
            DVWATimeoutError:    If the request exceeds the configured timeout.
            DVWAUnreachableError: If the connection fails.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        target_url = self._url(mutation.target_endpoint)

        # Build the captured request record (Property 11 — exact fidelity)
        http_request = HttpRequest(
            method=mutation.http_method.upper(),
            url=target_url,
            headers=dict(mutation.headers),
            body=mutation.attack_payload,
        )

        try:
            start_ns = time.monotonic_ns()

            # Property 11: use mutation fields verbatim
            resp = self._session.request(
                method=mutation.http_method.upper(),
                url=target_url,
                headers=mutation.headers,
                data=mutation.attack_payload,
                timeout=self._timeout_s,
                allow_redirects=True,
            )

            elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000

            # Property 12: capture all three response fields
            http_response = HttpResponse(
                status_code=resp.status_code,
                headers=dict(resp.headers),
                body=resp.text,
                elapsed_ms=elapsed_ms,
            )

            return ExperimentResult(
                run_id=run_id,
                lane_id=lane_id,
                timestamp=timestamp,
                request=http_request,
                response=http_response,
                error=None,
            )

        except RequestsTimeout as exc:
            # Property 13: timeout → DVWATimeoutError, no partial result
            raise DVWATimeoutError(
                f"Request to '{target_url}' timed out after "
                f"{self._timeout_s * 1000:.0f} ms"
            ) from exc

        except RequestsConnectionError as exc:
            raise DVWAUnreachableError(
                f"Cannot reach DVWA at {self._base_url}"
            ) from exc

        except Exception as exc:  # noqa: BLE001
            # Property 12: on unexpected errors, return a result with error set
            return ExperimentResult(
                run_id=run_id,
                lane_id=lane_id,
                timestamp=timestamp,
                request=http_request,
                response=None,
                error=str(exc),
            )
