# File Upload Architecture

> **Status**: ✅ Implemented (Phase 1: images only)  
> **Last Updated**: 2026-02-19

This document describes the implemented file upload system and its security-isolated architecture.

---

## Overview

User-uploaded files flow through a dedicated **`app-uploads` microservice** that runs on its own VM, isolated from the main server. The upload VM has zero access to the main Vault, Directus, or any user data. All sensitive operations are proxied through the core API.

Processing steps per upload:

1. **Authentication** — user session cookie validated via core API internal endpoint
2. **Validation** — file size (100 MB max) + MIME type whitelist
3. **Deduplication** — per-user SHA-256 hash check via core API proxy (instant response for repeat uploads)
4. **Malware scanning** — ClamAV via TCP socket (blocks upload; 422 if threat detected)
5. **AI detection** — SightEngine `genai` model via local Vault credentials (non-blocking; tag only, never rejects)
6. **Preview generation** — Pillow WEBP preview at max 600×600px
7. **Encryption** — AES-256-GCM with a random per-file key (pure local operation)
8. **Key wrapping** — AES key wrapped by core API via Vault Transit proxy (`/internal/uploads/wrap-key`)
9. **S3 upload** — encrypted original + preview stored in `chatfiles` bucket (S3 credentials from local Vault)
10. **Record storage** — written to Directus `upload_files` collection via core API proxy (`/internal/uploads/store-record`)

The client receives the plaintext AES key and all S3 metadata to construct an embed TOON,
which is then **client-encrypted** before storage in Directus (zero-knowledge at rest).

---

## Security Architecture

The upload service runs on a **separate Hetzner CAX21 VM** from the main server.

```
┌─────────────────────────────────────────────────────┐
│                   UPLOADS VM                        │
│                                                     │
│  app-uploads ──► local Vault (dev mode)             │
│       │              └── S3 credentials             │
│       │              └── SightEngine credentials    │
│       │                                             │
│       └──► core API /internal/uploads/*             │
│                  (INTERNAL_API_SHARED_TOKEN)         │
└─────────────────────────────────────────────────────┘
         ↓ proxied through core API only ↓
┌─────────────────────────────────────────────────────┐
│                   MAIN SERVER                       │
│                                                     │
│  core API ──► main Vault (Transit encrypt only)     │
│           └── Directus (dedup check + record write) │
└─────────────────────────────────────────────────────┘
```

**Compromise blast radius:** If the upload VM is fully compromised, the attacker obtains only S3 write credentials and SightEngine API keys. They **cannot**:

- Decrypt any existing files (no Vault Transit decrypt access)
- Access user data (no direct Directus access)
- Reach the main Vault

**Local Vault:** Runs in dev mode (in-memory, auto-unsealed) as a Docker sidecar. A `vault-setup` init container migrates `SECRET__*` env vars into KV v2 on every stack start. The local Vault has no Transit engine and no user keys — only two KV paths: `kv/data/providers/hetzner` (S3) and `kv/data/providers/sightengine`.

See:

- [`backend/apps/uploads/docker-compose.yml`](../../backend/apps/uploads/docker-compose.yml) — local Vault + vault-setup + ClamAV service definitions
- [`backend/apps/uploads/vault/setup_vault.py`](../../backend/apps/uploads/vault/setup_vault.py) — KV migration script
- [`backend/apps/uploads/vault/Dockerfile`](../../backend/apps/uploads/vault/Dockerfile) — vault-setup init container image

---

## Encryption Model

