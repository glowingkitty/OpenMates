# External Integrations

**Analysis Date:** 2026-03-26

## AI Model Providers

All LLM provider clients live in `backend/apps/ai/llm_providers/`. Keys retrieved from Vault via `SecretsManager`.

**Direct API integrations:**
- **OpenAI** — GPT models via `openai` SDK (`openai_client.py`). Vault path: `kv/data/providers/openai`
- **Anthropic** — Claude models via `anthropic` SDK (`anthropic_client.py`). Vault path: `kv/data/providers/anthropic`
- **Google Gemini** — via `google-genai` SDK (`google_client.py`). Also used for image generation in `backend/apps/images/`. Vault path: `kv/data/providers/google`
- **Groq** — via `groq` SDK (`groq_client.py`). Vault path: `kv/data/providers/groq`
- **Mistral AI** — direct HTTP to `https://api.mistral.ai/v1` (`mistral_client.py`). Vault path: `kv/data/providers/mistral`
- **Together AI** — OpenAI-compatible endpoint (`together_wrapper.py`). Vault path: `kv/data/providers/together`
- **Cerebras** — OpenAI-compatible endpoint via `httpx` (`cerebras_client.py`)
- **OpenRouter** — OpenAI-compatible aggregator (`openrouter_client.py`, `openai_openrouter.py`). Vault path: `kv/data/providers/openrouter`
- **AWS Bedrock** — Converse API via `boto3` (`bedrock_client.py`). Supports Claude, Mistral, Llama, Cohere on Bedrock. AWS credentials from Vault
- **Google Vertex AI MaaS** — OpenAI-compatible endpoint for DeepSeek, Qwen, Llama etc. (`google_maas_client.py`)

## Image Generation Providers

Configured in `backend/apps/images/skills/generate_skill.py`:
- **Recraft** — SVG and raster image generation via `backend/shared/providers/recraft/recraft.py`. Models: `recraftv4_vector`, `recraftv4_pro_vector`, `recraftv4`, `recraftv4_pro`. Vault path: `kv/data/providers/recraft`
- **fal.ai** — FLUX raster image generation via `backend/shared/providers/fal/flux.py`. Vault path: `kv/data/providers/fal`
- **Google Gemini** — default raster image generation (reuses AI provider credentials)

## Search & Web Providers

- **Brave Search API** — web search via `backend/shared/providers/brave/brave_search.py`. Vault path: `kv/data/providers/brave`
- **Firecrawl** — web scraping and content extraction via `backend/shared/providers/firecrawl/firecrawl_scrape.py`. API base: `https://api.firecrawl.dev/v2`. Vault path: `kv/data/providers/firecrawl`
- **SerpAPI** — Google Search, Google Lens (reverse image search) via `backend/shared/providers/serpapi.py`. Vault path: `kv/data/providers/serpapi`

## Maps & Location Providers

- **Google Maps Static API** — static map image rendering via `backend/shared/providers/google_maps/static_maps.py`
- **Google Places API** — place search via `backend/shared/providers/google_maps/google_places.py`
- **ip-api.com** — free IP geolocation (no key required) at `http://ip-api.com/json/`. Used in `backend/core/api/app/utils/device_fingerprint.py` with `lru_cache`
- **MaxMind GeoIP** — local GeoIP database lookups via `maxminddb` library. DB file path managed by backend config
- **timezonefinder** — offline timezone lookup from lat/lon coordinates (no external API)

## Travel Providers (in `backend/apps/travel/`)

- **SerpAPI** — hotel and flight search via `providers/serpapi_hotels_provider.py` and `providers/serpapi_provider.py`
- **Duffel** — flight search API (`test_duffel_flight_search.py` exists; sandbox endpoint used). Vault path: `kv/data/providers/duffel`
- **Travelpayouts** — flight price calendar via `providers/travelpayouts_provider.py`. API: `https://api.travelpayouts.com/v2/prices/month-matrix`
- **Flightradar24** — live flight tracking via `providers/flightradar24_provider.py`
- **Transitous (MOTIS)** — public transit routing via `providers/transitous_provider.py`. API: `https://api.transitous.org`
- **airports-py** — offline IATA airport database (~28k airports, no API call)

## Payment Processing

Payment services in `backend/core/api/app/services/payment/`. Routes at `backend/core/api/app/routes/payments.py`.

**Payment Providers:**
- **Stripe** — primary payment processor via `stripe` SDK (`stripe_service.py`). Handles `payment_intent.succeeded`, `payment_intent.payment_failed`, refund events. Frontend: `@stripe/stripe-js`
- **Polar.sh** — open-source payment alternative via `polar-sdk` (`polar_service.py`). Uses Standard Webhooks verification. Frontend: `@polar-sh/checkout`
- **Revolut** — payment option via `revolut_service.py`. Frontend: `@revolut/checkout`

**Incoming Webhooks:**
- `POST /v1/payments/webhook` — receives Stripe, Polar, and Revolut webhook events. Differentiated by payload structure and headers.

