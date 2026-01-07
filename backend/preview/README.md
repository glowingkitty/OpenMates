# OpenMates Preview Server

Image/favicon proxy and URL metadata extraction service for the OpenMates platform.

## Features

- **Image Proxy**: Fetch, resize, and cache images from external URLs
- **Favicon Proxy**: Fetch and cache website favicons
- **Metadata Extraction**: Extract Open Graph/Twitter Card metadata from URLs
- **Privacy**: Hides user IP from target servers
- **Security**: SSRF protection, content validation, optional API key auth
- **Performance**: Disk-based LRU caching with configurable limits

## Quick Start

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run with hot reload
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### Docker (Standalone)

```bash
# Build and run
docker compose -f docker-compose.preview.yml up

# Production (detached)
docker compose -f docker-compose.preview.yml up -d
```

### Self-Hosted (Main Stack)

Uncomment the `preview` service in `backend/core/docker-compose.yml`.

## API Endpoints

### `GET /api/v1/image`

Fetch and resize images.

```bash
# Basic usage
curl "http://localhost:8080/api/v1/image?url=https://example.com/photo.jpg"

# With resizing
curl "http://localhost:8080/api/v1/image?url=https://example.com/photo.jpg&max_width=800&max_height=600"

# With quality adjustment
curl "http://localhost:8080/api/v1/image?url=https://example.com/photo.jpg&quality=75"
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | required | Image URL to fetch |
| `max_width` | int | 1920 | Maximum width (0 = no limit) |
| `max_height` | int | 1080 | Maximum height (0 = no limit) |
| `quality` | int | 85 | JPEG/WebP quality (1-100) |
| `format` | string | auto | Output format (jpeg, png, webp) |
| `refresh` | bool | false | Bypass cache |

### `GET /api/v1/favicon`

Fetch website favicon.

```bash
curl "http://localhost:8080/api/v1/favicon?url=https://github.com"
```

### `POST /api/v1/metadata`

Extract website metadata.

```bash
curl -X POST "http://localhost:8080/api/v1/metadata" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/openai"}'
```

**Response:**
```json
{
  "url": "https://github.com/openai",
  "title": "OpenAI",
  "description": "OpenAI is an AI research and deployment company...",
  "image": "https://github.githubassets.com/images/modules/open_graph/github-octocat.png",
  "favicon": "https://github.com/favicon.ico",
  "site_name": "GitHub"
}
```

### `GET /api/v1/youtube`

Extract YouTube video metadata.

```bash
# Using full URL
curl "http://localhost:8080/api/v1/youtube?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Using video ID only
curl "http://localhost:8080/api/v1/youtube?url=dQw4w9WgXcQ"
```

**Supported URL formats:**
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`
- Just the 11-character video ID

**Response:**
```json
{
  "video_id": "dQw4w9WgXcQ",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "Rick Astley - Never Gonna Give You Up",
  "description": "The official video for \"Never Gonna Give You Up\"...",
  "channel_name": "Rick Astley",
  "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
  "thumbnails": {
    "default": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
    "medium": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
    "high": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "standard": "https://i.ytimg.com/vi/dQw4w9WgXcQ/sddefault.jpg",
    "maxres": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
  },
  "duration": {
    "total_seconds": 212,
    "formatted": "3:32"
  },
  "view_count": 1500000000,
  "like_count": 15000000,
  "published_at": "2009-10-25T06:57:33Z"
}
```

**API Quota:**
- Cost: 1 quota unit per unique video
- Daily limit: 10,000 units (free tier)
- Results cached for 24 hours

### `GET /health`

Health check for load balancers.

### `GET /health/detailed`

Detailed health with cache statistics.

## Configuration

Set environment variables as needed. The preview server uses the `PREVIEW_` prefix for most settings, but reuses the main backend's `SECRET__WEBSHARE__*` credentials for proxy configuration.

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PREVIEW_PORT` | 8080 | Server port |
| `UVICORN_WORKERS` | 4 | Worker processes for concurrent image processing |
| `PREVIEW_ENVIRONMENT` | development | Environment name |
| `PREVIEW_DEBUG` | false | Enable debug mode (API docs) |
| `PREVIEW_LOG_LEVEL` | INFO | Log level |
| `PREVIEW_CACHE_DIR` | /app/cache | Cache directory |
| `PREVIEW_CACHE_MAX_SIZE_MB` | 10240 | Image cache size limit (10GB) |
| `PREVIEW_METADATA_CACHE_MAX_SIZE_MB` | 500 | Metadata cache size limit (500MB) |
| `PREVIEW_MAX_IMAGE_WIDTH` | 1920 | Default max image width |
| `PREVIEW_MAX_IMAGE_HEIGHT` | 1080 | Default max image height |
| `PREVIEW_JPEG_QUALITY` | 85 | Default JPEG quality |
| `PREVIEW_BLOCK_PRIVATE_IPS` | true | SSRF protection |
| `PREVIEW_CORS_ORIGINS` | see below | Allowed CORS origins |
| `PREVIEW_API_KEY` | (empty) | Optional API key for auth |
| `PREVIEW_VALIDATE_REFERER` | true | Enable Referer header validation |
| `PREVIEW_ALLOWED_REFERERS` | see below | Allowed Referer patterns |

### Webshare Proxy (RECOMMENDED)

For reliable metadata fetching, configure Webshare rotating residential proxy. Without a proxy, many websites will block direct server requests.

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET__WEBSHARE__PROXY_USERNAME` | (empty) | Webshare username (same as main backend) |
| `SECRET__WEBSHARE__PROXY_PASSWORD` | (empty) | Webshare password (same as main backend) |
| `PREVIEW_USE_PROXY_FOR_METADATA` | true | Use proxy for HTML/metadata fetching |
| `PREVIEW_USE_PROXY_FOR_IMAGES` | false | Use proxy for image fetching |

