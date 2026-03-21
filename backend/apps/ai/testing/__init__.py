# backend/apps/ai/testing/__init__.py
# E2E test mock/replay system for LLM inference and app skill outputs.
#
# This package provides a fixture-based mock system that allows Playwright E2E tests
# to run without hitting real LLM providers or external APIs (zero cost per test run).
#
# Architecture context: See docs/architecture/e2e-test-mock-replay.md
#
# Modules:
#   mock_replay.py       - Marker detection, fixture loading, Redis stream replay
#   fixture_recorder.py  - Records real LLM/skill responses as fixture files
#
# Security:
#   All mock functionality is gated on SERVER_ENVIRONMENT != "production".
#   The modules are never imported in production environments.