**Invoicing:**
- **InvoiceNinja** — self-hosted invoicing system integrated via HTTP API. Client in `backend/core/api/app/services/invoiceninja/`. Manages clients, invoices, payments, bank accounts, transactions.

## Data Storage

**Primary Database:**
- PostgreSQL 13 (Alpine image) — via Directus CMS abstraction layer
  - Container: `cms-database`
  - Env vars: `DATABASE_USERNAME`, `DATABASE_PASSWORD`, `DATABASE_NAME`
  - Persistent volume: `openmates-postgres-data`

**CMS / Database Abstraction:**
- **Directus** 11.5 — headless CMS acting as DB API layer
  - Container: `cms` at `http://cms:8055`
  - All data access goes through `DirectusService` (`backend/core/api/app/services/directus/`)
  - Auth: `DIRECTUS_TOKEN` env var
  - Schema migrations: `backend/core/directus/schemas/`

**Cache / In-Memory:**
- **DragonflyDB** — Redis-compatible in-memory cache (replaces Redis)
  - Image: `docker.dragonflydb.io/dragonflydb/dragonfly`
  - Container: `cache` at `cache:6379`
  - Used by: API, Directus (cache layer), all Celery workers
  - Auth: `DRAGONFLY_PASSWORD`
  - Max memory: configurable via `CACHE_MAX_MEMORY` env var (default 3000mb)

**Client-Side Storage:**
- **IndexedDB** — browser-side storage for all chat data, messages, keys, embeds
  - Managed by `ChatDatabase` class in `frontend/packages/ui/src/services/db.ts`
  - Encryption: AES-256-GCM via `frontend/packages/ui/src/services/cryptoService.ts`
  - No third-party ORM — raw IndexedDB API

**File Storage:**
- **AWS S3** (or S3-compatible) — via `boto3` + `S3UploadService` in `backend/core/api/app/services/s3/`
  - Configured in `backend/core/api/app/services/s3/config.py`
  - Buckets (dev/prod variants):
    - `openmates-profile-images-private` — encrypted profile images
    - `openmates-chatfiles` — encrypted chat file attachments (500MB max)
    - `openmates-invoices` — invoice PDFs (10yr retention)
    - `openmates-userdata-backups` — user export backups (60d retention)
    - `openmates-compliance-logs-backups` — financial (10yr) + audit (2yr) logs
    - `openmates-usage-archives` — usage data archives (7yr retention)
    - `openmates-temp-images` — public temp images for reverse image search (1d TTL)
    - `openmates-issue-logs` — debug issue logs + screenshots (1yr retention)
  - Credentials: from Vault

## Secret Management

- **HashiCorp Vault** 1.19 — secrets backend
  - Container: `vault` at `http://vault:8200`
  - Mode: file-based storage with auto-unseal
  - Setup container: `vault-setup` runs `setup_vault.py` on start
  - Token stored at `/vault-data/api.token` (shared Docker volume)
  - API access via `SecretsManager` singleton (`backend/core/api/app/utils/secrets_manager.py`)
  - All provider API keys stored at `kv/data/providers/<provider_name>`

## Authentication & Identity

**Auth System:**
- Custom-built, zero-knowledge architecture. No third-party auth provider.
- Routes in `backend/core/api/app/routes/auth_routes/`
- Key mechanisms:
  - **Password auth** — Argon2 hashing via `argon2-cffi`
  - **Passkeys (WebAuthn)** — via `webauthn` 2.7 + `cbor2` (`auth_passkey.py`). PRF extension required for zero-knowledge key derivation
  - **2FA (TOTP)** — via `pyotp` (`auth_2fa_setup.py`, `auth_2fa_verify.py`)
  - **Recovery key** — cryptographic account recovery (`auth_recovery.py`)
  - **Invite codes** — invite-only signup flow (`auth_invite.py`)
  - **Gift cards** — gift card redemption (`auth_gift.py`)
  - **Pair codes** — device pairing (`auth_pair.py`)
  - **Session tokens** — custom JWT-like tokens, stored in Dragonfly

## Email

- **Brevo (Sendinblue)** — primary transactional email provider
  - `backend/core/api/app/services/email/brevo_provider.py`
  - API: `https://api.brevo.com/v3/smtp/email`
  - Vault path: `kv/data/providers/brevo`
- **Mailjet** — secondary/fallback email provider
  - `backend/core/api/app/services/email/mailjet_provider.py`
- Email rendering: MJML templates (`mjml-python` + `jinja2` + `premailer` for CSS inlining)
- Templates location: `backend/core/api/templates/`

## Push Notifications

- **Web Push (VAPID)** — browser push notifications via `pywebpush`
  - No third-party push service — pure VAPID server-to-browser protocol
  - Service: `backend/core/api/app/services/push_notification_service.py`
  - VAPID keys generated once and stored in Vault at `kv/data/providers/vapid`
  - Celery task: `push_notification_task.py` in `task-worker`

## Monitoring & Observability

