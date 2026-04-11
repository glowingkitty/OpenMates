# backend/tests/provider_contracts/__init__.py
#
# Contract-probe tests for every reverse-engineered / scraped provider.
# Run daily inside app-ai-worker via scripts/run_provider_contracts.py — NEVER
# in GHA because they need Vault secrets and the Webshare proxy.
