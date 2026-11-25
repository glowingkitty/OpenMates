# Container user inventory

Baseline on 25 November 2026. Dev entries with a numeric process UID came from
`docker inspect` and `docker top` on the running dev stack. Production, upload,
preview and self-host entries describe the tracked Compose manifests and image
recipes. Upstream defaults for images absent from dev come from their registry
image configuration. Confirm the deployed digests and process UIDs during the
normal release. Root in this inventory means UID 0 inside the container.

## OpenMates images

| Dockerfile | Where used | Baseline startup and service user |
| --- | --- | --- |
| `backend/core/api/Dockerfile` | Dev and production source-build API, isolated CI API and helper jobs | Root at startup and in Uvicorn on dev. Check the Vault handoff, logs, recommendation data and dev bind mounts. |
| `backend/core/api/Dockerfile.selfhost` | Published self-host API and standard workers | API starts as root. Worker Compose sets root for startup before dropping to the Celery account. |
| `backend/core/api/Dockerfile.celery` | Source-build workers and scheduler | Image defaults to `celeryuser`. Dev worker services override root for startup, then run Python at UID 1000. Scheduler starts at UID 1000. |
| `backend/core/api/Dockerfile.docs` | Source-build docs worker | Image defaults to `celeryuser`. Dev overrides root for startup, then runs Python at UID 1000. |
| `backend/core/api/Dockerfile.docs.selfhost` | Published docs worker | Image defaults to `celeryuser`. Verify the inherited worker Compose settings during release. |
| `backend/core/directus/Dockerfile` | CMS in core, self-host and isolated CI | Starts as root to fix the upload directory owner, then runs Directus at UID 1000 on dev. |
| `backend/core/directus/setup/Dockerfile` | One-shot CMS setup in source-build core and isolated CI | Root. Reads mounted SQL and schema files and talks to CMS and Postgres. |
| `backend/core/directus/Dockerfile.setup.selfhost` | Published one-shot CMS setup | Root. Schema and migrations ship in the image. |
| `backend/core/vault/setup/Dockerfile` | One-shot Vault setup in core and self-host | Root. The setup writes the private Vault handoff volume and may update a mounted dotenv file. |
| `backend/upload/Dockerfile` | Upload source-build, self-host and isolated CI | Root. Reads a private Vault token handoff and serves port 8000. |
| `backend/upload/vault/Dockerfile` | One-shot Vault setup for upload and self-host | Root. Writes the private upload Vault handoff volume. |
| `backend/preview/Dockerfile` | Preview source-build and self-host | `preview` (UID 1000). Cache volume needs to be writable by that account. Serves port 8080. |
| `backend/admin_sidecar/Dockerfile` | Core, upload and preview maintenance | Root in the image. Docker socket group and checkout access need verification in all three manifests. Docker socket access conveys host Docker authority independently of the sidecar UID. |
| `frontend/apps/web_app/Dockerfile` | Docker core/self-host frontend | Root in the serving stage. Serves static assets on port 5173. |
| `backend/engineering_control_plane/Dockerfile` | Dev engineering control plane API | Python runs as root on dev. The separate Compose service has no application volume. |
| `backend/status/Dockerfile` | Legacy standalone status app, never deployed | Root. SQLite is on a named volume under `/app/data`. |
| `deployment/status_server/Dockerfile` | Published status server | `status` (UID 10001). Gatus listens on 8080 and Caddy uses `CAP_NET_BIND_SERVICE` for 80 and 443. |
| `scripts/ci_schema_image.Dockerfile` | Published Postgres schema carrier for isolated CI | Inherits root startup from Postgres, which then drops to the Postgres account. |
| `openmates-ci-formula-worker:local` | Optional isolated formula-worker test profile | Compose specifies UID/GID 65532, a read-only filesystem and no added capabilities. The profile references a formula-worker recipe absent from the baseline checkout. |

## Upstream runtime images

