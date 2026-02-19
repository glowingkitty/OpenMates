// =============================================================================
// URL Metadata Service
// =============================================================================
// Service for fetching URL metadata and creating proper embeds for websites/videos.
//
// This service handles:
// - Fetching metadata from preview.openmates.org
// - Generating embed_id for proper embed references
// - Encoding content as TOON for storage efficiency
// - Storing embeds in EmbedStore for client-side access
// - Creating proper embed reference format for message content
//
// The key insight: When user pastes a URL, we need to create a PROPER embed
// with embed_id so that:
// 1. The embed can be sent to the server with the message
// 2. The server can cache it for LLM inference
// 3. The embed can be resolved and displayed in the UI
// =============================================================================

import { encode as toonEncode } from "@toon-format/toon";
import { get } from "svelte/store";
import { embedStore } from "../../../services/embedStore";
import { generateUUID } from "../../../message_parsing/utils";
import { userProfile } from "../../../stores/userProfile";

// =============================================================================
// Types
// =============================================================================

/**
 * Basic URL metadata returned from preview server
 */
export interface UrlMetadata {
  type: "website";
  url: string;
  title?: string;
  description?: string;
  favicon?: string;
  image?: string;
  site_name?: string;
}

/**
 * YouTube video metadata returned from preview server
 */
export interface YouTubeMetadata {
  type: "video";
  url: string;
  video_id: string;
  title?: string;
  description?: string;
  channel_name?: string;
  channel_id?: string;
  channel_thumbnail?: string; // Channel profile picture URL (fetched from channels.list API)
  thumbnails?: {
    default?: string;
    medium?: string;
    high?: string;
    standard?: string;
    maxres?: string;
  };
  duration?: {
    total_seconds: number;
    formatted: string;
  };
  view_count?: number;
  like_count?: number;
  published_at?: string;
}

/**
 * Result of creating an embed from URL metadata
 * Contains the embed_id and the markdown reference to insert
 */
export interface EmbedCreationResult {
  embed_id: string;
  type: "website" | "video";
  embedReference: string; // The JSON code block to insert: ```json\n{"type": "...", "embed_id": "..."}\n```
}

// =============================================================================
// Preview Server API
// =============================================================================

const PREVIEW_SERVER_URL = "https://preview.openmates.org";

/**
 * Fetches metadata for a given URL from preview.openmates.org
 * Uses the /api/v1/metadata endpoint which extracts:
 * - Title (from og:title, twitter:title, or <title>)
 * - Description (from og:description, twitter:description, or meta description)
 * - Image (from og:image or twitter:image)
 * - Favicon (link rel="icon", rel="shortcut icon")
 * - Site name (from og:site_name)
 *
 * @param url The URL to fetch metadata for
 * @returns Promise with metadata or null if failed
 */
export async function fetchUrlMetadata(
  url: string,
): Promise<UrlMetadata | null> {
  try {
    console.debug("[urlMetadataService] Fetching metadata for URL:", url);

    // Use GET endpoint to avoid CORS preflight (POST with JSON requires OPTIONS preflight)
    const response = await fetch(
      `${PREVIEW_SERVER_URL}/api/v1/metadata?url=${encodeURIComponent(url)}`,
    );

    if (!response.ok) {
      console.warn(
        "[urlMetadataService] Failed to fetch metadata:",
        response.status,
        response.statusText,
      );
      return null;
    }

    const data = await response.json();

    // Validate the response structure - title and description are optional
    if (!data || typeof data !== "object") {
      console.warn("[urlMetadataService] Invalid metadata response:", data);
      return null;
    }

    const metadata: UrlMetadata = {
      type: "website",
      url: url,
      title: typeof data.title === "string" ? data.title : undefined,
      description:
        typeof data.description === "string" ? data.description : undefined,
      favicon: data.favicon,
      image: data.image,
      site_name: data.site_name,
    };

    console.info("[urlMetadataService] Successfully fetched metadata:", {
      url,
      title: metadata.title?.substring(0, 50) + "..." || "No title",
      description:
        metadata.description?.substring(0, 100) + "..." || "No description",
    });

    return metadata;
  } catch (error) {
    console.error("[urlMetadataService] Error fetching URL metadata:", error);
    return null;
  }
}

