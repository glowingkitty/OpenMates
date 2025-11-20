# File Upload Architecture

> This document describes the planned file upload architecture with emphasis on bandwidth and storage optimization through content deduplication.

## Overview

The file upload system is designed with **zero-knowledge security and bandwidth efficiency** as core principles. Files are deduplicated at the validation level using cryptographic hashing (SHA-256). This enables:
- Same user uploading same file multiple times stores it once (per-user deduplication)
- Malware scanning happens once per unique content, not per user (validation deduplication)
- Each user's files encrypted with their own keys for zero-knowledge security
- Hash ensures file hasn't been corrupted or tampered with

## Upload Flow with Deduplication

**Client-Side (User Device):**
1. User selects file to upload
2. Calculate SHA-256 hash of file content on device
3. Derive encryption key: `encryption_key_file = HKDF(user_master_key, content_hash, salt="file")`
4. Encrypt file metadata fields individually with same key:
   - `encrypted_file_name = AES-256-GCM(file_name, encryption_key_file)`
   - `encrypted_mime_type = AES-256-GCM(mime_type, encryption_key_file)`
   - `encrypted_file_size = AES-256-GCM(file_size, encryption_key_file)`
5. Send: plaintext_file + encrypted_file_name + encrypted_mime_type + encrypted_file_size + fileHash + temp_encryption_key_file via websocket