**Metrics Pipeline:**
- **Prometheus** `prom/prometheus:v3.2.1` — metrics scraping
  - Config: `backend/core/monitoring/prometheus/prometheus.yml`
  - Scrapes: API (`:8000/metrics`), cAdvisor (`:8080`), Celery workers (ports 9101-9104)
  - Remote-writes all metrics to OpenObserve
- **OpenObserve** `public.ecr.aws/zinclabs/openobserve:v0.70.0-rc3` — unified log + metrics storage
  - Container: `openobserve` at `http://openobserve:5080`
  - Accepts Prometheus remote_write + Loki-compatible log ingestion
  - Provides SQL and PromQL query interface
- **Promtail** `grafana/promtail:3.4.2` — log shipping to OpenObserve
  - Config: `backend/core/monitoring/promtail/`
- **Alertmanager** `prom/alertmanager:v0.31.1` — alert routing
  - Config: `backend/core/monitoring/alertmanager/alertmanager.yml`
  - Alert rules: `backend/core/monitoring/prometheus/alert_rules.yml`
- **cAdvisor** `gcr.io/cadvisor/cadvisor:v0.47.2` — container resource metrics
- **Client log forwarding** — frontend logs shipped to backend via `clientLogForwarder.ts`, then pushed to OpenObserve by `openobserve_push_service.py`

**Error Tracking:**
- No third-party error tracker (e.g., Sentry). Errors logged to OpenObserve + admin debug API.

## Infrastructure & Networking

- **Caddy** — reverse proxy + automatic TLS (Let's Encrypt)
  - Template: `deployment/Caddyfile.example`
  - Handles all inbound traffic, path allowlisting, security headers
- **Cloudflare Tunnels** (cloudflared) — ephemeral tunnels for E2E test CI pipeline
  - Binary at `/home/superdev/.local/bin/cloudflared` (host-mounted into `api` container)
  - Managed via `backend/core/api/app/routers/internal_tunnel.py`

## Mail Integration (Proton Mail Bridge)

- **Proton Mail Bridge** — IMAP/SMTP bridge for the mail app
  - Provider: `backend/shared/providers/protonmail/`
  - Used by: `backend/apps/mail/skills/search_skill.py`
  - Self-hosted Bridge instance connects to Proton's servers

## YouTube / Video

- **YouTube Data API v3** — video metadata via `google-api-python-client`
  - Provider: `backend/shared/providers/youtube/youtube_metadata.py`
  - Vault path: `kv/data/providers/youtube`
- **YouTube Transcript API** — transcript fetching via `youtube-transcript-api`
  - Routed through Webshare proxy to avoid IP blocks
  - Used by: `backend/apps/videos/skills/transcript_skill.py`
- **Webshare** — HTTP proxy service for YouTube transcript requests
  - Vault path: `kv/data/providers/webshare`

## Content Authenticity

- **C2PA** (`c2pa-python` 0.28) — content credentials watermarking for AI-generated images
  - Used in `backend/core/api/app/utils/image_processing.py`

## CI/CD & Deployment

**Hosting:**
- Backend: Linux VPS via Docker Compose + Caddy
- Frontend: Vercel (adapter-vercel)
- CI pipeline: Playwright E2E tests triggered via Celery (`e2e_test_tasks.py`), results stored in `test-results/`

**Version Detection:**
- SvelteKit version polling every 2 minutes using git commit hash (`svelte.config.js`)

## Environment Configuration

**Required env vars (critical subset):**
- `DIRECTUS_TOKEN` — Directus API auth token
- `DATABASE_USERNAME`, `DATABASE_PASSWORD`, `DATABASE_NAME`, `DATABASE_ADMIN_EMAIL`, `DATABASE_ADMIN_PASSWORD`
- `DIRECTUS_SECRET` — Directus encryption key
- `DRAGONFLY_PASSWORD` — DragonflyDB auth password
- `INTERNAL_API_SHARED_TOKEN` — inter-service HMAC auth token
- `TUNNEL_TRIGGER_SECRET` — Cloudflare tunnel HMAC secret
- `SERVER_ENVIRONMENT` — `development` or `production`
- `VAPID_CONTACT_EMAIL` — VAPID contact email for push notifications
- `CELERY_AUTOSCALE_MAX`, `CELERY_AUTOSCALE_MIN` — worker pool sizing
- All provider API keys stored in Vault (not directly in `.env`)

**Secrets location:**
- `.env` file at project root (gitignored) — infrastructure credentials
- HashiCorp Vault — all third-party API keys (loaded at runtime via `SecretsManager`)

## Webhooks & Callbacks

**Incoming:**
- `POST /v1/payments/webhook` — Stripe payment events (`payment_intent.succeeded`, `payment_intent.payment_failed`, refunds)
- `POST /v1/payments/webhook` — Polar.sh events (`checkout.created`, `checkout.updated`, `refund.updated`)
- `POST /v1/payments/webhook` — Revolut payment events

**Outgoing:**
- VAPID Web Push to browsers (direct, no intermediary)
- Email via Brevo/Mailjet APIs

---

*Integration audit: 2026-03-26*