/**
 * Fetches metadata for a YouTube video from preview.openmates.org
 * Uses the /api/v1/youtube endpoint which extracts:
 * - Video title, description, channel info
 * - Thumbnails at multiple resolutions
 * - Duration, view count, like count
 * - Publication date
 *
 * @param url The YouTube URL to fetch metadata for
 * @returns Promise with metadata or null if failed
 */
export async function fetchYouTubeMetadata(
  url: string,
): Promise<YouTubeMetadata | null> {
  try {
    console.debug(
      "[urlMetadataService] Fetching YouTube metadata for URL:",
      url,
    );

    // Use GET endpoint for YouTube metadata
    const response = await fetch(
      `${PREVIEW_SERVER_URL}/api/v1/youtube?url=${encodeURIComponent(url)}`,
    );

    if (!response.ok) {
      // Log quota/rate-limit failures distinctly so they're easy to spot in the
      // console when debugging — these are expected and handled gracefully by
      // falling back to a static embed in createEmbedFromUrl().
      if (response.status === 429) {
        console.warn(
          "[urlMetadataService] Preview server rate limit hit (429) — falling back to static YouTube embed",
        );
      } else if (response.status === 503) {
        console.warn(
          "[urlMetadataService] YouTube API quota exhausted or unavailable (503) — falling back to static YouTube embed",
        );
      } else {
        console.warn(
          "[urlMetadataService] Failed to fetch YouTube metadata:",
          response.status,
          response.statusText,
          "— falling back to static YouTube embed",
        );
      }
      return null;
    }

    const data = await response.json();

    // Validate the response structure
    if (!data || typeof data !== "object" || !data.video_id) {
      console.warn(
        "[urlMetadataService] Invalid YouTube metadata response:",
        data,
      );
      return null;
    }

    const metadata: YouTubeMetadata = {
      type: "video",
      url: data.url || url,
      video_id: data.video_id,
      title: data.title,
      description: data.description,
      channel_name: data.channel_name,
      channel_id: data.channel_id,
      channel_thumbnail: data.channel_thumbnail, // Channel profile picture URL
      thumbnails: data.thumbnails,
      duration: data.duration,
      view_count: data.view_count,
      like_count: data.like_count,
      published_at: data.published_at,
    };

    console.info(
      "[urlMetadataService] Successfully fetched YouTube metadata:",
      {
        video_id: metadata.video_id,
        title: metadata.title?.substring(0, 50) + "..." || "No title",
        channel: metadata.channel_name || "Unknown channel",
        duration: metadata.duration?.formatted || "Unknown duration",
      },
    );

    return metadata;
  } catch (error) {
    console.error(
      "[urlMetadataService] Error fetching YouTube metadata:",
      error,
    );
    return null;
  }
}

// =============================================================================
// Embed Creation
// =============================================================================

/**
 * Creates a proper embed from website metadata.
 * This function:
 * 1. Generates a unique embed_id
 * 2. Encodes metadata as TOON for storage efficiency
 * 3. Stores the embed in EmbedStore (encrypted)
 * 4. Returns the embed reference for insertion into message content
 *
 * @param metadata Website metadata from preview server
 * @returns EmbedCreationResult with embed_id and markdown reference
 */