```
┌──────────────────────────────────────────────────────────────────────┐
│                          UPLOADS VM                                  │
│                                                                      │
│  plaintext_bytes                                                      │
│       │                                                               │
│       ├── AES-256-GCM(random_key) → encrypted_original.bin → S3     │
│       └── AES-256-GCM(same_key)  → encrypted_preview.bin  → S3     │
│                                                                      │
│  random_key ──── POST /internal/uploads/wrap-key ──► main Vault     │
│                         (core API proxy)             Transit encrypt │
│                                                      ↓               │
│  vault_wrapped_aes_key ◄──────────────────────────────────────────  │
└──────────────────────────────────────────────────────────────────────┘

                        ↓ Server returns to client ↓

   {
     embed_id, filename, content_type, content_hash,
     files: { original: {...}, preview: {...} },
     s3_base_url,
     aes_key,              ← plaintext — for client-side rendering
     aes_nonce,
     vault_wrapped_aes_key ← for server-side skills (images.view)
   }

                        ↓ Client builds embed TOON ↓

   embed TOON content includes aes_key + vault_wrapped_aes_key
   → client-encrypts TOON with user's embed key
   → stores in Directus (server cannot read it)
```

**Key properties:**

- Files are encrypted **before** S3 upload — plaintext bytes never leave the upload server
- The plaintext `aes_key` is returned to the client for browser-side rendering but is stored inside client-encrypted embed content at rest (zero-knowledge in Directus)
- The `vault_wrapped_aes_key` allows backend skills to decrypt the file on demand without the client being online
- Key wrapping uses **only Vault Transit `encrypt`** — the upload VM never has Transit decrypt capability

See:

- [`backend/apps/uploads/services/file_encryption.py`](../../backend/apps/uploads/services/file_encryption.py) — pure AES-256-GCM encryption (no Vault)
- [`backend/core/api/app/routes/internal_api.py`](../../backend/core/api/app/routes/internal_api.py) — `/internal/uploads/wrap-key` endpoint

---

## Upload Flow

### HTTP POST (not WebSocket)

The client sends a **multipart form POST** to `/api/uploads/v1/upload/file`.

```
Browser → Caddy → app-uploads (POST /v1/upload/file)
                        │
                        ├── GET /internal/validate-token → core API
                        ├── POST /internal/uploads/check-duplicate → core API → Directus
                        ├── scan_stream(bytes) → clamav:3310
                        ├── POST api.sightengine.com (optional, creds from local Vault)
                        ├── Pillow preview generation (thread pool)
                        ├── AES-256-GCM encrypt original + preview (in memory)
                        ├── POST /internal/uploads/wrap-key → core API → main Vault Transit
                        ├── PUT s3://chatfiles/.../original.bin (S3 creds from local Vault)
                        ├── PUT s3://chatfiles/.../preview.bin
                        └── POST /internal/uploads/store-record → core API → Directus
```

See:

- [`backend/apps/uploads/routes/upload_route.py`](../../backend/apps/uploads/routes/upload_route.py) — full upload endpoint implementation
- [`backend/core/api/app/routes/internal_api.py`](../../backend/core/api/app/routes/internal_api.py) — all three proxy endpoints

### Frontend embed flow

```
User selects image
    │
    ├── insertImage() inserts embed node (status: 'uploading', src: blobUrl)
    │
    └── _performUpload() [background, non-blocking]
            │
            ├── uploadFileToServer(file) → POST /api/uploads/v1/upload/file
            │
            ├── SUCCESS: update embed node attrs:
            │       status: 'finished'
            │       uploadEmbedId, s3Files, s3BaseUrl,
            │       aesKey, aesNonce, vaultWrappedAesKey,
            │       contentHash, aiDetection
            │
            └── FAILURE: update embed node:
                    status: 'error'
                    uploadError: <message>
```

The embed card shows a loading indicator while `status === 'uploading'`.
The message send button is disabled while any embed is in `uploading` state.

---

## Internal API Proxy Endpoints

Three endpoints on the core API server act as a security boundary between the upload VM and the main infrastructure. All require `INTERNAL_API_SHARED_TOKEN` in the `X-Internal-Token` header.

| Endpoint                                 | What it does                                                                |
| ---------------------------------------- | --------------------------------------------------------------------------- |
| `POST /internal/uploads/check-duplicate` | Queries `upload_files` Directus collection for `(user_id, content_hash)`    |
| `POST /internal/uploads/wrap-key`        | Calls main Vault Transit `encrypt` on the user's key ID to wrap the AES key |
| `POST /internal/uploads/store-record`    | Creates a new record in `upload_files` Directus collection                  |

