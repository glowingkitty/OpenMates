# Chatbot System Architecture Design Guide

## Overview
This document provides comprehensive instructions for building a modular, maintainable, and scalable architecture for a chatbot platform with extensible app functionality. The system is designed with Docker Compose for deployment flexibility, focusing on security, performance, and maintainability.

## Project Structure

```
my-chatbot-platform/
├── start-server.sh               # Server initialization script
├── frontend/                     # Frontend applications
│   ├── web-app/                  # Main web application (chatbot interface)
│   ├── website/                  # Marketing/landing pages
│   │   └── docs/                 # API documentation (auto-generated)
│   ├── packages/
│   │   └── ui/                   # Shared UI components and assets
│   └── vscode-plugin/            # VS Code extension (future)
│
├── backend/
│   ├── core/                     # Core services
│   │   ├── core.docker-compose.yml
│   │   ├── api/                  # Main FastAPI service
│   │   │   ├── routers/          # API route definitions
│   │   │   │   ├── auth.py       # Authentication endpoints
│   │   │   │   ├── chat.py       # Chat endpoints
│   │   │   │   ├── settings.py   # Settings endpoints
│   │   │   │   └── admin.py      # Admin endpoints
│   │   │   ├── models/           # Pydantic models/schemas
│   │   │   │   ├── user.py       # User models
│   │   │   │   ├── chat.py       # Chat models
│   │   │   │   └── settings.py   # Settings models
│   │   │   ├── services/         # Business logic
│   │   │   │   ├── auth.py       # Authentication service
│   │   │   │   ├── chat.py       # Chat processing service
│   │   │   │   └── preprocessing.py # Request preprocessing logic
│   │   │   ├── middleware/       # API middleware (rate limiting, etc.)
│   │   │   ├── tests/            # Unit tests (pytest)
│   │   │   ├── utils/            # Utility functions
│   │   │   ├── config.py         # Configuration management
│   │   │   ├── main.py           # FastAPI application entry point
│   │   │   └── dependencies.py   # Auth & permission checks
│   │   ├── email-renderer/         # New Node.js service for email rendering
│   │   │   ├── templates/          # Svelte email components
│   │   │   │   ├── welcome.svelte  # Email templates as Svelte components
│   │   │   │   ├── invoice.svelte
│   │   │   │   └── notification.svelte
│   │   │   ├── server.js           # Express server to handle render requests
│   │   │   ├── renderer.js         # Svelte-email integration
│   │   │   ├── Dockerfile
│   │   │   └── package.json        # With svelte-email dependency
│   │   ├── directus/             # Database management
│   │   │   ├── schemas/          # Directus YML schema definitions
│   │   │   ├── backups/          # Database backup files
│   │   │   ├── backup.py         # Backup creation script (outputs YML)
│   │   │   └── restore.py        # Schema restoration script (inputs YML)
│   │   │
│   │   ├── celery/               # Task management
│   │   │   ├── tasks/            # Task definitions
│   │   │   └── config.py         # Celery configuration
│   │   │
│   │   ├── vault/                # Secret management
│   │   │   └── config/           # Vault configuration
│   │   │
│   │   ├── monitoring/           # Monitoring configuration
│   │   │   ├── prometheus/       # Prometheus configuration
│   │   │   └── grafana/          # Grafana dashboards
│   │   │
│   │   ├── backup/               # S3 backup service
│   │   │   └── main.py           # Backup script for S3
│   │   │
│   │   └── updater/              # Software update manager
│   │       ├── main.py           # Entry point with API
│   │       ├── docker.py         # Docker interaction functions
│   │       └── requirements.txt  # Dependencies
│   │
│   ├── apps/                     # App services
│   │   ├── apps.docker-compose.yml
│   │   ├── app_base/             # Base classes for apps
│   │   │   ├── models.py         # Base models
│   │   │   ├── router.py         # Base router
│   │   │   └── service.py        # Base service
│   │   │
│   │   ├── mysoftwarename/       # Core functionality app
│   │   │   ├── skills/           # Core skills
│   │   │   │   ├── mate.py       # Mate management skills
│   │   │   │   ├── collection.py # Collection management
│   │   │   │   └── profile.py    # User profile management
│   │   │   ├── routers/          # API routes
│   │   │   ├── models/           # Data models
│   │   │   ├── services/         # Business logic
│   │   │   └── main.py           # App entry point
│   │   │
│   │   ├── support/              # Documentation search app
│   │   │   ├── skills/           # Support skills
│   │   │   │   ├── search.py     # Documentation search
│   │   │   │   └── feedback.py   # Bug reporting
│   │   │   ├── providers/        # Doc providers
│   │   │   ├── routers/          # API routes
│   │   │   └── main.py           # App entry point
│   │   │
│   │   ├── ai/                   # AI processing app
│   │   │   ├── skills/           # AI skills
│   │   │   │   └── chat.py       # LLM interaction
│   │   │   ├── providers/        # LLM providers
│   │   │   ├── routers/          # API routes
│   │   │   └── main.py           # App entry point
│   │   │
│   │   ├── videos/               # Video processing app
│   │   │   ├── skills/           # Video skills
│   │   │   │   ├── transcript.py # Video transcription
│   │   │   │   └── search.py     # YouTube search
│   │   │   ├── providers/        # Video providers
│   │   │   ├── routers/          # API routes
│   │   │   └── main.py           # App entry point
│   │   │
│   │   ├── pdf/                  # PDF processing app
│   │   │   ├── skills/           # PDF skills
│   │   │   │   ├── extract.py    # Text extraction
│   │   │   │   └── screenshot.py # Page screenshots
│   │   │   ├── providers/        # PDF processing providers
│   │   │   ├── routers/          # API routes
│   │   │   └── main.py           # App entry point
│   │   │
│   │   ├── audio/                # Audio processing app
│   │   │   ├── skills/           # Audio skills
│   │   │   │   ├── transcribe.py # Speech-to-text
│   │   │   │   └── generate.py   # Text-to-speech
│   │   │   ├── providers/        # Audio providers
│   │   │   ├── routers/          # API routes
│   │   │   └── main.py           # App entry point
│   │   │
│   │   ├── web/                  # Web search app
│   │   │   ├── skills/           # Web skills
│   │   │   │   └── search.py     # Web search
│   │   │   ├── providers/        # Search providers
│   │   │   ├── routers/          # API routes
│   │   │   └── main.py           # App entry point
│   │   │
│   │   └── messages/             # Messaging integrations
│   │       ├── skills/           # Messaging skills
│   │       │   └── respond.py    # Message response handling
│   │       ├── providers/        # Messaging providers
│   │       │   ├── discord.py    # Discord integration
│   │       │   └── slack.py      # Slack integration
│   │       ├── listeners/        # Message listeners
│   │       │   └── discord/      # Discord bot listener
│   │       ├── routers/          # API routes
│   │       └── main.py           # App entry point
│   │
│   ├── providers/                # Self-hosted third-party services
│   │   ├── self-hosted-providers.docker-compose.yml
│   │   ├── mosquitto/            # MQTT broker
│   │   ├── penpot/               # Design tool
│   │   ├── akaunting/            # Finance management
│   │   └── plane/                # Project management
│   │
│   ├── app-store/                # App distribution system
│   │   ├── app-store.docker-compose.yml
│   │   ├── registry/             # Docker registry configuration
│   │   ├── api/                  # App store API
│   │   │   ├── routers/          # API routes
│   │   │   ├── models/           # Data models
│   │   │   └── main.py           # Entry point
│   │   └── storage/              # App metadata and assets
│   │
│   └── vscode-plugin/            # VS Code extension backend
│
└── deployment/                   # Deployment tools
    ├── ansible/                  # Ansible playbooks
    └── terraform/                # Terraform scripts
```