export async function createWebsiteEmbed(
  metadata: UrlMetadata,
): Promise<EmbedCreationResult> {
  // Generate unique embed_id
  const embed_id = generateUUID();

  console.debug("[urlMetadataService] Creating website embed:", {
    embed_id,
    url: metadata.url,
    title: metadata.title?.substring(0, 50) || "No title",
  });

  // Prepare embed content for storage
  // Include all metadata that will be useful for:
  // 1. LLM inference (title, description, url)
  // 2. UI rendering (favicon, image, site_name)
  const embedContent = {
    url: metadata.url,
    title: metadata.title || null,
    description: metadata.description || null,
    favicon: metadata.favicon || null,
    image: metadata.image || null,
    site_name: metadata.site_name || null,
    // Include timestamp for when metadata was fetched
    fetched_at: new Date().toISOString(),
  };

  // Encode as TOON for storage efficiency (30-60% savings vs JSON)
  let toonContent: string;
  try {
    toonContent = toonEncode(embedContent);
    console.debug("[urlMetadataService] Encoded embed as TOON:", {
      embed_id,
      jsonSize: JSON.stringify(embedContent).length,
      toonSize: toonContent.length,
      savings: `${Math.round((1 - toonContent.length / JSON.stringify(embedContent).length) * 100)}%`,
    });
  } catch (error) {
    // Fallback to JSON if TOON encoding fails
    console.warn(
      "[urlMetadataService] TOON encoding failed, using JSON fallback:",
      error,
    );
    toonContent = JSON.stringify(embedContent);
  }

  // Create embed data structure matching what the embed system expects
  const now = Date.now();
  const embedData = {
    embed_id,
    type: "website",
    status: "finished",
    content: toonContent,
    text_preview: metadata.title || metadata.url, // Short preview for lists
    createdAt: now,
    updatedAt: now,
  };

  // Store in EmbedStore (will be encrypted with master key)
  try {
    await embedStore.put(`embed:${embed_id}`, embedData, "web-website");
    console.info(
      "[urlMetadataService] Stored website embed in EmbedStore:",
      embed_id,
    );
  } catch (error) {
    console.error(
      "[urlMetadataService] Failed to store embed in EmbedStore:",
      error,
    );
    // Continue anyway - embed can still be sent with message
  }

  // Create the embed reference JSON block
  // IMPORTANT: Include URL as fallback for LLM inference if embed resolution fails
  const embedReference = createEmbedReferenceBlock(
    "website",
    embed_id,
    metadata.url,
  );

  return {
    embed_id,
    type: "website",
    embedReference,
  };
}

/**
 * Creates a proper embed from YouTube video metadata.
 * This function:
 * 1. Generates a unique embed_id
 * 2. Encodes metadata as TOON for storage efficiency
 * 3. Stores the embed in EmbedStore (encrypted)
 * 4. Returns the embed reference for insertion into message content
 *
 * @param metadata YouTube metadata from preview server
 * @returns EmbedCreationResult with embed_id and markdown reference
 */
export async function createYouTubeEmbed(
  metadata: YouTubeMetadata,
): Promise<EmbedCreationResult> {
  // Generate unique embed_id
  const embed_id = generateUUID();

  console.debug("[urlMetadataService] Creating YouTube embed:", {
    embed_id,
    video_id: metadata.video_id,
    title: metadata.title?.substring(0, 50) || "No title",
  });

  // Prepare embed content for storage
  // Include all metadata that will be useful for:
  // 1. LLM inference (title, description, channel, duration)
  // 2. UI rendering (thumbnails, view count, etc.)
  const embedContent = {
    url: metadata.url,
    video_id: metadata.video_id,
    title: metadata.title || null,
    description: metadata.description || null,
    channel_name: metadata.channel_name || null,
    channel_id: metadata.channel_id || null,
    // Channel profile picture for rendering alongside channel name
    channel_thumbnail: metadata.channel_thumbnail || null,
    // Only store useful thumbnail URLs for rendering
    thumbnail:
      metadata.thumbnails?.maxres ||
      metadata.thumbnails?.high ||
      metadata.thumbnails?.medium ||
      metadata.thumbnails?.default ||
      null,
    duration_seconds: metadata.duration?.total_seconds || null,
    duration_formatted: metadata.duration?.formatted || null,
    view_count: metadata.view_count || null,
    like_count: metadata.like_count || null,
    published_at: metadata.published_at || null,
    // Include timestamp for when metadata was fetched
    fetched_at: new Date().toISOString(),
  };

  // Encode as TOON for storage efficiency (30-60% savings vs JSON)
  let toonContent: string;
  try {
    toonContent = toonEncode(embedContent);
    console.debug("[urlMetadataService] Encoded YouTube embed as TOON:", {
      embed_id,
      jsonSize: JSON.stringify(embedContent).length,
      toonSize: toonContent.length,
      savings: `${Math.round((1 - toonContent.length / JSON.stringify(embedContent).length) * 100)}%`,
    });
  } catch (error) {
    // Fallback to JSON if TOON encoding fails
    console.warn(
      "[urlMetadataService] TOON encoding failed, using JSON fallback:",
      error,
    );
    toonContent = JSON.stringify(embedContent);
  }

  // Create text preview for the embed
  // Include duration for quick reference
  const textPreview = metadata.title
    ? `${metadata.title}${metadata.duration?.formatted ? ` (${metadata.duration.formatted})` : ""}`
    : metadata.url;

  // Create embed data structure matching what the embed system expects
  const now = Date.now();
  const embedData = {
    embed_id,
    type: "video",
    status: "finished",
    content: toonContent,
    text_preview: textPreview,
    createdAt: now,
    updatedAt: now,
  };

  // Store in EmbedStore (will be encrypted with master key)
  try {
    await embedStore.put(`embed:${embed_id}`, embedData, "videos-video");
    console.info(
      "[urlMetadataService] Stored YouTube embed in EmbedStore:",
      embed_id,
    );
  } catch (error) {
    console.error(
      "[urlMetadataService] Failed to store YouTube embed in EmbedStore:",
      error,
    );
    // Continue anyway - embed can still be sent with message
  }

  // Create the embed reference JSON block
  // IMPORTANT: Include URL as fallback for LLM inference if embed resolution fails
  const embedReference = createEmbedReferenceBlock(
    "video",
    embed_id,
    metadata.url,
  );

  return {
    embed_id,
    type: "video",
    embedReference,
  };
}

