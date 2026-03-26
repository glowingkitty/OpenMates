# Technology Stack

**Analysis Date:** 2026-03-26

## Languages

**Primary:**
- TypeScript ~5.9.2 - Frontend (SvelteKit app + shared UI package)
- Python 3.13 - Backend (all FastAPI services, Celery workers, scripts)

**Secondary:**
- JavaScript (ES Module) - Build scripts, metadata generators in `frontend/packages/ui/scripts/`
- CSS Custom Properties - Frontend styling (no Tailwind, no CSS-in-JS)
- YAML - Config files (`shared/config/`, `backend/apps/*/app.yml`, i18n sources)

## Runtime

**Environment:**
- Node.js >=18 (frontend builds and dev server)
- Python 3.13 (Docker image: `python:3.13-slim` — all backend containers)

**Package Manager:**
- pnpm 10.23.0 (frontend monorepo)
- Lockfile: `pnpm-lock.yaml` (present, committed)
- pip (backend, via `requirements.txt` files per service)

## Frameworks

**Frontend Core:**
- Svelte 5.54+ with Runes (`compilerOptions.runes: true`) — reactive UI
- SvelteKit 2.55+ — routing, SSR/prerendering, adapter-vercel deployment
- Vite 7.3+ — build tool (`frontend/apps/web_app/vite.config.ts`)
- Turbo 2.7+ — monorepo task runner (`turbo.json`)

**Backend Core:**
- FastAPI 0.128 — REST API (`backend/core/api/`)
- Uvicorn 0.40 (standard) — ASGI server
- Pydantic v2 2.11 — data validation and schemas
- Celery 5.5 — async task queue (`backend/core/api/app/tasks/`)

**Testing:**
- Vitest 3.2+ — frontend unit tests (`frontend/packages/ui/src/services/__tests__/`)
- Playwright 1.49 — E2E tests (`frontend/apps/web_app/tests/`)
- pytest (asyncio_mode=auto) — backend unit + integration tests (`backend/tests/`)

**Build/Dev:**
- `@vite-pwa/sveltekit` 1.0 — PWA manifest + Workbox service worker
- `prettier` 3.7 + `prettier-plugin-svelte` 3.4 — formatting
- `ruff` 0.14.11 — Python linting
- `yamllint` 1.37.1 — YAML linting

## Key Dependencies

**Critical Frontend:**
- `@tiptap/core` 3.4 + extensions — rich text message editor (ProseMirror-based)
- `svelte-i18n` 4.0 — i18n runtime (21 locales, YAML sources auto-compiled to JSON)
- `tweetnacl` 1.0 — client-side NaCl crypto (end-to-end encryption)
- `@stripe/stripe-js` 7.9 — Stripe checkout SDK
- `@polar-sh/checkout` 0.2 — Polar.sh checkout SDK
- `@revolut/checkout` 1.1 — Revolut checkout SDK
- `leaflet` 1.9 + `@types/leaflet` — maps rendering
- `katex` 0.16 — math formula rendering
- `jspdf` 4.2 + `jszip` 3.10 — PDF/ZIP export
- `dompurify` 3.3 — HTML sanitization
- `@lucide/svelte` 0.545 — icon library
- `date-fns` 4.1 — date utilities
- `lodash-es` 4.17 — utility functions
- `function-plot` 1.25 — mathematical function plotting

**Critical Backend:**
- `httpx` 0.28 — async HTTP client (used everywhere instead of requests)
- `redis` 5.2 — Dragonfly/Redis client
- `boto3` 1.37 — AWS S3 storage
- `celery` 5.5 — async task queue with beat scheduler
- `argon2-cffi` 23.1 — password hashing
- `cryptography` 46.0 — AES-256-GCM encryption
- `pynacl` 1.6 — NaCl crypto (server-side)
- `webauthn` 2.7 — WebAuthn/Passkey authentication
- `pyotp` 2.9 — TOTP-based 2FA
- `pywebpush` 2.3 — Web Push (VAPID) notifications
- `openai` 2.15 — OpenAI API client
- `anthropic` 0.57 — Anthropic Claude API client
- `google-genai` 1.58 — Google Gemini API client
- `groq` 0.34 — Groq API client
- `stripe` 12.2 — Stripe server-side SDK
- `polar-sdk` 0.29 — Polar.sh server-side SDK
- `c2pa-python` 0.28 — Content authenticity (C2PA) for image watermarking
- `toon-format` (git) — custom binary encoding for AI response embeds
- `pymupdf` 1.27 — PDF page screenshot rendering
- `sympy` 1.14 + `mpmath` 1.3 — symbolic/numeric math
- `Pillow` 12.1 + `cairosvg` 2.9 — image processing
- `reportlab` 4.3 — PDF generation
- `mjml-python` 1.3 + `jinja2` 3.1 — transactional email templating
- `tiktoken` 0.9 — token counting for LLM requests
- `timezonefinder` 8.2 + `pytz` 2025.2 — timezone resolution
- `staticmap` 0.5 — static map image generation
- `maxminddb` 3.1 — MaxMind GeoIP database (local lookup)
- `airports-py` 3.0 — offline airport IATA database (~28k airports)
- `user-agents` 2.2 — user-agent string parsing
- `youtube-transcript-api` 1.2 — YouTube transcript fetching (via Webshare proxy)
- `google-api-python-client` 2.187 — YouTube Data API v3

## Configuration

**Environment:**
- All secrets injected via `.env` file at project root (read by Docker Compose `env_file`)
- Runtime secrets fetched from HashiCorp Vault at `http://vault:8200` via `SecretsManager` class (`backend/core/api/app/utils/secrets_manager.py`)
- Shared YAML configs at `shared/config/` (mounted to `/shared` in all containers)
  - `urls.yml` — environment-specific base URLs
  - `pricing.yml` — credit/billing pricing rules
  - `costs.yml` — per-model AI costs
  - `embed_types.yml` — supported embed type registry

**Build:**
- `turbo.json` — monorepo build pipeline (frontend)
- `frontend/apps/web_app/vite.config.ts` — Vite config with PWA, chunk splitting
- `frontend/apps/web_app/svelte.config.js` — adapter-vercel, Runes mode
- `backend/core/docker-compose.yml` — all production services definition
- `backend/core/docker-compose.override.yml` — local dev overrides
- `backend/pytest.ini` — pytest configuration

## Platform Requirements

**Development:**
- Docker + Docker Compose (all backend services run in containers)
- Node.js >=18 + pnpm 10.23 (frontend)
- cloudflared binary at `/home/superdev/.local/bin/cloudflared` (ephemeral tunnel for E2E tests)

**Production:**
- Backend: Docker on a Linux VPS, reverse-proxied by Caddy (`deployment/Caddyfile.example`)
- Frontend: Vercel (adapter-vercel, `@sveltejs/adapter-vercel` 6.3)
- PWA: Workbox service worker, standalone display mode

---

*Stack analysis: 2026-03-26*