## Architecture Components

### Docker Compose Files
The system is built around three primary Docker Compose files:

1. **core.docker-compose.yml**: Contains essential services:
   - API service (FastAPI)
   - Email renderer (using Svelte-email / nodejs to open the email svelte files with variables and return the rendered emails as email compatible html code)
   - Directus (database/CMS)
   - Celery (task management, for longer running tasks, accessible by core and apps.docker-compose)
   - Dragonfly (caching of often used data with fast access needed)
   - Vault by Hashicorp (encryption key management)
   - Monitoring (Grafana/Prometheus)
   - Backup service (S3 Hetzner, backing up encrypted user data, invoices, etc.)
   - Updater service (allows for updating the software via git pull for latest changes & restarting (and if needed rebuilding) all updated docker containers)

2. **apps.docker-compose.yml**: Contains app-specific services:
   - Core functionality app (which are accessible to both frontend and developers via api: create mates (chatbots), download invoice, add chat to a collection, etc. - Seperate from frontend exclusive api endpoints in backend/core/api)
   - Support app
   - AI processing app
   - Videos app
   - PDF app
   - Audio app
   - Web search app
   - Messages app (for third-party integrations)
   - (Additional apps as needed)

3. **self-hosted-providers.docker-compose.yml**: Optional third-party services:
   - Mosquitto (MQTT broker)
   - Penpot (design tool)
   - Akaunting (finance management)
   - Plane (project management)
   - (Other self-hosted services)