// =============================================================================
// URL Detection Helpers
// =============================================================================

/**
 * YouTube URL patterns for detection
 * Matches:
 * - https://www.youtube.com/watch?v=VIDEO_ID
 * - https://m.youtube.com/watch?v=VIDEO_ID (mobile)
 * - https://youtu.be/VIDEO_ID
 * - https://www.youtube.com/embed/VIDEO_ID
 * - https://www.youtube.com/shorts/VIDEO_ID
 * - https://www.youtube.com/v/VIDEO_ID (legacy)
 */
const YOUTUBE_URL_PATTERN =
  /^https?:\/\/(www\.|m\.)?(youtube\.com\/(watch\?v=|embed\/|shorts\/|v\/)|youtu\.be\/)/i;

/**
 * Check if a URL is a YouTube video URL
 * @param url The URL to check
 * @returns true if it's a YouTube URL
 */
export function isYouTubeUrl(url: string): boolean {
  return YOUTUBE_URL_PATTERN.test(url);
}

/**
 * Extracts the 11-character YouTube video ID from a URL without any API call.
 * Supports all common YouTube URL formats.
 *
 * @param url Any YouTube URL
 * @returns The 11-character video ID, or null if not found
 */
export function extractYouTubeVideoId(url: string): string | null {
  // Ordered patterns matching all known YouTube URL formats
  const patterns = [
    /[?&]v=([a-zA-Z0-9_-]{11})/, // ?v= or &v=
    /youtu\.be\/([a-zA-Z0-9_-]{11})/, // youtu.be/
    /youtube\.com\/embed\/([a-zA-Z0-9_-]{11})/, // /embed/
    /youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})/, // /shorts/
    /youtube\.com\/v\/([a-zA-Z0-9_-]{11})/, // /v/
  ];
  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }
  return null;
}

/**
 * Creates a static YouTube embed without any API call.
 *
 * Used for users with no credits (authenticated or not). The embed uses a
 * thumbnail URL constructed directly from the video ID — YouTube serves
 * hqdefault.jpg for every video at a predictable CDN path. The thumbnail
 * is NOT embedded as a raw URL here; VideoEmbedPreview.svelte derives the
 * proxied URL from the video_id prop via its $derived rawThumbnailUrl →
 * thumbnailUrl chain, so user privacy is maintained (no direct hits to
 * Google CDN from the client browser).
 *
 * The resulting embed is stored in EmbedStore with the same shape and
 * namespace as a full YouTube embed, so the render path is identical.
 *
 * @param videoId The 11-character YouTube video ID
 * @param url The original YouTube URL (for LLM fallback reference)
 * @returns EmbedCreationResult with embed_id and markdown reference
 */
