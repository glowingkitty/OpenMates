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

- [`backend/upload/docker-compose.yml`](../../backend/upload/docker-compose.yml) — local Vault + vault-setup + ClamAV service definitions
- [`backend/upload/vault/setup_vault.py`](../../backend/upload/vault/setup_vault.py) — KV migration script
- [`backend/upload/vault/Dockerfile`](../../backend/upload/vault/Dockerfile) — vault-setup init container image

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

- [`backend/upload/services/file_encryption.py`](../../backend/upload/services/file_encryption.py) — pure AES-256-GCM encryption (no Vault)
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

- [`backend/upload/routes/upload_route.py`](../../backend/upload/routes/upload_route.py) — full upload endpoint implementation
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
| [`backend/upload/main.py`](../../backend/upload/main.py)                                                 | FastAPI app, lifespan startup (ClamAV, encryption, SightEngine, S3)   |
| [`backend/upload/routes/upload_route.py`](../../backend/upload/routes/upload_route.py)                   | `POST /v1/upload/file` — full upload pipeline                         |
| [`backend/upload/services/malware_scanner.py`](../../backend/upload/services/malware_scanner.py)         | ClamAV TCP socket client                                              |
| [`backend/upload/services/file_encryption.py`](../../backend/upload/services/file_encryption.py)         | Pure AES-256-GCM encryption (no Vault)                                |
| [`backend/upload/services/preview_generator.py`](../../backend/upload/services/preview_generator.py)     | Pillow WEBP preview generation                                        |
| [`backend/upload/services/sightengine_service.py`](../../backend/upload/services/sightengine_service.py) | SightEngine AI detection (credentials from local Vault)               |
| [`backend/upload/services/s3_upload.py`](../../backend/upload/services/s3_upload.py)                     | S3 upload for chatfiles bucket (credentials from local Vault)         |
| [`backend/upload/vault/setup_vault.py`](../../backend/upload/vault/setup_vault.py)                       | Local Vault init: KV v2, policy, scoped token, SECRET\_\_\* migration |
| [`backend/upload/vault/Dockerfile`](../../backend/upload/vault/Dockerfile)                               | vault-setup init container image                                      |
| [`backend/upload/docker-compose.yml`](../../backend/upload/docker-compose.yml)                           | Vault, vault-setup, ClamAV, app-uploads service definitions           |
| [`backend/upload/docker-compose.override.yml`](../../backend/upload/docker-compose.override.yml)         | Dev overrides (openmates network join, port 8004)                     |
| [`backend/upload/Dockerfile`](../../backend/upload/Dockerfile)                                           | Upload service image (libmagic1, Pillow deps)                         |

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

## Storage Billing

Uploaded files consume persistent S3 storage. Users are charged weekly for storage above a 1 GB free tier.

### How it works

1. **Counter increment** — When `/internal/uploads/store-record` writes a new `upload_files` record, it also increments `storage_used_bytes` on the user record in Directus and cache (best-effort, non-fatal if it fails).
2. **Weekly billing run** — Every Sunday at 03:00 UTC the Celery Beat task `charge_storage_fees` (`app.tasks.storage_billing_tasks.charge_storage_fees`) runs on the `persistence` queue:
   - Aggregates `upload_files` by `user_id` to get the real total bytes per user (one DB call).
   - Filters to only users **above the 1 GB free tier** at the DB level.
   - Processes users in batches of 50 with bounded concurrency.
   - Charges each billable user via `BillingService.charge_user_credits`, which deducts credits, updates Directus, and creates a usage entry (`app_id="system"`, `skill_id="storage"`) visible in the activity log.
   - Reconciles `storage_used_bytes` with the real aggregate (corrects any counter drift from increments/decrements).
   - Updates `storage_last_billed_at` per user.

### Pricing

| Storage  | Weekly charge                               |
| -------- | ------------------------------------------- |
| 0 – 1 GB | Free                                        |
| > 1 GB   | 3 credits per GB per week (ceil to next GB) |

1,000 credits = $1 USD. 3 credits/GB/week ≈ $0.012/GB/month.

### Counter drift correction

The running `storage_used_bytes` counter on the user record may drift due to failed decrements or race conditions. The weekly billing run treats the aggregate query result as the authoritative value and overwrites `storage_used_bytes` on every run, preventing drift from accumulating across weeks.

### Billing failure handling

If a user cannot afford the weekly storage charge (insufficient credits), the billing failure counter `storage_billing_failures` on their user record is incremented. Each subsequent weekly failure escalates:

| Failure # | Action                                                                                            |
| --------- | ------------------------------------------------------------------------------------------------- |
| 1st       | Warning email: "Payment failed, please top up"                                                    |
| 2nd       | Second notice email: "2nd missed payment"                                                         |
| 3rd       | Final warning email: "Files will be deleted in 7 days"                                            |
| 4th       | All upload files deleted from S3 + Directus; deletion confirmation email sent; counter reset to 0 |

**On a successful charge**, the counter is reset to 0 immediately.

**What is deleted (4th failure):** All `upload_files` records for the user and their associated S3 objects (`original`, `full`, `preview` variants from `files_metadata`). Embed records are **not** deleted — they remain in Directus so the UI can show "File was deleted" for any messages that referenced the files.