4. **app-store.docker-compose.yml**: App distribution system:
   - Docker registry
   - App store API
   - Storage for app metadata

### Core API Service

The main FastAPI service handles:

1. **Authentication & Authorization**
   - User signup/login
   - 2FA management
   - Token handling
   - Permission checks
   - API key management

2. **Request Processing**
   - Incoming request validation
   - Credit checking
   - Rate limiting
   - Request preprocessing
   - Routing to appropriate app services
   - Response handling and encryption

3. **Admin Functions**
   - User management
   - System settings
   - Software updates
   - App installation/management

### App System

The app system follows a modular architecture where:

1. Each app is a separate Docker container with:
   - Defined "skills" (API endpoints)
   - Provider implementations (where applicable)
   - Standardized structure for consistency

2. Apps expose skills like:
   - Generate audio (/v1/audio/generate)
   - Search the web (/v1/web/search)
   - Process PDF (/v1/pdf/extract)
   - Transcribe video (/v1/videos/transcript)
   - Manage mates (/v1/mysoftwarename/mate/create)
   - Handle third-party messages (/v1/messages/respond)

3. The main API routes requests to appropriate app skills based on:
   - Direct API calls
   - AI app recommendations

### App Store System

The app store allows:

1. Server admins to browse and install approved apps
2. Containerized apps to be easily deployed
3. Docker images to be pulled from a private registry
4. Custom app configuration for server needs

### Data Flow

1. **Request Processing Flow**:
   - User sends request via frontend or API
   - API performs auth/validation/credit checks
   - Request is preprocessed (legality, topic identification, difficulty)
   - For chat messages, AI app determines required skills
   - API routes to appropriate app services
   - Results are returned, credits charged, encrypted data stored

2. **App Installation Flow**:
   - Admin selects apps via web interface
   - API forwards request to updater service
   - Updater modifies apps.docker-compose.yml
   - Images are pulled from the app store registry
   - New containers are started
   - Apps register capabilities with the core API

### Security Considerations

1. **Data Encryption**:
   - All user data encrypted before storage
   - Encryption keys managed by Vault
   - Separate authorization for different API endpoints

2. **API Security**:
   - Rate limiting for all endpoints
   - Domain restrictions for frontend-exclusive endpoints
   - API key management for developer access
   - Input validation and sanitization

### Monitoring and Maintenance

1. **Monitoring Stack**:
   - Prometheus for metrics collection
   - Grafana for dashboards
   - Custom UI integration for admin visibility

2. **Backup System**:
   - Regular database schema exports to YML
   - Encrypted backups to Hetzner S3
   - User uploads stored directly in S3
   - Configuration backups