All three are implemented in [`backend/core/api/app/routes/internal_api.py`](../../backend/core/api/app/routes/internal_api.py).

---

## File Type Routing

| File type                                                           | Route                     | Status                    |
| ------------------------------------------------------------------- | ------------------------- | ------------------------- |
| Images (JPEG, PNG, WEBP, GIF, HEIC, BMP, TIFF)                      | app-uploads microservice  | **Phase 1 — implemented** |
| PDF                                                                 | app-uploads microservice  | Phase 2 — planned         |
| DOCX, XLSX                                                          | app-uploads microservice  | Phase 3 — planned         |
| Code (`.py`, `.js`, `.ts`, `.json`, `.yaml`, `.csv`, `.txt`, `.md`) | Client-only (code embed)  | Already works             |
| Audio (`.mp3`, `.wav`, `.ogg`)                                      | Client-only (audio embed) | Already works             |
| Video                                                               | Client-only (video embed) | Already works             |
| EPUB                                                                | Client-only (epub embed)  | Already works             |

---

## Service and File Reference

### Upload VM (app-uploads)

| Path                                                                                                                 | Description                                                           |
| -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| [`backend/apps/uploads/main.py`](../../backend/apps/uploads/main.py)                                                 | FastAPI app, lifespan startup (ClamAV, encryption, SightEngine, S3)   |
| [`backend/apps/uploads/routes/upload_route.py`](../../backend/apps/uploads/routes/upload_route.py)                   | `POST /v1/upload/file` — full upload pipeline                         |
| [`backend/apps/uploads/services/malware_scanner.py`](../../backend/apps/uploads/services/malware_scanner.py)         | ClamAV TCP socket client                                              |
| [`backend/apps/uploads/services/file_encryption.py`](../../backend/apps/uploads/services/file_encryption.py)         | Pure AES-256-GCM encryption (no Vault)                                |
| [`backend/apps/uploads/services/preview_generator.py`](../../backend/apps/uploads/services/preview_generator.py)     | Pillow WEBP preview generation                                        |
| [`backend/apps/uploads/services/sightengine_service.py`](../../backend/apps/uploads/services/sightengine_service.py) | SightEngine AI detection (credentials from local Vault)               |
| [`backend/apps/uploads/services/s3_upload.py`](../../backend/apps/uploads/services/s3_upload.py)                     | S3 upload for chatfiles bucket (credentials from local Vault)         |
| [`backend/apps/uploads/vault/setup_vault.py`](../../backend/apps/uploads/vault/setup_vault.py)                       | Local Vault init: KV v2, policy, scoped token, SECRET\_\_\* migration |
| [`backend/apps/uploads/vault/Dockerfile`](../../backend/apps/uploads/vault/Dockerfile)                               | vault-setup init container image                                      |
| [`backend/apps/uploads/docker-compose.yml`](../../backend/apps/uploads/docker-compose.yml)                           | Vault, vault-setup, ClamAV, app-uploads service definitions           |
| [`backend/apps/uploads/docker-compose.override.yml`](../../backend/apps/uploads/docker-compose.override.yml)         | Dev overrides (openmates network join, port 8004)                     |
| [`backend/apps/uploads/Dockerfile`](../../backend/apps/uploads/Dockerfile)                                           | Upload service image (libmagic1, Pillow deps)                         |

### Core Server additions

| Path                                                                                                     | Description                                                                 |
| -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| [`backend/core/api/app/routes/internal_api.py`](../../backend/core/api/app/routes/internal_api.py)       | `/internal/uploads/check-duplicate`, `/wrap-key`, `/store-record` endpoints |
| [`backend/core/directus/schemas/upload_files.yml`](../../backend/core/directus/schemas/upload_files.yml) | Deduplication collection schema                                             |
| [`backend/apps/images/skills/view_skill.py`](../../backend/apps/images/skills/view_skill.py)             | `images.view` skill for server-side AI image analysis                       |

