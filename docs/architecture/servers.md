# Server architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

## API server

- docker compose consisting of
	- core-api docker
	- core-api-task-worker docker
	- directus docker
	- dragonfly docker
	- grafana docker
	- Loki docker
	- Prometheus docker
	- celery task-scheduler docker
	- app-ai docker
		- with docker network internal fast api endpoints for each skill and each focus mode
		- /skill/ask
			- used every time a user is messaging a digital team mate
	- app-ai-task-worker docker
		- celery task worker for processing longer running tasks (like /skill/ask)
	- for each additional app, we add two dockers:
		- app-{appname} docker
			- with docker network internal fast api endpoints for each skill and each focus mode
			- serves as the API container for the app
			- handles incoming skill execution requests
			- routes requests to appropriate skill handlers
		- app-{appname}-task-worker docker
			- celery task worker for processing longer running tasks
			- processes skill executions asynchronously
			- handles external API calls and long-running operations
		- for the apps web, videos, sheets, docs, etc.

**Two-Container Pattern:**
Each app follows a consistent two-container architecture:
- **API Container**: FastAPI server that receives and routes skill execution requests
- **Celery Worker Container**: Background task processor for asynchronous skill execution

This separation allows:
- **Scalability**: Scale API and workers independently based on load
- **Reliability**: Worker failures don't affect API availability
- **Resource Management**: Different resource limits for API vs. workers
- **Service Discovery**: Apps are automatically discovered via Docker network

For more details on app architecture, see [Apps Architecture](./apps/README.md).


## uploads server

- isolated docker environment to process files
- public /upload endpoint
	- validate user
	- check if file is within file size limit
	- check for harmful uploaded files
	- if pdf or image file: create preview image
	- upload preview and original to S3 hetzner and return file id to frontend?
- public /files endpoint
	- validate user
	- gets hetzner s3 url for file and does a 302 redirect to the hetzner s3 url
- public /preview endpoint
	- validate use
	- checks if hetzner s3 url for preview image for the file exists and if so, makes 302 forward to the hetzner s3 url

## preview server

The preview server provides image/favicon proxying and URL metadata extraction for privacy, security, and performance benefits. It runs at `preview.openmates.org`.

**Implementation:** `backend/preview/`

### Deployment Options

1. **Cloud (Production):** Runs on a separate VM at `preview.openmates.org` for security isolation and independent scaling.
   - Use `backend/preview/docker-compose.preview.yml`
   
2. **Self-hosted:** Can be included in the main docker-compose stack (uncomment the preview service in `backend/core/docker-compose.yml`)

### Endpoints

#### `GET /api/v1/image`
Fetches, resizes, and caches images from external URLs.

**Query Parameters:**
- `url` (required): Image URL to fetch
- `max_width` (optional): Maximum width in pixels (0 = no limit, default: 1920)
- `max_height` (optional): Maximum height in pixels (0 = no limit, default: 1080)
- `quality` (optional): JPEG/WebP quality 1-100 (default: 85)
- `format` (optional): Force output format (jpeg, png, webp)
- `refresh` (optional): Bypass cache and fetch fresh

**Example:**
```
GET /api/v1/image?url=https://example.com/photo.jpg&max_width=800&quality=80
```

**Features:**
- Automatic resizing with aspect ratio preservation
- JPEG/WebP quality optimization
- Disk-based LRU cache (10GB default)
- SSRF protection (blocks private IPs)
- 7-day cache TTL
- 4 concurrent workers for parallel processing

#### `GET /api/v1/favicon`
Fetches and caches website favicons.

**Query Parameters:**
- `url` (required): Website URL (not favicon URL)
- `refresh` (optional): Bypass cache

**Example:**
```
GET /api/v1/favicon?url=https://github.com
```

**Features:**
- Tries `/favicon.ico` first, falls back to Google Favicon Service
- Disk-based caching with 7-day TTL

#### `POST /api/v1/metadata`
Extracts Open Graph and HTML metadata from websites.

**Request Body:**
```json
{
  "url": "https://example.com/article"
}
```

**Response:**
```json
{
  "url": "https://example.com/article",
  "title": "Article Title",
  "description": "Article description...",
  "image": "https://example.com/og-image.jpg",
  "favicon": "https://example.com/favicon.ico",
  "site_name": "Example.com"
}
```

**Features:**
- Extracts og:title, og:description, og:image, twitter:* tags
- Falls back to HTML title and meta description
- 24-hour cache TTL

#### `GET /health`
Health check endpoint for load balancers.

#### `GET /health/detailed`
Detailed health check with cache statistics.

### Security Features

- **Referer Validation:** Blocks requests from unauthorized domains (prevents hotlinking)
- **SSRF Protection:** Blocks requests to private/internal IP addresses
- **Content Validation:** Validates content types and size limits
- **Rate Limiting:** Configurable rate limits per IP (at Caddy level recommended)
- **API Key Auth:** Optional API key authentication

### Configuration

Environment variables (prefix: `PREVIEW_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `PREVIEW_PORT` | 8080 | Server port |
| `UVICORN_WORKERS` | 4 | Number of worker processes (concurrent image processing) |
| `PREVIEW_CACHE_DIR` | /app/cache | Cache directory |
| `PREVIEW_CACHE_MAX_SIZE_MB` | 10240 | Image cache size (10GB) |
| `PREVIEW_METADATA_CACHE_MAX_SIZE_MB` | 500 | Metadata cache size (500MB) |
| `PREVIEW_MAX_IMAGE_WIDTH` | 1920 | Default max image width |
| `PREVIEW_MAX_IMAGE_HEIGHT` | 1080 | Default max image height |
| `PREVIEW_JPEG_QUALITY` | 85 | Default JPEG quality |
| `PREVIEW_BLOCK_PRIVATE_IPS` | true | SSRF protection |
| `PREVIEW_CORS_ORIGINS` | (see config) | Allowed CORS origins |
| `PREVIEW_VALIDATE_REFERER` | true | Enable Referer validation |
| `PREVIEW_ALLOWED_REFERERS` | (see config) | Allowed Referer patterns |
| `PREVIEW_API_KEY` | (empty) | Optional API key |

### Cache Architecture

All caches are **disk-based** using `diskcache` (SQLite index + file storage). No Redis/Dragonfly needed.

- **Images:** Disk-based LRU cache, 10GB default, 7-day TTL
- **Favicons:** Separate LRU cache, 1GB, 7-day TTL  
- **Metadata:** Separate LRU cache, 500MB, 24-hour TTL

Cache keys include processing parameters, so different sizes of the same image are cached separately.

### Concurrency

The server runs **4 uvicorn workers** by default, allowing 4 concurrent image processing tasks. Each worker:
- Uses ~200-300MB RAM when processing
- Shares the same disk cache (thread-safe)
- Can be scaled via `UVICORN_WORKERS` environment variable

### Recommended Hardware

**Hetzner CAX11** (€3.79/month):
- 2 ARM cores, 4GB RAM, 40GB SSD
- Handles 4 concurrent image processing + 10GB cache
- Sufficient for moderate traffic