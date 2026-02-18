# File Upload Architecture

This document describes the **implemented** file upload system (Phase 1: images only)
and the planned extensions for PDFs, DOCX, and XLSX (Phases 2-3).

---

## Overview

User-uploaded files flow through a dedicated **`app-uploads` microservice** that handles:

1. **Authentication** — validates the user's session cookie via the core API
2. **Validation** — file size (100 MB max) + MIME type whitelist
3. **Deduplication** — per-user SHA-256 hash check (instant response for repeat uploads)
4. **Malware scanning** — ClamAV via TCP socket (blocks upload; 422 if threat detected)
5. **AI detection** — SightEngine `genai` model (non-blocking; tag only, never rejects)
6. **Preview generation** — Pillow WEBP preview at max 600×600px
7. **Encryption** — AES-256-GCM with a random per-file key
8. **Vault key wrapping** — Vault Transit wraps the AES key for server-side skill access
9. **S3 upload** — encrypted original + preview stored in `chatfiles` bucket
10. **Record storage** — Directus `upload_files` collection for deduplication

The client receives the plaintext AES key and all S3 metadata to construct an embed TOON,
which is then **client-encrypted** before storage in Directus (zero-knowledge at rest).

---

## Encryption Model

The encryption model mirrors the existing AI-generated image pipeline in `generate_task.py`:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            UPLOAD SERVER                                │
│                                                                         │
│  plaintext_bytes                                                         │
│       │                                                                  │
│       ├── AES-256-GCM(random_key) → encrypted_original.bin → S3        │
│       └── AES-256-GCM(same_key)  → encrypted_preview.bin  → S3        │
│                                                                         │
│  random_key ──────────────────────────────── aes_key (base64)          │
│                 ┌────────────────────────┐                              │
│                 │  Vault Transit encrypt  │                              │
│                 └────────────────────────┘                              │
│  vault_wrapped_aes_key ──────────────────────────────────────────────  │
└─────────────────────────────────────────────────────────────────────────┘

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

**Security properties:**

- Files are encrypted **before** S3 upload — plaintext bytes never leave the upload server
- The plaintext `aes_key` is returned to the client for browser-side rendering but is
  stored inside client-encrypted embed content at rest (zero-knowledge in Directus)
- The `vault_wrapped_aes_key` allows backend skills to decrypt the file on demand without
  the client needing to be online

---

## Upload Flow

### HTTP POST (not WebSocket)

The client sends a **multipart form POST** to `/api/uploads/v1/upload/file`.

```
Browser → Caddy/Nginx → app-uploads (POST /v1/upload/file)
                              │
                              ├── GET /internal/validate-token → api
                              ├── GET /items/upload_files → cms (dedup check)
                              ├── scan_stream(bytes) → clamav:3310
                              ├── POST api.sightengine.com (optional)
                              ├── Pillow (preview generation, thread pool)
                              ├── AES-256-GCM encryption (in memory)
                              ├── POST /v1/transit/encrypt/... → vault
                              ├── PUT s3://chatfiles/.../original.bin
                              ├── PUT s3://chatfiles/.../preview.bin
                              └── POST /items/upload_files → cms
```

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

## File Type Routing

| File type                                                           | Route                     | Handled by                |
| ------------------------------------------------------------------- | ------------------------- | ------------------------- |
| Images (JPEG, PNG, WEBP, GIF, HEIC, BMP, TIFF)                      | app-uploads microservice  | **Phase 1 — implemented** |
| PDF                                                                 | app-uploads microservice  | Phase 2 — planned         |
| DOCX, XLSX                                                          | app-uploads microservice  | Phase 3 — planned         |
| Code (`.py`, `.js`, `.ts`, `.json`, `.yaml`, `.csv`, `.txt`, `.md`) | Client-only (code embed)  | Already works             |
| Audio (`.mp3`, `.wav`, `.ogg`)                                      | Client-only (audio embed) | Already works             |
| Video                                                               | Client-only (video embed) | Already works             |
| EPUB                                                                | Client-only (epub embed)  | Already works             |

