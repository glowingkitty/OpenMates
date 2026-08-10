#!/usr/bin/env python3
"""Tests for commit-scoped deploy verification helpers.

Fast checks may use the latest ready deployment; exact checks must match the
requested commit before they are treated as proof.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_TESTS_PATH = PROJECT_ROOT / "scripts" / "run_tests.py"


def load_run_tests_module():
    spec = importlib.util.spec_from_file_location("openmates_run_tests_commit_scoped", RUN_TESTS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_deployment_matches_exact_commit_prefix():
    run_tests = load_run_tests_module()
    deployment = {"meta": {"githubCommitSha": "abcdef123456"}, "state": "READY"}

    assert run_tests._deployment_matches_commit(deployment, "abcdef1", exact=True) is True
    assert run_tests._deployment_matches_commit(deployment, "123456", exact=True) is False


def test_fast_verification_accepts_latest_ready_dev_deployment():
    run_tests = load_run_tests_module()
    deployment = {"meta": {"githubCommitSha": "abcdef123456"}, "state": "READY"}

    assert run_tests._deployment_matches_commit(deployment, "123456", exact=False) is True
