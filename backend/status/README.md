# OpenMates Status Service

Independent status service for `status.openmates.org`.

## What it does

- Monitors core platform endpoints (web app, core API, upload server, preview server)
- Persists status transitions and response times in SQLite
- Reads provider/external-service health from each core API environment's `/v1/health`
- Serves a Svelte SPA for `/` (prod) and `/dev` (dev)

## Environment variables

- `PROD_WEB_URL` (default: `https://openmates.org`)
- `PROD_API_URL` (default: `https://api.openmates.org`)
- `DEV_WEB_URL` (default: `https://dev.openmates.org`)
- `DEV_API_URL` (default: `https://api.dev.openmates.org`)
- `UPLOAD_URL` (required for upload checks)
- `PREVIEW_URL` (required for preview checks)
- `STATUS_CHECK_INTERVAL_SECONDS` (default: `60`)
- `STATUS_DB_PATH` (default: `/app/data/status.db`)

## Run

```bash
docker compose -f backend/status/docker-compose.yml up -d --build
```

Then proxy your domain to `localhost:8000` (see `deployment/status_server/Caddyfile`).
