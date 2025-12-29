# Issue Reporting System

## Overview

The issue reporting system allows users (including non-authenticated users) to report issues. Issue reports are:

- Sent via email to the server admin
- Stored in the database with encrypted sensitive fields
- Archived as encrypted YAML files in Hetzner S3

## Architecture

### Data Flow

1. **User submits issue** via `/v1/settings/issues` endpoint
2. **Sensitive fields are encrypted** server-side:
   - Contact email
   - Chat/embed URL
   - Estimated location
   - Device info
3. **Issue record created** in Directus `issues` collection
4. **Email task processes** the issue:
   - Creates consolidated YAML file with all issue data
   - Encrypts YAML file
   - Uploads encrypted YAML to Hetzner S3 (`issue_logs` bucket)
   - Updates database with encrypted S3 object key
   - Sends email with YAML attachment to admin

### Database Schema

The `issues` collection stores:

- **Cleartext** (for text search): `title`, `description`
- **Encrypted**: `encrypted_contact_email`, `encrypted_chat_or_embed_url`, `encrypted_estimated_location`, `encrypted_device_info`, `encrypted_issue_report_yaml_s3_key`
- **Metadata**: `timestamp`, `created_at`, `updated_at`

### Encryption

All sensitive fields are encrypted using the system-level `issue_report_emails` Vault transit key, allowing server-side decryption for admin access.

## Internal API

The internal API endpoints are only accessible from within the Docker network using the `INTERNAL_API_SHARED_TOKEN`.

### Quick Reference

```bash
# Get authentication token
TOKEN=$(docker exec api printenv INTERNAL_API_SHARED_TOKEN)

# List all issues
docker exec api curl -s -H "X-Internal-Service-Token: ${TOKEN}" \
  http://localhost:8000/internal/issues | python3 -m json.tool

# Search issues
docker exec api curl -s -H "X-Internal-Service-Token: ${TOKEN}" \
  "http://localhost:8000/internal/issues?search=keyword" | python3 -m json.tool

# Get specific issue with logs
docker exec api curl -s -H "X-Internal-Service-Token: ${TOKEN}" \
  "http://localhost:8000/internal/issues/{issue_id}?include_logs=true" | python3 -m json.tool
```

### Endpoints

#### List Issues

```bash
GET /internal/issues?search=<text>&limit=100&offset=0
```

**Query Parameters:**

- `search` (optional): Text to search for in issue titles (case-insensitive)
- `limit` (optional, default: 100, max: 1000): Number of issues to return
- `offset` (optional, default: 0): Pagination offset

**Response:** List of issues with decrypted sensitive fields (logs not included)

#### Get Single Issue

```bash
GET /internal/issues/{issue_id}?include_logs=true
```

**Query Parameters:**

- `include_logs` (optional, default: false): If `true`, fetches and decrypts the YAML file from S3 and extracts console logs

**Response:** Issue details with decrypted fields (and optionally console logs)

### Usage via Docker Exec

All requests must be made from within the Docker network. The easiest way is to use `docker exec` to run curl inside the `api` container.

#### Getting the Authentication Token

The token is stored in the `api` container's environment. You can retrieve it using:

```bash
# Get the token from the container
docker exec api printenv INTERNAL_API_SHARED_TOKEN
```

Alternatively, if you have `INTERNAL_API_SHARED_TOKEN` set in your local environment, you can use `${INTERNAL_API_SHARED_TOKEN}` in the commands below.

#### List All Issues

```bash
# From the project root, navigate to backend/core directory
cd backend/core

# Get the token (replace with actual token or use environment variable)
TOKEN=$(docker exec api printenv INTERNAL_API_SHARED_TOKEN)

# List all issues (pretty-printed JSON)
docker exec api curl -s -H "X-Internal-Service-Token: ${TOKEN}" \
  http://localhost:8000/internal/issues | python3 -m json.tool
```

**One-liner version:**

```bash
docker exec api curl -s -H "X-Internal-Service-Token: $(docker exec api printenv INTERNAL_API_SHARED_TOKEN)" \
  http://localhost:8000/internal/issues | python3 -m json.tool
```

#### Search Issues by Title

```bash
cd backend/core
TOKEN=$(docker exec api printenv INTERNAL_API_SHARED_TOKEN)

# Search for issues containing "login" in the title
docker exec api curl -s -H "X-Internal-Service-Token: ${TOKEN}" \
  "http://localhost:8000/internal/issues?search=login" | python3 -m json.tool
```

**With pagination:**

```bash
docker exec api curl -s -H "X-Internal-Service-Token: ${TOKEN}" \
  "http://localhost:8000/internal/issues?search=login&limit=50&offset=0" | python3 -m json.tool
```

#### Get Specific Issue (without logs)

```bash
cd backend/core
TOKEN=$(docker exec api printenv INTERNAL_API_SHARED_TOKEN)

# Replace {issue_id} with the actual issue UUID
docker exec api curl -s -H "X-Internal-Service-Token: ${TOKEN}" \
  "http://localhost:8000/internal/issues/9321b002-b7d0-4238-82f2-49c4c933d0b2" | python3 -m json.tool
```

#### Get Specific Issue (with logs)

```bash
cd backend/core
TOKEN=$(docker exec api printenv INTERNAL_API_SHARED_TOKEN)

# Include console logs from the encrypted YAML file
docker exec api curl -s -H "X-Internal-Service-Token: ${TOKEN}" \
  "http://localhost:8000/internal/issues/9321b002-b7d0-4238-82f2-49c4c933d0b2?include_logs=true" | python3 -m json.tool
```

### Authentication

All internal API requests require the `X-Internal-Service-Token` header with the value from the `INTERNAL_API_SHARED_TOKEN` environment variable. The token can be retrieved from the running container using:

```bash
docker exec api printenv INTERNAL_API_SHARED_TOKEN
```

**Note:** The `python3 -m json.tool` pipe at the end of each command formats the JSON response for readability. Remove it if you want raw JSON output.

### Response Format

```json
{
  "id": "uuid",
  "title": "Issue title",
  "description": "Issue description",
  "chat_or_embed_url": "https://...",  // Decrypted
  "contact_email": "user@example.com",  // Decrypted
  "timestamp": "2024-01-01T12:00:00Z",
  "estimated_location": "City, Region, Country",  // Decrypted
  "device_info": "Browser & OS: ...",  // Decrypted
  "console_logs": "..."  // Only if include_logs=true
  "created_at": "2024-01-01T12:00:00Z",
  "updated_at": "2024-01-01T12:00:00Z"
}
```

## S3 Storage

Encrypted YAML files are stored in the `issue_logs` S3 bucket:

- **Path pattern**: `issue-reports/{timestamp}_{uuid}.yaml.encrypted`
- **Encryption**: Server-side encryption using `issue_report_emails` Vault key
- **Retention**: 1 year (lifecycle policy)
- **Access**: Private (only accessible via internal API with proper authentication)

## Security Notes

- All sensitive fields are encrypted at rest in the database
- YAML files are encrypted before upload to S3
- Internal API requires Docker network access and shared token
- Console logs are only included in API responses when explicitly requested (`include_logs=true`)
- Email attachments contain the same YAML data (base64 encoded, not encrypted)