Get credentials from: https://webshare.io/

### YouTube API (For Video Metadata)

To enable YouTube video metadata extraction, configure a YouTube Data API v3 key.

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET__YOUTUBE__API_KEY` | (empty) | YouTube Data API v3 key (same as main backend) |
| `PREVIEW_YOUTUBE_API_KEY` | (empty) | Alternative: preview-specific key |
| `PREVIEW_YOUTUBE_CACHE_TTL_SECONDS` | 86400 | YouTube metadata cache TTL (24 hours) |

**Setup:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new project or select existing
3. Enable "YouTube Data API v3" in the [API Library](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
4. Create an API key in Credentials
5. Set `SECRET__YOUTUBE__API_KEY` in your `.env`

**Quota:**
- Free tier: 10,000 units/day
- `videos.list` costs: 1 unit per request
- With 24-hour caching: ~10,000 unique videos/day

**Note:** The preview server accepts credentials in two formats:
- `SECRET__WEBSHARE__PROXY_USERNAME` / `SECRET__WEBSHARE__PROXY_PASSWORD` (same as main backend, for shared `.env`)
- `PREVIEW_WEBSHARE_USERNAME` / `PREVIEW_WEBSHARE_PASSWORD` (preview-specific with prefix)

The first format matching will be used.

## Architecture

```
backend/preview/
├── main.py              # FastAPI application entry point
├── app/
│   ├── config.py        # Configuration settings
│   ├── routes/          # API route handlers
│   │   ├── favicon.py   # Favicon proxy endpoint
│   │   ├── image.py     # Image proxy endpoint
│   │   ├── metadata.py  # Metadata extraction endpoint
│   │   └── health.py    # Health check endpoints
│   └── services/        # Business logic
│       ├── cache_service.py    # Disk-based LRU caching
│       ├── fetch_service.py    # External URL fetching with SSRF protection
│       ├── image_service.py    # Image resizing and optimization
│       └── metadata_service.py # Open Graph metadata parsing
├── Dockerfile           # Docker image definition
├── docker-compose.preview.yml  # Standalone deployment
└── requirements.txt     # Python dependencies
```

## Security

- **Referer Validation**: Blocks requests not originating from your domains (prevents hotlinking)
- **SSRF Protection**: Blocks requests to private/internal IP addresses
- **Content Validation**: Validates MIME types and enforces size limits
- **No Tracking**: Doesn't forward cookies or referrers to target servers
- **API Key Auth**: Optional authentication via `X-API-Key` header
- **Rate Limiting**: Recommended at Caddy/reverse proxy level

### Referer Validation

By default, the preview server validates the `Referer` header to ensure requests come from your domains. This prevents other websites from hotlinking your preview server.

**Configuration:**
```bash
# Enable/disable referer validation
PREVIEW_VALIDATE_REFERER=true

# Allowed referer patterns (supports wildcards)
PREVIEW_ALLOWED_REFERERS=https://openmates.org/*,https://*.openmates.org/*,http://localhost:*/*
```

**Note:** Empty referers are always allowed (for privacy settings and direct navigation). Referer headers can be spoofed by non-browser clients, so combine with rate limiting for full protection.

## Deployment

### Production (Separate VM)

1. Set up a VM at `preview.openmates.org`
2. Copy `backend/preview/` to the VM
3. Configure environment variables in `.env`
4. Run with Docker Compose:
   ```bash
   docker compose -f docker-compose.preview.yml up -d
   ```
5. Set up Caddy reverse proxy with SSL:
   ```bash
   # Copy and configure the Caddyfile
   cp Caddyfile.example Caddyfile
   # Edit Caddyfile: replace <YOUR_EMAIL>, <PREVIEW_DOMAIN>, <PREVIEW_UPSTREAM>
   
   # Install Caddy (if not installed)
   sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
   sudo apt update && sudo apt install caddy
   
   # Apply configuration
   sudo cp Caddyfile /etc/caddy/Caddyfile
   sudo systemctl reload caddy
   ```

### Self-Hosted (Same Server)

1. Uncomment the `preview` service in `backend/core/docker-compose.yml`
2. Uncomment the `preview-cache` volume
3. Restart the stack: `docker compose up -d`

## Cache Management

The server uses **disk-based caching** (via `diskcache`) with automatic LRU eviction. No Redis/Dragonfly needed.

- **Images**: 10GB default, 7-day TTL
- **Favicons**: 1GB default, 7-day TTL
- **Metadata**: 500MB default, 24-hour TTL

When cache exceeds size limit, least-recently-used entries are automatically deleted.

View cache statistics:
```bash
curl "http://localhost:8080/health/cache"
```

## Concurrency

The server runs **4 uvicorn workers** by default for parallel image processing:

```bash
# Adjust workers based on your VM resources
UVICORN_WORKERS=4  # Default: 4 concurrent image processing tasks
```

| Workers | RAM Usage | Concurrent Processing |
|---------|-----------|----------------------|
| 2 | ~800MB | 2 images at once |
| 4 | ~1.5GB | 4 images at once (default) |
| 8 | ~3GB | 8 images at once |

## Recommended Hardware

**Hetzner CAX11** (€3.79/month):
- 2 ARM cores, 4GB RAM, 40GB SSD
- Supports 4 workers + 10GB cache
- Sufficient for moderate traffic

