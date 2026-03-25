---
status: active
last_verified: 2026-03-24
---

# Image Proxy — External Image Loading Rules

**NEVER load external images directly.** All third-party images must go through the preview server proxy for privacy, performance, and caching.

---

## Shared Utility

Import from `frontend/packages/ui/src/utils/imageProxy.ts`:

```typescript
import { proxyImage, proxyFavicon, getMetadataUrl, getYouTubeMetadataUrl } from '../../../utils/imageProxy';
import { MAX_WIDTH_FAVICON, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
```

### Functions

| Function | Endpoint | Use when |
|---|---|---|
| `proxyImage(url, maxWidth?)` | `/api/v1/image` | You have a direct image URL |
| `proxyFavicon(pageUrl)` | `/api/v1/favicon` | You only have a page URL, not a direct favicon URL |
| `getMetadataUrl(pageUrl)` | `/api/v1/metadata` | Fetching OG/Twitter Card metadata for a page |
| `getYouTubeMetadataUrl(videoUrl)` | `/api/v1/youtube` | Fetching YouTube video metadata |

### Max-Width Presets

| Constant | Value | Use case |
|---|---|---|
| `MAX_WIDTH_FAVICON` | 38 | Favicons (19px display, 2x retina) |
| `MAX_WIDTH_AIRLINE_LOGO` | 32 | Airline logos (16px display) |
| `MAX_WIDTH_AIRLINE_LOGO_FULLSCREEN` | 36 | Airline logos in fullscreen (18px) |
| `MAX_WIDTH_CHANNEL_THUMBNAIL` | 58 | Channel profile pics (29px display) |
| `MAX_WIDTH_PREVIEW_THUMBNAIL` | 520 | Preview card images (~260px container) |
| `MAX_WIDTH_VIDEO_PREVIEW` | 640 | Video preview thumbnails (~320px) |
| `MAX_WIDTH_CONTENT_IMAGE` | 800 | Article/web-read body images |
| `MAX_WIDTH_HEADER_IMAGE` | 1024 | Fullscreen header images (~511px) |
| `MAX_WIDTH_VIDEO_FULLSCREEN` | 1560 | Fullscreen video thumbnails (~780px) |

---

## Configuration

The preview server base URL is configured in `config/api.ts` via `getPreviewUrl()`:

- `VITE_PREVIEW_URL` — single URL for self-hosted deployments (takes precedence)
- `VITE_PREVIEW_URL_DEV` / `VITE_PREVIEW_URL_PROD` — environment-specific URLs
- Default: `https://preview.openmates.org`

---

## Anti-Patterns

```typescript
// WRONG — hardcoded domain
const url = `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(img)}`;

// WRONG — missing encodeURIComponent (proxyImage handles this internally)
const url = `${PREVIEW_SERVER}/api/v1/image?url=${img}`;

// WRONG — inline constant
const PREVIEW_SERVER = 'https://preview.openmates.org';

// CORRECT
import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
const url = proxyImage(img, MAX_WIDTH_PREVIEW_THUMBNAIL);
```

---

## Why We Proxy

1. **Privacy** — hides user IP from external image servers
2. **Performance** — server-side resizing reduces bandwidth
3. **Caching** — 7-day LRU disk cache on the preview server
