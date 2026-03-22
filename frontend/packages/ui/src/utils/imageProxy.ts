// frontend/packages/ui/src/utils/imageProxy.ts
//
// Shared image proxy utility for the preview server.
// ALL external images (thumbnails, favicons, avatars) MUST be loaded through this
// proxy to protect user privacy (hides IP), optimize bandwidth (resizing), and
// improve performance (7-day server-side cache).
//
// Architecture: See docs/architecture/servers.md, docs/claude/image-proxy.md
// Tests: None yet — frontend utility, verified via component usage.

import { getPreviewUrl } from "../config/api";

// =============================================================================
// Preview Server Base URL (resolved once at module load)
// =============================================================================

const PREVIEW_BASE = getPreviewUrl();

// =============================================================================
// Image Proxy — /api/v1/image
// =============================================================================

/**
 * Proxy an external image URL through the preview server.
 *
 * @param url       - Original external image URL
 * @param maxWidth  - Maximum width in px (server default: 1920 if omitted)
 * @returns Proxied URL, or empty string if url is falsy
 *
 * @example
 *   proxyImage(result.thumbnail_url, 520)
 *   // → "https://preview.openmates.org/api/v1/image?url=...&max_width=520"
 */
export function proxyImage(
  url: string | undefined | null,
  maxWidth?: number,
): string {
  if (!url) return "";
  // Avoid double-proxying
  if (url.startsWith(`${PREVIEW_BASE}/api/v1/image`) || url.startsWith("data:")) {
    return url;
  }
  const params = new URLSearchParams({ url });
  if (maxWidth !== undefined) {
    params.set("max_width", maxWidth.toString());
  }
  return `${PREVIEW_BASE}/api/v1/image?${params.toString()}`;
}

// =============================================================================
// Favicon Proxy — /api/v1/favicon
// =============================================================================

/**
 * Get a favicon for a page URL via the preview server's favicon extractor.
 * Use this when you only have a page URL and no direct favicon URL.
 * If you already have a direct favicon URL, use `proxyImage(faviconUrl, 38)` instead.
 *
 * @param pageUrl - The webpage URL to extract a favicon from
 * @returns Proxied favicon URL, or empty string if pageUrl is falsy
 */
export function proxyFavicon(pageUrl: string | undefined | null): string {
  if (!pageUrl) return "";
  return `${PREVIEW_BASE}/api/v1/favicon?url=${encodeURIComponent(pageUrl)}`;
}

// =============================================================================
// Metadata Endpoint — /api/v1/metadata
// =============================================================================

/**
 * Get the metadata endpoint URL for a given page URL.
 * Extracts title, description, image, favicon, site_name via OG/Twitter Card tags.
 *
 * @param pageUrl - The webpage URL to fetch metadata for
 * @returns Full metadata endpoint URL
 */
export function getMetadataUrl(pageUrl: string): string {
  return `${PREVIEW_BASE}/api/v1/metadata?url=${encodeURIComponent(pageUrl)}`;
}

// =============================================================================
// YouTube Metadata Endpoint — /api/v1/youtube
// =============================================================================

/**
 * Get the YouTube metadata endpoint URL for a given video URL.
 * Extracts title, channel_name, channel_thumbnail, etc.
 *
 * @param videoUrl - YouTube video URL
 * @returns Full YouTube metadata endpoint URL
 */
export function getYouTubeMetadataUrl(videoUrl: string): string {
  return `${PREVIEW_BASE}/api/v1/youtube?url=${encodeURIComponent(videoUrl)}`;
}

// =============================================================================
// Common max_width presets (document why each value exists)
// =============================================================================

/** Favicon / small icon: 19x19 display, 2x retina = 38px */
export const MAX_WIDTH_FAVICON = 38;
/** Airline logo: 16x16 display, 2x retina = 32px */
export const MAX_WIDTH_AIRLINE_LOGO = 32;
/** Small airline logo in fullscreen segments: 18x18, 2x = 36px */
export const MAX_WIDTH_AIRLINE_LOGO_FULLSCREEN = 36;
/** Channel thumbnail (circular): 29x29 display, 2x retina = 58px */
export const MAX_WIDTH_CHANNEL_THUMBNAIL = 58;
/** Preview card thumbnail: ~260px container, 2x retina = 520px */
export const MAX_WIDTH_PREVIEW_THUMBNAIL = 520;
/** Video preview thumbnail: ~320px container, 2x retina = 640px */
export const MAX_WIDTH_VIDEO_PREVIEW = 640;
/** Fullscreen content images: article/web-read body = 800px */
export const MAX_WIDTH_CONTENT_IMAGE = 800;
/** Fullscreen header images: ~511px container, 2x retina = 1024px */
export const MAX_WIDTH_HEADER_IMAGE = 1024;
/** Fullscreen video thumbnail: ~780px container, 2x retina = 1560px */
export const MAX_WIDTH_VIDEO_FULLSCREEN = 1560;