**Email templates:** `storage-billing-failed-1`, `storage-billing-failed-2`, `storage-billing-failed-3`, `storage-files-deleted` (MJML, in `backend/core/api/templates/email/`). Each email includes the user's current storage (GB) and the credits/week required.

**Users with active failure counters** (`storage_billing_failures > 0`) are included in every billing run even if they have since dropped below the 1 GB free tier — so their failure state is always resolved.

### Key files

| Path                                                                                                                       | Description                                                                       |
| -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| [`backend/core/api/app/tasks/storage_billing_tasks.py`](../../backend/core/api/app/tasks/storage_billing_tasks.py)         | Weekly billing Celery task                                                        |
| [`backend/core/api/app/tasks/celery_config.py`](../../backend/core/api/app/tasks/celery_config.py)                         | Beat schedule: `charge-storage-fees-weekly` (Sunday 03:00 UTC)                    |
| [`backend/core/directus/schemas/users.yml`](../../backend/core/directus/schemas/users.yml)                                 | `storage_used_bytes`, `storage_last_billed_at`, `storage_billing_failures` fields |
| [`backend/core/api/app/services/directus/embed_methods.py`](../../backend/core/api/app/services/directus/embed_methods.py) | `delete_all_upload_files_for_user()` — nuclear deletion path                      |

---

## Auto-Deletion of Chats

Users can configure a chat retention period in **Privacy → Auto Deletion → Chats**. Stale chats (and their associated files) are deleted automatically.

### How it works

1. **User sets a period** — `POST /v1/settings/auto-delete-chats` accepts a period string (`"30d"`, `"60d"`, `"90d"`, `"6m"`, `"1y"`, `"2y"`, `"5y"`, `"never"`) and stores the equivalent integer day count as `auto_delete_chats_after_days` on the user record (`null` for `"never"`).
2. **Daily deletion run** — Every day at 02:30 UTC the Celery Beat task `auto_delete_old_chats` (`app.tasks.auto_delete_tasks.auto_delete_old_chats`) runs on the `persistence` queue:
   - Queries all users with a non-null `auto_delete_chats_after_days`.
   - For each user, computes a cutoff timestamp (`now − days × 86400`).
   - Queries chats whose `last_message_timestamp` is older than the cutoff (must have at least one message).
   - Dispatches `persist_delete_chat` for each stale chat — reusing the full deletion pipeline.
   - At most **100 chats per user per day** are scheduled (thundering-herd prevention); any remainder is caught on the next run.

### Full deletion pipeline (`persist_delete_chat`)

When a chat is deleted — whether triggered by the user, by auto-deletion, or by account deletion — the pipeline:

1. Deletes all draft messages.
2. Deletes all messages.
3. Deletes all embeds for the chat:
   - **Shared embeds** are also deleted if they are **not referenced by any other chat of the same user** (checked by querying `embeds` with the same `embed_id` but a different `hashed_chat_id` for the same `hashed_user_id`).
   - Deleted embed IDs are returned for the next step.
4. Deletes `upload_files` dedup records for all deleted embeds (frees dedup storage).
5. Decrements `storage_used_bytes` on the user by the freed bytes.
6. Deletes the chat record itself.

The `storage_used_bytes` counter is also corrected authoritatively by the weekly billing run, so any decrement inaccuracies are self-healing within at most one week.

### Key files

| Path                                                                                                                                         | Description                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| [`backend/core/api/app/tasks/auto_delete_tasks.py`](../../backend/core/api/app/tasks/auto_delete_tasks.py)                                   | Daily auto-delete Celery task                                  |
| [`backend/core/api/app/routes/settings.py`](../../backend/core/api/app/routes/settings.py)                                                   | `POST /v1/settings/auto-delete-chats` endpoint                 |
| [`backend/core/api/app/tasks/persistence_tasks.py`](../../backend/core/api/app/tasks/persistence_tasks.py)                                   | `persist_delete_chat` — full deletion pipeline                 |
| [`backend/core/api/app/services/directus/embed_methods.py`](../../backend/core/api/app/services/directus/embed_methods.py)                   | `delete_all_embeds_for_chat`, `delete_upload_files_for_embeds` |
| [`backend/core/api/app/tasks/celery_config.py`](../../backend/core/api/app/tasks/celery_config.py)                                           | Beat schedule: `auto-delete-old-chats-daily` (daily 02:30 UTC) |
| [`backend/core/directus/schemas/users.yml`](../../backend/core/directus/schemas/users.yml)                                                   | `auto_delete_chats_after_days` field                           |
| [`frontend/.../privacy/SettingsAutoDeletion.svelte`](../../frontend/packages/ui/src/components/settings/privacy/SettingsAutoDeletion.svelte) | UI for selecting and persisting the retention period           |

---

## Read Next

- [Message Processing Architecture](./message-processing.md) — how AI skills consume uploaded file embed data
- [`backend/core/api/app/routes/internal_api.py`](../../backend/core/api/app/routes/internal_api.py) — internal proxy endpoint implementations
- [`backend/upload/routes/upload_route.py`](../../backend/upload/routes/upload_route.py) — full upload pipeline code
