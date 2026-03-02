# backend/upload/vault/Dockerfile
#
# Lightweight init container for the uploads VM local Vault.
# Runs once at stack startup to:
#   1. Initialize Vault (first boot only) — saves unseal key + root token
#   2. Auto-unseal Vault using the saved unseal key (subsequent restarts)
#   3. Enable KV v2 engine
#   4. Create read-only uploads-service policy
#   5. Create or reuse scoped API token (saved to vault-setup-data volume)
#   6. Migrate SECRET__* env vars into Vault KV (idempotent)
#
# Exits after setup completes (restart: on-failure handles retries).
# The Vault config (vault.hcl) is volume-mounted at /vault/config — no need
# to bake it into this image.

FROM python:3.13-slim

WORKDIR /app

# Only dependency is httpx for Vault API calls
RUN pip install --no-cache-dir httpx==0.28.1

COPY backend/upload/vault/setup_vault.py .
RUN chmod +x setup_vault.py

CMD ["python", "setup_vault.py"]