**Server-Side:**
6. Receive plaintext file, encrypted metadata fields, hash, and encryption key
7. Check if file with this hash already exists:
   - **For same user (user_id + content_hash exists)**: Return existing fileId (no re-upload needed)
   - **For different user (content_hash exists, different user_id)**: Skip malware scan (already validated), proceed to step 11
   - **New file (content_hash doesn't exist)**: Proceed with full validation
8. Validate hash matches: `SHA256(plaintext_file) == content_hash`
9. **Malware scan** (only if new content_hash): Scan plaintext file for threats
10. Generate previews if applicable (PDF, image - requires plaintext)
11. Encrypt file: `encrypted_file = AES-256-GCM(plaintext_file, encryption_key_file)`
12. **IMMEDIATELY DISCARD** temp_encryption_key_file from memory
13. Store encrypted file to S3:
    - `s3://files/{user_id}/{content_hash}/file.bin` (encrypted file content)
14. Create database record with encrypted metadata fields:
    - `{file_id, user_id, content_hash, encrypted_file_name, encrypted_mime_type, encrypted_file_size, s3_key}`
15. Return fileId to client

## Architecture Components

### Upload Server (isolated Docker environment)

**Endpoints via websocket:**
- `upload:check` - Check if file exists by hash (pre-upload validation)
- `upload:file` - Upload file content (only if not already on server)
- `files:get` - Access uploaded file
- `preview:get` - Access file preview (for images/PDFs)

### Why Websockets?

Websockets are preferable over HTTP for file uploads in this architecture because:
- **Persistent connection**: Reduces overhead for pre-upload hash check + actual upload (both on same connection)
- **Real-time feedback**: Users see immediate response if file already exists
- **Streaming**: Large files can be streamed efficiently
- **Progress tracking**: Consistent with existing messaging/streaming infrastructure
- **Lower latency**: No connection establishment overhead for check-then-upload pattern

## File Deduplication Strategy

### Core Principle: Validation Deduplication + Per-User Encryption

Every file is identified by its SHA-256 hash for validation purposes, while encryption is per-user:

**What is Deduplicated:**
- ✅ **Malware scanning**: Same content hash = already scanned, skip scanning
- ✅ **Bandwidth for same user**: User re-uploading same file = instant return of existing fileId
- ✅ **Preview generation**: Same content already has previews generated

**What is NOT Deduplicated:**
- ❌ **Storage across users**: Different users store separately with their own encryption keys
- ❌ **Bandwidth across users**: Different users must upload file (but skip malware scan)

**Benefits:**
- **Zero-knowledge security**: Files encrypted per-user, server cannot decrypt without client keys
- **Validation efficiency**: Malware scanning happens once per unique content
- **Bandwidth savings for users**: Same user uploading same file multiple times = instant
- **Data integrity**: Hash validation ensures corruption detection
- **Acceptable storage tradeoff**: Security > storage optimization

## Implementation

### Client-Side

1. **Hash Calculation**: Calculate SHA-256 hash of file content on user device
2. **Key Derivation**: Derive encryption key from user's master key + content hash
   - `encryption_key_file = HKDF(user_master_key, content_hash, salt="file")`
   - Deterministic: Same user + same file always produces same key
   - User-specific: Different users produce different keys for same file
3. **Metadata Encryption**: Encrypt all file metadata fields individually with same key
   - `encrypted_file_name = AES-256-GCM(file_name, encryption_key_file)`
   - `encrypted_mime_type = AES-256-GCM(mime_type, encryption_key_file)`
   - `encrypted_file_size = AES-256-GCM(file_size, encryption_key_file)`
   - Prevents information leakage from metadata
4. **File Upload**: Send plaintext file + encrypted metadata fields + hash + temporary encryption key to server
   - Server uses key only for encryption after validation
   - Server discards key immediately after use

### Server-Side

1. **Deduplication Check**: Query database for (user_id, content_hash) combination
   - **Same user uploaded before**: Return existing fileId immediately (no work needed)
   - **Different user uploaded same file**: Skip malware scan (content already validated), encrypt with new user's key
   - **New content**: Proceed with full validation and encryption
2. **Hash Verification**: Validate `SHA256(plaintext_file) == content_hash`
3. **Malware Scanning** (only for new content_hash): Scan plaintext for threats once per unique content
4. **File Type Validation**: MIME type validation and size limits
5. **Encryption**: Encrypt both file and metadata using user-specific key
   - `encrypted_file = AES-256-GCM(plaintext_file, encryption_key_file)`
   - Metadata encrypted client-side, stored in Directus database
6. **Key Discarding**: **CRITICAL** - Immediately discard temp_encryption_key_file from memory
   - Never persist in any form (memory, disk, logs)
7. **Storage**: Store encrypted file to S3
   - `s3://files/{user_id}/{content_hash}/file.bin` - Encrypted file content
8. **Database Record**: Create Directus record with encrypted metadata
   - `{file_id, user_id, content_hash, encrypted_file_name, encrypted_mime_type, encrypted_file_size, s3_key}`
   - All metadata fields encrypted with file encryption key

## Database Schema

Files are stored in Directus collections using content-addressed storage. The schema is defined in YAML format.

**files.yml** - Core file storage metadata:
```yaml
files:
  type: collection
  fields:
    id:
      type: uuid
      note: "Primary Key - Unique identifier for the file"
    
    user_id:
      type: uuid
      note: "User who uploaded the file (plaintext for access control)"
    
    content_hash:
      type: string
      length: 64
      note: "SHA-256 hash of file content (plaintext for deduplication)"
      unique: true
    
    encrypted_file_name:
      type: string
      note: "[Encrypted] Original filename provided by uploader, encrypted with file encryption key"
    
    encrypted_mime_type:
      type: string
      note: "[Encrypted] File MIME type (e.g., image/png, application/pdf), encrypted with file encryption key"
    
    encrypted_file_size:
      type: integer
      note: "[Encrypted] Size of file in bytes, encrypted with file encryption key"
    
    s3_key:
      type: string
      note: "S3 storage path: s3://files/{user_id}/{content_hash}/file.bin (plaintext for storage access)"
    
    created_at:
      type: timestamp
      note: "When file was first uploaded to server"
```

**Note:** File metadata (name, MIME type, size) are encrypted in database using the same key that encrypts file content. This prevents metadata leakage even in database backups, following the same pattern as `encrypted_title` in chats collection.

**file_references.yml** - Allows multiple users to share same file without duplication:
```yaml
file_references:
  type: collection
  fields:
    id:
      type: uuid
      note: "Primary Key"
    
    user_id:
      type: uuid
      note: "User referencing the file"
    
    file_id:
      type: uuid
      note: "Reference to file in files collection"
    
    message_id:
      type: uuid
      note: "Optional - which message references this file"
    
    created_at:
      type: timestamp
      note: "When user added reference to file"
```

## Security Considerations

### Core Principles (Per-User Zero-Knowledge Encryption)

This architecture achieves zero-knowledge encryption while enabling server-side malware scanning:

- **Hash is plaintext**: Content hash stored in plaintext for malware scan deduplication
- **File is encrypted per-user**: Each user's files encrypted with their own derived key
- **Metadata is encrypted**: File name, MIME type, file size encrypted with same key as content
- **Keys never persist**: Encryption keys received temporarily, immediately discarded after use
- **Zero-knowledge**: Even if DB + Vault + S3 all leaked, files cannot be decrypted without user's master key
- **Malware scan deduplication**: Content scanned once per unique hash, not per user

### What Data is Encrypted vs Plaintext

**Encrypted (stored in Directus database):**
- ✅ encrypted_file_name
- ✅ encrypted_mime_type
- ✅ encrypted_file_size
- All encrypted with: `AES-256-GCM(data, encryption_key_file)`

**Encrypted (stored in S3):**
- ✅ File content

**Plaintext (stored in Directus database or S3):**
- ❌ content_hash - Needed for deduplication and validation
- ❌ user_id - Needed for access control
- ❌ s3_key - Needed for storage access
- ❌ created_at - Needed for queries

**Result:** Even if database backup is stolen, attackers only get plaintext metadata that doesn't reveal content (user_id, hash, timestamps). All sensitive metadata (file_name, type, size) is encrypted in database using user-specific keys.

### Why Plaintext Upload?

Files must be uploaded unencrypted because:
1. **Malware scanning requires plaintext** - Antivirus engines need actual file content to detect threats
2. **One-time scan per content**: Same file uploaded by different users only scanned once
3. **Preview generation requires plaintext** - Extracting pages from PDFs, generating thumbnails, etc.
4. **Server doesn't store plaintext** - Only encrypted result stored in S3
5. **Temporary key access** - Server encrypts then immediately discards key

### Compatibility with security.md

This follows the core zero-knowledge principle: **"server stores encrypted blobs it cannot decrypt"**

**Key Derivation (Client-Side):**
- `encryption_key_file = HKDF(user_master_key, content_hash, salt="file")`
- User-specific: Different users derive different keys
- Deterministic: Same user + same file always produces same key
- Client-controlled: Only client has user_master_key

**Upload Flow:**
1. Client derives encryption key from their master key
2. Client sends plaintext + temporary encryption key to server
3. Server validates and scans (only if new content)
4. Server encrypts with provided key
5. **Server immediately discards key** - never persisted anywhere
6. Result: Encrypted file in S3, but server cannot decrypt without client

**On file access:**
1. Client derives same encryption key (deterministic from user_master_key + content_hash)
2. Client sends temporary key to server
3. Server decrypts file from S3 using temporary key
4. Server streams decrypted file to client
5. Server immediately discards key

**Security Properties:**

- **Zero-Knowledge**: Server cannot decrypt files without temporary key from client
- **Database leak**: Contains only metadata (user_id, content_hash, s3_key), no decryption keys
- **Vault leak**: No file encryption keys stored in Vault
- **S3 leak**: Only encrypted files, useless without per-user keys
- **Full system compromise**: Still requires user's master_key to decrypt files
- **Malware Scanning**: Plaintext scanned before encryption, once per unique content
- **Hash Collision**: SHA-256 is cryptographically secure (collision probability negligible at 2^128)
- **Tampering Detection**: Hash verification ensures file integrity
- **No cross-user storage deduplication**: Different users store separately (acceptable tradeoff for privacy)

## CLI Integration (Non-Text Files)

When users reference files in CLI commands that aren't pure text (e.g., `openmates apps ai ask --files image.png,document.pdf`), the CLI handles file hashing:

1. **Local hashing**: CLI calculates SHA-256 hash of each referenced file
2. **Pre-flight check**: Sends hash to server to check if file exists
3. **Conditional upload**: Only uploads file if needed
4. **Reference in context**: File reference (with hash + fileId) is included in the request to the AI app

This ensures efficient handling of binary/non-text files without unnecessary re-uploads across CLI sessions or users.

## Benefits Summary

| Aspect | Benefit |
|--------|---------|
| **Security** | Zero-knowledge: Files encrypted per-user, server cannot decrypt without client |
| **Bandwidth (Same User)** | Instant response when user re-uploads same file |
| **Validation Efficiency** | Malware scanning once per unique content, not per user |
| **Performance** | Skip expensive operations (scanning, preview generation) for known content |
| **Integrity** | Hash verification prevents corruption/tampering |
| **Privacy** | Even full system compromise cannot decrypt files without user's master key |

---

## Generated File Metadata

All AI-generated files (PDFs, documents, audio, video, etc.) must include embedded metadata for transparency and reproducibility.

### Metadata for Generated Files

All generated content must embed:

**Required Fields:**
```json
{
  "metadata": {
    "generation": {
      "timestamp": "2025-11-17T14:32:00Z",
      "ai_model": {
        "name": "model_name",
        "provider": "anthropic|openai|etc",
        "version": "v1.0"
      },
      "prompt": {
        "original_prompt": "user's request",
        "system_prompt_hash": "sha256:...",
        "prompt_hash": "sha256:..."
      },
      "generation_parameters": {
        "temperature": 0.7,
        "max_tokens": 2048,
        "top_p": 0.9
      },
      "processing_time_ms": 1523,
      "generation_id": "gen_abc123def456"
    },
    "user_context": {
      "user_id": "anonymized_id",
      "app_context": "document_generation",
      "conversation_id": "conv_abc123"
    },
    "licensing": {
      "license": "CC0-1.0",
      "creator": "OpenMates AI",
      "terms": "User retains full ownership"
    },
    "integrity": {
      "file_hash": "sha256:xyz789...",
      "generation_verified": true,
      "verification_timestamp": "2025-11-17T14:32:00Z"
    }
  }
}
```

### PDF Documents

**Embedding Location:** PDF metadata stream + document properties

```xml
/Producer "OpenMates"
/Creator "OpenMates AI"
/CreationDate (D:20251117143200Z)
/Keywords "ai-generated, openmates"
/Metadata <stream with JSON>
```

**Libraries:**
- Python: `PyPDF2`, `reportlab`, `pypdf`
- JavaScript: `pdf-lib`, `pdfkit`

**User Experience:**
- Show generation info in PDF properties/metadata
- Display model and timestamp in document footer
- Allow export of metadata separately

### Audio Files (MP3, WAV, OGG)

**Embedding Locations:**

**MP3 - ID3v2 tags:**
```
TIT2 (Title) → Generation ID
COMM (Comments) → Processing metadata
TXXX frames:
  - "openmates_model" → model name
  - "openmates_timestamp" → generation time
  - "openmates_metadata" → full JSON (compressed)
```

**WAV - LIST INFO chunk:**
```
INFO chunk with custom fields:
  - IART (Artist) → "OpenMates AI"
  - ICMT (Comment) → Metadata JSON
  - ISFT (Software) → "OpenMates"
```

**OGG Vorbis - Vorbis comments:**
```
METADATA_BLOCK_VORBIS_COMMENT:
  - ARTIST = "OpenMates AI"
  - COMMENT = Generation metadata JSON
  - OPENMATES_MODEL = model name
  - OPENMATES_TIMESTAMP = timestamp
```

**Libraries:**
- Python: `mutagen`, `pydub`
- JavaScript: `music-metadata`, `mp3-metadata`

### Document Files (DOCX, ODT)

**DOCX - Custom XML properties:**
```xml
<Properties>
  <openmates:generation>JSON metadata</openmates:generation>
  <openmates:model>model_name</openmates:model>
  <openmates:timestamp>timestamp</openmates:timestamp>
  <dc:creator>OpenMates AI</dc:creator>
  <dcterms:created>timestamp</dcterms:created>
</Properties>
```

**Libraries:**
- Python: `python-docx`, `zipfile`
- JavaScript: `docx`, `pizzip`

### Video Files (MP4, WebM)

**Embedding Location:** MP4 metadata atoms or WebM metadata

**MP4 - `©cmt` (comment) atom:**
```
MP4 atoms:
  - `©ART` → "OpenMates AI"
  - `©cmt` → Generation metadata JSON
  - `©too` → "OpenMates Generator"
```

**WebM - Matroska tags:**
```
<Tag>
  <Targets><Type>SEGMENT</Type></Targets>
  <SimpleTag>
    <Name>COMMENT</Name>
    <String>Generation metadata</String>
  </SimpleTag>
</Tag>
```

**Libraries:**
- Python: `moviepy`, `mutagen`
- JavaScript: `ffmpeg.js`

---

## Processing Metadata for Uploaded Files

When users upload files that are processed/analyzed by AI systems, include processing results in metadata.

### Processing Metadata Structure

```json
{
  "metadata": {
    "processing": {
      "timestamp": "2025-11-17T14:35:00Z",
      "original_file": {
        "name": "document.pdf",
        "size_bytes": 1048576,
        "hash": "sha256:abc123...",
        "upload_timestamp": "2025-11-17T14:30:00Z"
      },
      "processing_modules": [
        {
          "name": "content_safety_classifier",
          "version": "1.2.3",
          "status": "completed",
          "processing_time_ms": 245
        },
        {
          "name": "ocr_processor",
          "version": "2.0.1",
          "status": "completed",
          "processing_time_ms": 523,
          "text_extracted": true,
          "accuracy": 0.96
        }
      ],
      "processing_id": "proc_def456ghi789"
    },
    "detection_results": {
      "content_safety": {
        "safe": true,
        "categories": {
          "violence": 0.02,
          "adult_content": 0.01,
          "hate_speech": 0.00
        }
      },
      "document_analysis": {
        "pages": 24,
        "language": "en",
        "sentiment": "neutral",
        "topics": ["business", "finance"]
      }
    },
    "processing_summary": {
      "file_status": "safe",
      "recommended_actions": [],
      "user_notification": "File processed and ready to use."
    }
  }
}
```

### User Download Experience

When downloading processed files:
1. Show "ℹ️ File Processed - View processing details"
2. Display safety summary and detected issues
3. Provide full metadata viewer
4. Option to export metadata as JSON

---

## Future Enhancements

- **Compression**: Store files compressed (gzip/brotli) for additional savings
- **Delta Encoding**: Store only differences for text/document versions
- **Lifecycle Management**: Auto-cleanup of unreferenced files after X days
- **Chunked Uploads**: Client-side chunking with progress tracking for large files
- **Blockchain Provenance**: Store metadata hash on blockchain for immutable verification
- **C2PA Integration**: Coalition for Content Provenance and Authenticity support