3. **Update System**:
   - Separate updater container with Docker socket access
   - Safe update procedures with rollback
   - App installation/removal management

### Server Initialization Script

The `start-server.sh` script handles the sequential startup of services to ensure proper system initialization:

1. **Sequential Service Startup:**
   - Starts the Directus container first
   - Waits for Directus to become healthy
   - Checks if database schema is already initialized

2. **First-Time Setup:**
   - When first run, automatically imports schema from YML definitions
   - Generates a secure invite code for the first administrator
   - Stores this invite code in Directus for the web application

3. **Service Coordination:**
   - Starts remaining core services after Directus is ready
   - Launches app services after core services are running
   - Handles dependency order between services

4. **User Onboarding:**
   - Displays setup instructions when initialization is complete
   - Provides the URL for accessing the web application
   - Explains how the first user will become the administrator

This approach separates technical Directus administration from application user management while ensuring all components start in the correct order.


## Implementation Guidelines

### FastAPI Implementation

Follow these practices:
- Organize code with routers for endpoint grouping
- Use Pydantic models for request/response validation
- Implement business logic in service classes
- Use dependencies.py for reusable auth checks
- Write unit tests with pytest

### App Development

When creating new apps:
- Inherit from app_base classes
- Define clear skills with standardized interfaces
- Separate provider implementations
- Follow consistent directory structure
- Document API endpoints for auto-generation

### Database Management

For Directus:
- Store schema definitions as YML files
- Use backup.py to export models regularly
- Use restore.py for migrations and restores
- Keep encryption keys separate from data

### Directus Database Models

Initial database models should include:

1. **users**
   - Basic user information and authentication
   - Credit balances
   - Preferences

2. **mates**
   - AI assistants configuration
   - System prompts
   - User-specific settings

3. **usage**
   - Credit consumption records
   - Feature usage tracking
   - Billing information

4. **chats**
   - Message history (encrypted)
   - Chat metadata
   - Collections/folders

5. **apps**
   - Installed app records
   - App configurations
   - Version information

6. **skills**
   - Available skill definitions
   - App associations
   - Permission requirements

7. **providers**
   - External service connections
   - API credentials (encrypted)
   - Usage constraints

### Deployment

Use provided tools:
- Ansible playbooks for server configuration
- Terraform scripts for infrastructure management
- Docker Compose for service orchestration

## API Endpoints

The system will include these key endpoints:

### Authentication
- `/v1/auth/check_invite_token_valid`
- `/v1/auth/check_username_valid`
- `/v1/auth/signup`
- `/v1/auth/verify_email_code`
- `/v1/auth/setup_2fa`
- `/v1/auth/login`
- `/v1/auth/refresh`
- `/v1/auth/logout`

### Chat
- `/v1/chat/message`
- `/v1/chat/cancel`
- `/v1/chat/delete_message`
- `/v1/chat/delete`

### Settings
- `/v1/settings/user/update_profile_image`
- `/v1/settings/software_update/check`
- `/v1/settings/software_update/install`
- `/v1/settings/software_update/install_status`

### App-specific Endpoints (Examples)
- `/v1/mysoftwarename/mate/create`
- `/v1/mysoftwarename/collection/add_chat`
- `/v1/support/search` 
- `/v1/ai/chat`
- `/v1/videos/transcript`
- `/v1/videos/search`
- `/v1/pdf/extract`
- `/v1/pdf/screenshot`
- `/v1/audio/transcribe`
- `/v1/audio/generate`
- `/v1/web/search`
- `/v1/messages/respond`

## Configuration Management

1. **Secrets**: Managed via environment variables in .env files
2. **Configuration**: Managed via YAML files
3. **Directus Schemas**: Stored as YML files

## Extension Strategy

The architecture is designed for extensibility:
- New apps can be added without modifying core code
- Self-hosted providers can be added as needed
- Third-party messaging platforms can be integrated via the messages app
- Frontend can be extended with VS Code plugin

