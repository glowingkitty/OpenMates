# backend/upload/vault/Dockerfile
#
# Lightweight init container for the uploads VM local Vault.
# Runs once at stack startup to:
#   1. Enable KV v2 engine
#   2. Create read-only policy
#   3. Create scoped API token
#   4. Migrate SECRET__* env vars into Vault KV
#
# Exits after setup completes (restart: on-failure handles retries).

FROM python:3.13-slim

WORKDIR /app

# Only dependency is httpx for Vault API calls
RUN pip install --no-cache-dir httpx==0.28.1

COPY setup_vault.py .
RUN chmod +x setup_vault.py

CMD ["python", "setup_vault.py"]
