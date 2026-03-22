# backend/shared/testing/__init__.py
# Shared testing utilities for the OpenMates backend.
#
# This package provides infrastructure for "live mock" testing — running the full
# processing pipeline (preprocessing, main inference, postprocessing, billing) while
# intercepting external API calls (LLM providers, skill HTTP requests) with cached
# record-and-replay responses. This enables zero-cost integration testing.
#
# Security:
#   All mock functionality is gated on SERVER_ENVIRONMENT != "production"
#   AND requires MOCK_EXTERNAL_APIS=true env var as a feature flag.
#   Activation is per-request via markers, not server-wide.
#
# Architecture context: See docs/architecture/live-mock-testing.md
#
# Modules:
#   mock_context.py           - Per-request context variables and marker detection
#   api_response_cache.py     - Fingerprinting and JSON file cache for API responses
#   caching_http_transport.py - httpx transport wrapper with cache for skill providers
