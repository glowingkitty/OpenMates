# backend/upload/Dockerfile
#
# Dedicated Dockerfile for the uploads microservice.
# Unlike other app services that use Dockerfile.base, uploads needs additional
# system-level dependencies:
#   - libclamd-dev / libclamav-dev: Not needed since we use the daemon via TCP socket
#   - libmagic1: For python-magic MIME type detection (finfo)
#   - libjpeg-dev, libpng-dev, libwebp-dev: For Pillow image processing
#
# ClamAV scanning is handled by a separate 'clamav' service container;
# this container communicates with it over TCP (pyclamd socket client).

FROM python:3.13-slim

WORKDIR /app

# Install system dependencies required by Pillow and python-magic
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        libmagic1 \
        libjpeg-dev \
        libpng-dev \
        libwebp-dev \
        zlib1g-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python requirements (uploads-specific superset of core requirements)
COPY backend/upload/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared backend framework code (same as Dockerfile.base)
COPY backend/apps/base_app.py /app/apps/base_app.py
COPY backend/apps/base_skill.py /app/apps/base_skill.py
COPY backend/apps/base_main.py /app/base_main.py
RUN mkdir -p /app/apps && touch /app/apps/__init__.py

# Copy shared Python schemas and utilities
COPY backend/shared/python_schemas /app/backend_shared/python_schemas
COPY backend/shared/python_utils /app/backend_shared/python_utils

# Copy the uploads app code
# Must live at /app/backend/upload/ so that `from backend.upload.*` imports resolve
# with PYTHONPATH=/app.
RUN mkdir -p /app/backend && touch /app/backend/__init__.py
COPY backend/upload/ /app/backend/upload/

# Copy the startup script that waits for the Vault API token before starting uvicorn.
# Mirrors the wait-for-vault.sh pattern used by the core API.
COPY backend/upload/vault/wait-for-vault.sh /app/wait-for-vault.sh
RUN chmod +x /app/wait-for-vault.sh

# Set common environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH="/app"

EXPOSE 8000

# Wait for vault-setup to write the API token, then start uvicorn.
CMD ["/app/wait-for-vault.sh"]
