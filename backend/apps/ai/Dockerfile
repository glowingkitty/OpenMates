# backend/apps/ai/Dockerfile
# Dockerfile for the AI Application

FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements.txt from the core API directory.
# This assumes the AI app shares the same core dependencies.
# For a more isolated app, it would have its own requirements.txt.
COPY backend/core/api/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the base app and skill files from the parent 'apps' directory
# These will be placed in an 'apps' subdirectory within /app,
# allowing imports like 'from apps.base_app import BaseApp'.
COPY backend/apps/base_app.py /app/apps/base_app.py
COPY backend/apps/base_skill.py /app/apps/base_skill.py
# If there are other shared files in backend/apps/ that base_app or base_skill might need,
# they should also be copied here. For now, just these two.
# Create an __init__.py for the 'apps' package if it's treated as a package
RUN mkdir -p /app/apps && touch /app/apps/__init__.py

# Copy shared Python schemas from backend/shared/
# Source path is relative to the project root build context
COPY backend/shared/python_schemas /app/backend_shared/python_schemas


# Copy the AI app's specific code into a subdirectory 'ai' within /app
# This makes the AI app's modules importable as 'ai.module_name'
# Source path is relative to the project root build context
COPY backend/apps/ai/ /app/ai/

# Create a directory for logs if the app writes any
RUN mkdir -p /app/ai/logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH="/app"
# AI_APP_INTERNAL_PORT is used by ai/app.py to determine the listening port.
# It should match the EXPOSE directive and the port used in docker-compose.
ENV AI_APP_INTERNAL_PORT=8000

EXPOSE 8000

# Command to run the AI application
# It refers to the 'app' instance within /app/ai/app.py
CMD ["uvicorn", "ai.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips='*'"]