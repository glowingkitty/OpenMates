# Backend Core API

This directory contains the core components of the OpenMates REST API service.

## Directory Structure:

-   **`app/`**: Contains the main FastAPI application logic.
    -   **`middleware/`**: Custom middleware for the FastAPI application (e.g., logging).
    -   **`models/`**: Pydantic models or database models (if applicable, though most seem to be in `schemas`).
    -   **`routes/`**: API endpoint definitions (routers).
    -   **`schemas/`**: Pydantic schemas for request/response validation and serialization.
    -   **`services/`**: Business logic and integrations with external services (e.g., Directus, Cache, S3, Email).
    -   **`tasks/`**: Celery task definitions for asynchronous operations.
    -   **`utils/`**: Utility functions and helper modules (e.g., configuration management, encryption, logging setup).
-   **`templates/`**: Email templates (e.g., MJML files).
-   **`Dockerfile`**: Defines the Docker image for the REST API service.
-   **`Dockerfile.celery`**: Defines the Docker image for the Celery workers.
-   **`main.py`**: The main entry point for the FastAPI application, including application setup, middleware, and router inclusion.
-   **`requirements.txt`**: Python package dependencies for the API and Celery workers.
-   **`wait-for-vault.sh`**: A script likely used to ensure HashiCorp Vault is available before starting the main application.

## Overview:

The API is built using FastAPI and serves as the primary backend interface for the OpenMates platform. It handles authentication, data management (via services like Directus), payment processing, real-time communication (WebSockets), and various other backend functionalities.

It integrates with several other services defined in the Docker Compose setup, including:
-   CMS (Directus)
-   Cache (Dragonfly/Redis)
-   Task Queues (Celery)
-   Secret Management (Vault)
-   Monitoring (Prometheus, Grafana, Loki)

The API service and Celery workers share common code, particularly schemas (from `../../shared/python_schemas`, aliased as `backend_shared` within the application) and potentially some utility functions.