### Frontend

| Path                                                                                                                                                 | Description                                                              |
| ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| [`frontend/.../enter_message/services/uploadService.ts`](../../frontend/packages/ui/src/components/messages/enter_message/services/uploadService.ts) | `uploadFileToServer()` — POST to upload endpoint, returns embed metadata |
| [`frontend/.../enter_message/embedHandlers.ts`](../../frontend/packages/ui/src/components/messages/enter_message/embedHandlers.ts)                   | `insertImage()` — inserts embed node, triggers background upload         |

---

## Environment Variables

### Upload VM `.env`

```env
# Core API connection (the ONLY external service the upload VM contacts)
CORE_API_URL=http://<main-server-private-ip>:8000
INTERNAL_API_SHARED_TOKEN=<shared-secret>

# Local Vault root token (random UUID — only used by vault-setup)
UPLOADS_VAULT_ROOT_TOKEN=<random-uuid>

# S3 credentials (migrated into local Vault by vault-setup on startup)
SECRET__HETZNER__S3_ACCESS_KEY=...
SECRET__HETZNER__S3_SECRET_KEY=...
SECRET__HETZNER__S3_REGION_NAME=nbg1

# SightEngine AI detection (optional — AI detection disabled if not set)
SECRET__SIGHTENGINE__API_USER=...
SECRET__SIGHTENGINE__API_SECRET=...

SERVER_ENVIRONMENT=production
LOG_LEVEL=info
```

No `DIRECTUS_TOKEN`, `CMS_URL`, or main `VAULT_TOKEN` / `VAULT_URL` vars are needed on the upload VM.

---

## Deduplication

Per-user deduplication uses `(user_id, content_hash)` as the unique key. Records are stored in the `upload_files` Directus collection, queried via the `/internal/uploads/check-duplicate` proxy endpoint. On a cache hit, the server returns the existing `embed_id`, `aes_key`, S3 keys, and all metadata instantly — no re-upload, no re-scan, no re-encryption.

**Cross-user deduplication is intentionally NOT implemented.** Different users who upload the same file each get their own encrypted copy with their own AES key. This maintains the per-user encryption model at the cost of some storage redundancy.

---

## Server-Side Image Analysis (images.view skill)

The `images.view` skill ([`backend/apps/images/skills/view_skill.py`](../../backend/apps/images/skills/view_skill.py)) allows the AI to analyse uploaded images:

1. Receives `vault_wrapped_aes_key`, `s3_key`, `s3_base_url`, `aes_nonce`, `query` from the AI processor (extracted from the embed's TOON content)
2. Unwraps the AES key via Vault Transit using the user's `vault_key_id` (main Vault — on main server)
3. Downloads the encrypted file from S3
4. Decrypts with AES-256-GCM
5. Passes base64-encoded image to the multimodal AI model for analysis
6. Returns the AI's analysis text

---

## Planned Phases

### Phase 2 — PDFs

- Add `pdf` app with `read` skill (text extraction + chapter TOC) and `view` skill (screenshot pages via pdf2image, passed to vision LLM)
- Update `app-uploads` to handle `application/pdf` MIME type

### Phase 3 — DOCX / XLSX

- Add macro malware scanning (LibreOffice headless + oletools)
- Add `docs` app skill for text extraction from DOCX
- Add `sheets` app skill for structured data extraction from XLSX

---

## Read Next

- [Message Processing Architecture](./message_processing.md) — how AI skills consume uploaded file embed data
- [`backend/core/api/app/routes/internal_api.py`](../../backend/core/api/app/routes/internal_api.py) — internal proxy endpoint implementations
- [`backend/apps/uploads/routes/upload_route.py`](../../backend/apps/uploads/routes/upload_route.py) — full upload pipeline code
