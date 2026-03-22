# Dockerfile for the FastAPI API service
# This Dockerfile sets up the Python environment, copies the application code,
# and prepares the container to run the Uvicorn server.

FROM python:3.13-slim

# Set the working directory in the container
# PYTHONPATH will be set to /app, and the 'backend' module will reside in /app/backend
WORKDIR /app

# Install system dependencies required by the application
# git is needed for installing packages from GitHub (e.g., toon-format)
RUN apt-get update && \
    apt-get install -y curl git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the requirements file from its location within the backend/core/api directory
# (relative to the new build context, which is the project root)
COPY backend/core/api/requirements.txt requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire 'backend' directory from the host into '/app/backend' in the image.
# This makes the 'backend' module available for import.
COPY backend /app/backend

# Create a directory for logs. The application should be configured to write logs here.
RUN mkdir -p /app/logs

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Set PYTHONPATH to /app. Python will look for modules in /app.
# Since 'backend' is copied to /app/backend, 'import backend' will work.
ENV PYTHONPATH "/app"

# Expose the port the API will run on
EXPOSE 8000

# Default command to run the application.
# This is typically overridden by the 'command' in docker-compose.yml.
# It correctly refers to the main application module path.
CMD ["uvicorn", "backend.core.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips='*'"]