| Image | Where used | Baseline |
| --- | --- | --- |
| `postgres:13-alpine`, `postgres:16-alpine` | Core CMS, isolated CI and engineering control plane | Image defaults to root for initialization. Dev Postgres processes run at UID 70. |
| `hashicorp/vault:1.19` | Core, upload, self-host and isolated CI | On dev, root entrypoint remains as PID 1 and Vault runs at UID 100. Verify the data directory and memory-lock capability before changing the entrypoint UID. |
| `docker.dragonflydb.io/dragonflydb/dragonfly` | Core cache and self-host | On dev, root tini remains PID 1 and Dragonfly runs at UID 999. Verify the cache volume before changing startup UID. |
| `public.ecr.aws/zinclabs/openobserve:v0.70.0-rc3` | Core monitoring and self-host | Root startup and process on dev. Uses a persistent data volume. |
| `grafana/promtail:3.4.2` / `:3.2.1` | Core log collection and self-host | Root process on dev. Reads Docker logs via the socket and reads the API log bind mount. |
| `prom/prometheus:v3.2.1`, `prom/node-exporter:v1.9.1`, `prom/alertmanager:v0.31.1` / `:v0.33.1` | Core and self-host monitoring | Upstream non-root defaults. Verify host mount readability for node exporter and volume ownership for Prometheus before restarting. |
| `gcr.io/cadvisor/cadvisor:v0.47.2` / `:v0.49.1` | Core and self-host monitoring | Root/privileged host collector in tracked configuration. Requires access to host cgroups, devices and container statistics. |
| `python:3.13-slim` | Core App Packages runner | Compose overrides the base root user with UID/GID 65534. Confirmed on dev. |
| `clamav/clamav-debian` | Upload and isolated CI | Root startup. The init process prepares signature storage. Confirm the daemon UID for the deployed digest during release. |
| `redis:7-alpine` | Isolated CI cache | Image starts as root and the Redis entrypoint drops privileges. |
| `axllent/mailpit:v1.27.4`, `chrislusf/seaweedfs` | Isolated CI mail and object storage fixtures | Both images default to root and the CI Compose profile uses that default. |
| `mcr.microsoft.com/playwright:v1.49.0-jammy` | Legacy standalone Playwright Compose | Root image default. |
| `amazon/aws-cli:2.27.50` | Production backup transport | Root image default. Runs as a short-lived command. Backup and restore drill also reuse Vault and Postgres; the Vault file archive helper needs direct access to the private files and the restore helper preserves their ownership. |
| `aquasec/trivy` | Dev security scanner | Root image default. Mounted source scans need read-only access. |

The Python and Node base images and the status server's Gatus and Caddy build
stages supply binaries or build dependencies. The rows above record the final
stage that runs in each environment.

## Verified changes

- CI schema carrier, dev commits `6e3fe61` and `ef9727d`. The pinned Postgres
  base restored a compressed SQL fixture in a fresh local volume as UID/GID 70.
  The CI publisher passed both clean restore checks after the CI database
  mount allowed Docker to inherit the image's empty, Postgres-owned directory.
  [Publisher run](https://github.com/glowingkitty/OpenMates/actions/runs/45585889954).
- Engineering control plane API, Dockerfile in dev commit `8de5100`. All 34
  control-plane tests passed. The recreated live container has a single
  UID 10001 process and reports database readiness with no writable application
  volume. The dev rollout reused the cached image and enforced the new UID
  through Compose in dev commit `504c3f7`.
- Engineering control plane PostgreSQL starts as `postgres` (UID/GID 70).
  A disposable database initialized and passed a SQL write/read with the
  same image and UID. The live PostgreSQL container restarted with its existing
  volume and both PostgreSQL and the engineering API returned to healthy
  (dev commit `2d8bd4b`).
- Directus, dev commit `98e2e3b`. All 29 runtime verifier tests passed.
  Dev reused its cached image with Compose running the startup script as
  `node`. Docker reports a healthy container, UID 1000 for each CMS process
  and a writable existing upload directory. The API health endpoint returned
  HTTP 200.
- Core Postgres, dev commit `086b8be`. All generated Compose manifests retain
  the existing data volume. The dev database reports healthy and its
  processes run as UID/GID 70. Directus reported healthy and API health
  returned HTTP 200 after recreation.
- Docker web app. The published dev image served its static application on
  port 5173 with UID/GID 1000 in a network-isolated dev smoke. The Dockerfile
  now sets the same user by default (dev commit `365cc0d`).
- Preview was already non-root. The published dev image started with its
  default user, ran all processes as UID 1000, returned HTTP 200 on port 8080
  and could write to a fresh cache volume. This used a disposable dev container.
- Source-built CMS setup. UID/GID 10002 read the mounted schema and migration
  files with a read-only filesystem. The setup process exited successfully on
  a restored disposable schema and Directus health passed. A separate empty
  database run reached schema writes before the local time limit. The focused
  mount test passed. Two unrelated permission-matrix assertions already
  failed on the unchanged baseline.