export async function createStaticYouTubeEmbed(
  videoId: string,
  url: string,
): Promise<EmbedCreationResult> {
  const embed_id = generateUUID();

  console.debug(
    "[urlMetadataService] Creating static YouTube embed (no API call):",
    {
      embed_id,
      video_id: videoId,
    },
  );

  // Minimal embed content — only what can be known without an API call.
  // title/description/channel/stats are all null; the renderer will show
  // "YouTube Video" as the fallback title and derive the thumbnail from video_id.
  const embedContent = {
    url: `https://www.youtube.com/watch?v=${videoId}`,
    video_id: videoId,
    title: null,
    description: null,
    channel_name: null,
    channel_id: null,
    channel_thumbnail: null,
    thumbnail: null, // renderer derives thumbnail from video_id client-side
    duration_seconds: null,
    duration_formatted: null,
    view_count: null,
    like_count: null,
    published_at: null,
    fetched_at: new Date().toISOString(),
  };

  // Encode as TOON for storage efficiency
  let toonContent: string;
  try {
    toonContent = toonEncode(embedContent);
  } catch (error) {
    console.warn(
      "[urlMetadataService] TOON encoding failed for static embed, using JSON fallback:",
      error,
    );
    toonContent = JSON.stringify(embedContent);
  }

  const now = Date.now();
  const embedData = {
    embed_id,
    type: "video",
    status: "finished",
    content: toonContent,
    text_preview: "YouTube Video",
    createdAt: now,
    updatedAt: now,
  };

  try {
    await embedStore.put(`embed:${embed_id}`, embedData, "videos-video");
    console.info(
      "[urlMetadataService] Stored static YouTube embed in EmbedStore:",
      embed_id,
    );
  } catch (error) {
    console.error(
      "[urlMetadataService] Failed to store static YouTube embed in EmbedStore:",
      error,
    );
  }

  const embedReference = createEmbedReferenceBlock("video", embed_id, url);

  return {
    embed_id,
    type: "video",
    embedReference,
  };
}

/**
 * Fetch metadata and create an embed for any URL (website or YouTube).
 * Automatically detects the URL type and fetches appropriate metadata.
 *
 * Credit-aware YouTube handling:
 * - Users WITH credits    → full YouTube Data API fetch (title, channel, stats, etc.)
 *                           The preview server checks its 24-hour cache first, so a
 *                           previously-fetched video costs zero API quota.
 * - Users WITHOUT credits → static embed built entirely client-side (no API call).
 *                           The thumbnail is derived from the video ID and proxied
 *                           through the preview server's /api/v1/image endpoint so
 *                           the user's browser never hits Google/YouTube CDN directly.
 *
 * The credit check is intentionally client-side. A determined user could spoof it by
 * editing their local store, but the YouTube API quota is free (10k units/day) and the
 * preview server's rate limiter (10 req/min/IP on the YouTube endpoint) already caps
 * bulk abuse. The main goal is to protect against unauthenticated bots and high-volume
 * anonymous traffic, not against individual motivated bad actors.
 *
 * Graceful degradation: if the API call fails for any reason — server-side rate limit
 * (429), Google quota exhausted (503), network error, or any other non-OK response —
 * fetchYouTubeMetadata() returns null and we fall back to createStaticYouTubeEmbed()
 * exactly as for users without credits. The user sees the thumbnail + "YouTube Video"
 * title with no interruption or error message.
 *
 * @param url The URL to process
 * @returns EmbedCreationResult or null if metadata fetch failed
 */
