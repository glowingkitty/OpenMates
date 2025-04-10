# Architecture Guidelines

## Table of Contents

- [Architecture Guidelines](#architecture-guidelines)
  - [Table of Contents](#table-of-contents)
  - [Development Environment](#development-environment)
    - [Service Exposure (Development)](#service-exposure-development)
    - [Details (Development)](#details-development)
  - [Production Environment](#production-environment)
    - [Service Exposure (Production)](#service-exposure-production)
    - [Details (Production)](#details-production)
  - [Frontend Components](#frontend-components)
  - [Future Architecture (Apps)](#future-architecture-apps)

## Development Environment

This environment runs the **backend stack** locally using Docker Compose (`docker-compose.yml` + `docker-compose.override.yml`) on a single machine (e.g., the Hetzner ARM server or a developer's machine). Several backend services are exposed directly on the host, allowing for easier local access during development and direct API testing. **Frontend development primarily utilizes Vercel Preview Deployments.**

### Service Exposure (Development)

| Service Name      | Purpose                                      | Exposed to Internet? | Default Port (Host) | Notes                                       |
| :---------------- | :------------------------------------------- | :--------------- | :------------------ | :------------------------------------------ |
| `api`             | FastAPI Backend                              | Yes              | `${REST_API_PORT}`  | Main API endpoint                           |
| `cms`             | Directus CMS                                 | Yes              | `${CMS_PORT:-8055}` | Exposed via override file                   |
| `grafana`         | Visualization Dashboard                      | Yes              | `3001`              | Exposed via override file (maps to 3000)    |
| `cms-database`    | Postgres DB for Directus                     | No               | -                   | Internal network only                       |
| `cache`           | Dragonfly Cache (Redis compatible)           | No               | -                   | Internal network only                       |
| `vault`           | HashiCorp Vault Secrets                      | No               | -                   | Internal network only                       |
| `task-worker`     | Celery Worker                                | No               | -                   | Internal network only                       |
| `task-scheduler`  | Celery Beat Scheduler                        | No               | -                   | Internal network only                       |
| `prometheus`      | Metrics Collection                           | No               | -                   | Internal network only                       |
| `loki`            | Log Aggregation                              | No               | -                   | Internal network only                       |
| `promtail`        | Log Shipper                                  | No               | -                   | Internal network only                       |
| `cadvisor`        | Container Metrics Exporter                   | No               | -                   | Internal network only                       |
| `vault-setup`     | *Temporary:* Initializes Vault               | No               | -                   | Runs once                                   |
| `cms-setup`       | *Temporary:* Configures Directus             | No               | -                   | Runs once                                   |

### Details (Development)

*   **Setup:** Runs using `docker-compose.yml` and `docker-compose.override.yml`. All services communicate over the `openmates` Docker network.
*   **Server:** Typically a single machine (Hetzner ARM server or local dev machine).
*   **Frontend:** Svelte Website/Web App development primarily uses **Vercel Preview Deployments**, automatically built and deployed from the `dev` branch. Developers may still run local dev servers (e.g., `vite`) for immediate feedback, communicating with the exposed `api` service on the dev machine.
*   **Core Services:**
    *   `api`: Main entry point, connects to `cache`, `vault`, `cms`.
    *   `cms`: Content management, connects to `cms-database`, `cache`, `vault`. Exposed for direct access.
    *   `cms-database`: Internal Postgres DB for `cms`.
    *   `cache`: Internal Dragonfly cache used by `api`, `cms`, and Celery.
    *   `vault`: Secrets management, accessed internally by services. Initialized by `vault-setup`.
*   **Task Queue:**
    *   `task-worker` / `task-scheduler`: Internal Celery services using `cache` as broker/backend.
*   **Monitoring:**
    *   `prometheus`, `loki`, `promtail`, `cadvisor`: Internal services for metrics and logging.
    *   `grafana`: Exposed for viewing dashboards. Connects internally to `prometheus` and `loki`.
*   **Exposure:** `api`, `cms`, and `grafana` ports are mapped to the host machine. This allows direct local access for development and testing (e.g., connecting a local `vite` instance or using API tools). Internet access for these services in dev depends on the host's reverse proxy configuration.

## Production Environment

This environment clearly separates concerns: the **backend stack runs exclusively on a dedicated server** (Hetzner ARM) using Docker Compose (`docker-compose.yml` only), while the **frontend (Website and Web App) runs exclusively on Vercel**. Only the main backend API is exposed to the internet via a reverse proxy on the Hetzner server.

### Service Exposure (Production)

| Service Name      | Purpose                                      | Exposed to Internet? | Notes                                                            |
| :---------------- | :------------------------------------------- | :------------------- | :--------------------------------------------------------------- |
| `api`             | FastAPI Backend                              | **Yes (via Proxy)**  | The *only* service intended for public access, via Reverse Proxy |
| `cms`             | Directus CMS                                 | No                   | Internal network only                                            |
| `grafana`         | Visualization Dashboard                      | No                   | Internal network only                                            |
| `cms-database`    | Postgres DB for Directus                     | No                   | Internal network only                                            |
| `cache`           | Dragonfly Cache (Redis compatible)           | No                   | Internal network only                                            |
| `vault`           | HashiCorp Vault Secrets                      | No                   | Internal network only                                            |
| `task-worker`     | Celery Worker                                | No                   | Internal network only                                            |
| `task-scheduler`  | Celery Beat Scheduler                        | No                   | Internal network only                                            |
| `prometheus`      | Metrics Collection                           | No                   | Internal network only                                            |
| `loki`            | Log Aggregation                              | No                   | Internal network only                                            |
| `promtail`        | Log Shipper                                  | No                   | Internal network only                                            |
| `cadvisor`        | Container Metrics Exporter                   | No                   | Internal network only                                            |
| `vault-setup`     | *Temporary:* Initializes Vault               | No                   | Runs once                                                        |
| `cms-setup`       | *Temporary:* Configures Directus             | No                   | Runs once                                                        |

### Details (Production)

*   **Setup:** Runs using only `docker-compose.yml` on the Hetzner ARM server. A reverse proxy (e.g., Caddy, Traefik) runs on the host, managing public access.
*   **Backend Server:** Dedicated Hetzner ARM server (8GB RAM).
*   **Frontend Hosting:** Vercel exclusively hosts the Svelte Website and Web App for both production (`main` branch) and preview (`dev` branch) environments.
    *   **Deployment:** Vercel automatically deploys the `main` branch to Production and the `dev` branch to Preview upon pushes to the respective branches.
*   **Exposure:**
    *   The reverse proxy on the host directs external traffic **only** to the `api` service's container port (`${REST_API_PORT}`).
    *   All other services (`cms`, `cms-database`, `cache`, `vault`, Celery, Monitoring stack) are **not** publicly accessible and run only within the internal Docker network.
    *   Access to internal tools like `grafana` or `vault` requires secure methods (SSH tunnel, bastion host).
*   **Communication:**
    *   Vercel-hosted frontends and external API clients communicate with the backend via the reverse proxy, hitting the `api` service.
    *   `api` interacts with other backend services (`cms`, `cache`, `vault`, Celery via `cache`) over the internal Docker network.
    *   Monitoring tools operate entirely internally.

## Frontend Components

*   **Website:** Svelte-based application for public information. Hosted on Vercel in production.
*   **Web App:** Svelte-based application for core user functionality (chat, etc.). Hosted on Vercel in production. Communicates extensively with the `api` backend service.

## Future Architecture (Apps)

*   **Concept:** Extend functionality through modular "Apps".
*   **Deployment:** Each App runs as a separate Docker container, likely managed within Docker Compose.
*   **Technology:** Each App container likely runs its own FastAPI service.
*   **Functionality:** Apps expose specific "Skills" or "Focus Modes" via internal API endpoints.
*   **Interaction:** The main `api` gateway routes relevant requests to the appropriate App container over the internal Docker network.