This architecture provides a comprehensive foundation for building a flexible, secure, and maintainable chatbot platform with modular app functionality.



## Implementation Guidelines

### FastAPI Implementation

Follow these practices:
- Organize code with routers for endpoint grouping (separate files by feature area)
- Use Pydantic models for request/response validation
- Implement business logic in service classes
- Use dependencies.py for reusable auth checks
- Write unit tests with pytest
- Implement API security using:
  - FastAPI Depends for authentication and authorization checks
  - Rate limiting middleware to prevent abuse
  - Consistent error handling with proper status codes

### API Gateway Pattern Implementation

The core API service will function as an API gateway with these characteristics:
- **Request Routing**: Direct requests to appropriate app services
- **Authentication**: Validate tokens before forwarding requests
- **Rate Limiting**: Apply consistent rate limits across all endpoints
- **Request/Response Transformation**: Transform data formats as needed
- **Circuit Breakers**: Prevent cascading failures when app services fail

### Resilience Patterns

1. **Circuit Breakers**:
   - Implement circuit breakers for calls to app services
   - When a service fails repeatedly, "open" the circuit and return cached/fallback responses
   - After cool-down period, "half-open" to test if service has recovered
   - Example use cases:
     - External API calls to LLM providers
     - Calls between core API and app services
     - Database operations when appropriate

   ```python
   # Example circuit breaker implementation
   @circuit_breaker(fail_threshold=5, recovery_time=30)
   async def call_ai_service(prompt: str):
       return await ai_service_client.complete(prompt)
   ```

### Logging System

All services should implement standardized structured logging:

1. **Log Format**:
   - JSON format for machine readability
   - Consistent fields across all services:
     - `timestamp`
     - `service_name`
     - `trace_id` (for request tracking)
     - `level` (INFO, WARNING, ERROR, DEBUG)
     - `message`
     - `context` (additional data)

- all logs are saved in grafana, from all dockers!
- grafana dashboards include access to:
  - number of monthly active users
  - number of new signups this month
  - income (payments) this month

### Kubernetes Compatibility

To ensure future compatibility with Kubernetes:

1. **Stateless Services**:
   - Design services to function without relying on local state
   - Store all persistent data in the database or external storage
   - Example: Don't store user session data in memory; use Redis/database instead

2. **Health Checks**:
   - Implement `/health` endpoints in all services
   - Return service status and dependency health
   
   ```python
   @app.get("/health")
   async def health_check():
       """Health check endpoint for Kubernetes liveness probe"""
       # Check database connectivity
       db_healthy = await check_database_connection()
       # Check other dependencies
       cache_healthy = await check_cache_connection()
       
       if not db_healthy or not cache_healthy:
           return JSONResponse(
               status_code=503,
               content={"status": "unhealthy", "db": db_healthy, "cache": cache_healthy}
           )
       
       return {"status": "healthy"}
   ```

3. **Container Configuration**:
   - Use environment variables consistently
   - Avoid host-specific volume mounts
   - Design for horizontal scaling

## API Endpoints

### Payment Processing (Revolut Business)

- `/v1/payment/create` - Create payment order and return checkout URL
- `/v1/payment/check/{payment_id}` - Check payment status
- `/v1/payment/webhook` - Receive payment notifications
- `/v1/payment/history` - Retrieve payment history

with the payments users can buy credits, which are needed for using apps (AI, and most other apps).


# Additional comments / requirements
- backend/core/api also includes code for sending emails (via brevo) & generating pdf invoices (via ReportLab)
- using directus user model for creating users, resetting password, etc.
- every chat is encrypted with its own key, so the chat can also be shared with others or publically without risking the security of other chats
- use best practices for readable, commented, maintainable, efficient, secure code
- on first start of start-server.sh:
  - setup directus & directus admin
  - then other services will also start
  - invite code in directus will be generated to allow for web app admin user to be created via web app
  - first user using that invite code will also become web app admin and can manage server via web app (seperate from directus admin)