export async function createEmbedFromUrl(
  url: string,
): Promise<EmbedCreationResult | null> {
  // Check if it's a YouTube URL
  if (isYouTubeUrl(url)) {
    const videoId = extractYouTubeVideoId(url);
    const credits = get(userProfile).credits;

    if (credits <= 0) {
      // No credits: create a static embed entirely client-side — no API call.
      // If we can't extract the video ID fall through to the website embed path.
      if (videoId) {
        console.debug(
          "[urlMetadataService] User has no credits — using static YouTube embed",
        );
        return await createStaticYouTubeEmbed(videoId, url);
      }
      console.warn(
        "[urlMetadataService] Could not extract video ID from YouTube URL, falling back to website embed",
      );
    } else {
      // Has credits: attempt full metadata fetch (server checks cache first).
      const metadata = await fetchYouTubeMetadata(url);
      if (metadata) {
        return await createYouTubeEmbed(metadata);
      }
      // API fetch failed: degrade gracefully to static embed if we have the video ID.
      if (videoId) {
        console.warn(
          "[urlMetadataService] YouTube API fetch failed — falling back to static embed",
        );
        return await createStaticYouTubeEmbed(videoId, url);
      }
      console.warn(
        "[urlMetadataService] YouTube metadata fetch failed, trying website metadata",
      );
    }
  }

  // Fetch website metadata
  const metadata = await fetchUrlMetadata(url);
  if (metadata) {
    return await createWebsiteEmbed(metadata);
  }

  // If all metadata fetching failed, create a minimal embed with just the URL
  console.warn(
    "[urlMetadataService] All metadata fetching failed, creating minimal embed for:",
    url,
  );
  return await createWebsiteEmbed({
    type: "website",
    url: url,
  });
}

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Creates a proper JSON code block for embed reference
 * Format: ```json\n{"type": "...", "embed_id": "...", "url": "..."}\n```
 *
 * This is the format that extractEmbedReferences() in embedResolver.ts looks for.
 * The embed data will be loaded from EmbedStore and sent with the message.
 *
 * IMPORTANT: The `url` field is included as a FALLBACK for LLM inference.
 * If the embed cannot be resolved from server cache (e.g., encryption error,
 * cache expiration, or processing failure), the LLM will still have access
 * to the original URL and can process the request meaningfully.
 *
 * @param type The embed type (website, video, etc.)
 * @param embed_id The unique embed identifier
 * @param url Optional URL to include as fallback for LLM inference
 * @returns Markdown code block string
 */
export function createEmbedReferenceBlock(
  type: string,
  embed_id: string,
  url?: string,
): string {
  // Include URL as fallback - critical for cases where embed resolution fails
  // Without this, LLM receives only {"type": "...", "embed_id": "..."} which is useless
  const referenceData: Record<string, string> = { type, embed_id };
  if (url) {
    referenceData.url = url;
  }
  const jsonContent = JSON.stringify(referenceData, null, 2);
  return `\`\`\`json\n${jsonContent}\n\`\`\``;
}

// =============================================================================
// Legacy Functions (for backward compatibility)
// =============================================================================

/**
 * @deprecated Use createEmbedFromUrl() instead
 * Creates a json_embed code block markdown for website metadata
 * Uses json_embed code block type to distinguish from regular JSON content
 * @param metadata The website metadata to serialize
 * @returns Markdown string with json_embed code block format
 */
export function createJsonEmbedCodeBlock(metadata: UrlMetadata): string {
  const jsonContent = JSON.stringify(metadata, null, 2);
  return `\`\`\`json_embed\n${jsonContent}\n\`\`\``;
}

/**
 * @deprecated Use fetchUrlMetadata() and createWebsiteEmbed() instead
 * Creates website metadata for a URL with only the URL (for failed metadata fetch)
 * @param url The URL that failed to fetch metadata
 * @returns UrlMetadata object with only URL and type
 */
export function createWebsiteMetadataFromUrl(url: string): UrlMetadata {
  return {
    type: "website",
    url: url,
  };
}

/**
 * Extracts URL from a json_embed code block (legacy format)
 * @param jsonEmbedBlock The json_embed code block content
 * @returns Original URL or null if not a valid json_embed block
 */
export function extractUrlFromJsonEmbedBlock(
  jsonEmbedBlock: string,
): string | null {
  try {
    // Remove the code block markers and parse JSON
    const cleanJson = jsonEmbedBlock
      .replace(/```json_embed\n?|\n?```/g, "")
      .trim();
    const parsed = JSON.parse(cleanJson);

    if (parsed.type === "website" && typeof parsed.url === "string") {
      return parsed.url;
    }

    return null;
  } catch {
    // JSON parsing failed - not a valid json_embed block
    return null;
  }
}

/**
 * Extracts website metadata from a json_embed code block (legacy format)
 * @param jsonEmbedBlock The json_embed code block content
 * @returns UrlMetadata or null if not a valid json_embed block
 */
export function parseJsonEmbedBlock(
  jsonEmbedBlock: string,
): UrlMetadata | null {
  try {
    // Remove the code block markers and parse JSON
    const cleanJson = jsonEmbedBlock
      .replace(/```json_embed\n?|\n?```/g, "")
      .trim();
    const parsed = JSON.parse(cleanJson);

    if (parsed.type === "website" && typeof parsed.url === "string") {
      return parsed as UrlMetadata;
    }

    return null;
  } catch {
    // JSON parsing failed - not a valid json_embed block
    return null;
  }
}
