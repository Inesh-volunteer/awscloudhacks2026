"""
Shared fixtures for unit tests.
"""
import os
import pytest

# Ensure Lambda env vars are set for all unit tests
os.environ.setdefault("AUTOREDTEAM_ENV", "test")
os.environ.setdefault("ARTIFACT_BUCKET", "test-bucket")
os.environ.setdefault("LAMBDA_TIMEOUT_MS", "300000")
os.environ.setdefault("REPRODUCIBILITY_SFN_ARN", "")
