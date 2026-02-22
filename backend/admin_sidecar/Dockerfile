# backend/admin_sidecar/Dockerfile
#
# Admin Sidecar container image.
#
# This is a minimal container that runs the admin sidecar FastAPI app.
# It needs:
#   - Python + FastAPI/uvicorn (the web framework)
#   - Docker CLI (to run `docker compose logs` and `docker compose build/up`)
#   - Git (to run `git pull`)
#
# The Docker socket is mounted at runtime (not baked in):
#   volumes:
#     - /var/run/docker.sock:/var/run/docker.sock
#   group_add:
#     - <docker-group-gid>
#
# This container intentionally has NO access to user data, S3, Vault, ClamAV,
# or any other sensitive service. Its only capabilities are:
#   - Read Docker logs
#   - Trigger a rebuild and restart of a specified service
#   - Respond to health checks
#
# Build context: project root (so Dockerfile can COPY backend/admin_sidecar/)

FROM python:3.12-slim

# Install Docker CLI and git — the only system-level tools this container needs.
# docker-ce-cli provides the `docker` binary and compose plugin.
# curl is included for the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        git \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/debian \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        docker-ce-cli \
        docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (fastapi + uvicorn only)
COPY backend/admin_sidecar/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the sidecar app code — nothing from the main service
COPY backend/admin_sidecar/main.py .

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