---

## New Services and Files

### Backend (Phase 1 — implemented)

| Path                                                   | Description                                  |
| ------------------------------------------------------ | -------------------------------------------- |
| `backend/apps/uploads/`                                | New upload microservice                      |
| `backend/apps/uploads/main.py`                         | FastAPI app with lifespan (startup/shutdown) |
| `backend/apps/uploads/routes/upload_route.py`          | `POST /v1/upload/file` endpoint              |
| `backend/apps/uploads/services/malware_scanner.py`     | ClamAV TCP socket client                     |
| `backend/apps/uploads/services/file_encryption.py`     | AES-256-GCM + Vault Transit wrapping         |
| `backend/apps/uploads/services/preview_generator.py`   | Pillow WEBP preview generation               |
| `backend/apps/uploads/services/sightengine_service.py` | SightEngine AI detection                     |
| `backend/apps/uploads/services/s3_upload.py`           | S3 upload/download for chatfiles bucket      |
| `backend/apps/uploads/Dockerfile`                      | Custom Dockerfile (libmagic1, Pillow deps)   |
| `backend/core/api/app/routes/internal_api.py`          | +`GET /internal/validate-token` endpoint     |
| `backend/core/directus/schemas/upload_files.yml`       | Deduplication collection schema              |
| `backend/apps/images/skills/view_skill.py`             | `images.view` skill for AI analysis          |
| `backend/apps/images/app.yml`                          | +`view` skill definition                     |
| `backend/core/docker-compose.yml`                      | +`app-uploads` + `clamav` services           |

### Frontend (Phase 1 — implemented)

| Path                                                   | Description                                  |
| ------------------------------------------------------ | -------------------------------------------- |
| `frontend/.../enter_message/services/uploadService.ts` | `uploadFileToServer()` function              |
| `frontend/.../enter_message/embedHandlers.ts`          | Updated `insertImage()` with upload pipeline |

---

## Environment Variables

Add to `.env` for `app-uploads` functionality:

```env
# ClamAV malware scanner (required for uploads to start)
CLAMAV_HOST=clamav
CLAMAV_PORT=3310

# SightEngine AI detection (optional — detection skipped if not set)
SIGHTENGINE_API_USER=your_api_user
SIGHTENGINE_API_SECRET=your_api_secret
```

---

## Server-Side Image Analysis (images.view skill)

The `images.view` skill (`backend/apps/images/skills/view_skill.py`) allows the AI to
analyse uploaded images:

1. Receives `vault_wrapped_aes_key`, `s3_key`, `s3_base_url`, `aes_nonce`, `query`
   from the AI processor (extracted from the embed's TOON content)
2. Unwraps the AES key via Vault Transit using the user's `vault_key_id`
3. Downloads the encrypted file from S3 (direct HTTPS, no presigned URL needed)
4. Decrypts with AES-256-GCM
5. Passes base64-encoded image to the multimodal AI model for analysis
6. Returns the AI's analysis text

---

## Deduplication

Per-user deduplication uses `(user_id, content_hash)` as the unique key. Records are
stored in the `upload_files` Directus collection. On a cache hit, the server returns the
existing `embed_id`, `aes_key`, S3 keys, and all metadata instantly — no re-upload, no
re-scan, no re-encryption.

**Cross-user deduplication is intentionally NOT implemented.** Different users who upload
the same file each get their own encrypted copy with their own AES key. This maintains
the per-user encryption model at the cost of some storage redundancy.

---

## Planned Phases

### Phase 2 — PDFs

- Add `pdf` app with `read` skill (text extraction + chapter TOC) and `view` skill
  (screenshot pages via pdf2image, passed to vision LLM)
- Update `app-uploads` to handle `application/pdf` MIME type

### Phase 3 — DOCX / XLSX

- Add macro malware scanning (LibreOffice headless + oletools)
- Add `docs` app skill for text extraction from DOCX
- Add `sheets` app skill for structured data extraction from XLSX
