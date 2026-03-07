// frontend/packages/ui/src/data/embedRegistry.generated.ts
//
// ⚠️  WARNING: THIS FILE IS AUTO-GENERATED — DO NOT EDIT MANUALLY ⚠️
//
// Generated from backend app.yml files and shared/config/embed_types.yml
// by: frontend/packages/ui/scripts/generate-embed-registry.js
//
// To add a new embed type, add an entry to the relevant app.yml
// under the embed_types section, then rebuild.
//
// Generated: 2026-03-06T13:48:11.015Z
// Total embed types: 28

/**
 * Maps server/backend embed type strings to frontend type strings.
 * Used by embedParsing.ts (mapEmbedReferenceType) and embedStore.ts (normalizeEmbedType).
 *
 * Example: "app_skill_use" → "app-skill-use", "website" → "web-website"
 */
export const EMBED_TYPE_NORMALIZATION_MAP: Record<string, string> = {
  "audio-recording": "recording",
  "app_skill_use": "app-skill-use",
  "code": "code-code",
  "document": "docs-doc",
  "event": "events-event",
  "image": "image",
  "mail": "mail-email",
  "place": "maps-place",
  "location": "maps",
  "math-plot": "math-plot",
  "website": "web-website",
  "pdf": "pdf",
  "connection": "travel-connection",
  "stay": "travel-stay",
  "video": "videos-video",
  "sheet": "sheets-sheet",
  "focus_mode_activation": "focus-mode-activation"
};

/**
 * Maps "app_id:skill_id" to the canonical child embed type string.
 * Used to determine the type for individual results within composite embeds.
 *
 * Example: "web:search" → "website", "maps:search" → "place"
 */
export const EMBED_CHILD_TYPE_MAP: Record<string, string> = {
  "events:search": "event",
  "maps:search": "place",
  "news:search": "website",
  "shopping:search_products": "website",
  "travel:search_connections": "connection",
  "travel:search_stays": "stay",
  "videos:search": "video",
  "web:search": "website"
};

/**
 * Maps embed registry keys to preview component import paths.
 * Keys use "app:<appId>:<skillId>" for app-skill-use, or frontend_type for direct.
 * Paths are relative to the components/embeds/ directory.
 */
export const EMBED_PREVIEW_COMPONENTS: Record<string, string> = {
  "recording": "audio/RecordingEmbedPreview.svelte",
  "app:code:get_docs": "code/CodeGetDocsEmbedPreview.svelte",
  "code-code": "code/CodeEmbedPreview.svelte",
  "docs-doc": "docs/DocsEmbedPreview.svelte",
  "app:events:search": "events/EventsSearchEmbedPreview.svelte",
  "events-event": "events/EventEmbedPreview.svelte",
  "app:health:search_appointments": "health/HealthSearchEmbedPreview.svelte",
  "app:images:generate": "images/ImageGenerateEmbedPreview.svelte",
  "app:images:generate_draft": "images/ImageGenerateEmbedPreview.svelte",
  "image": "images/ImageEmbedPreview.svelte",
  "mail-email": "mail/MailEmbedPreview.svelte",
  "app:maps:search": "maps/MapsSearchEmbedPreview.svelte",
  "maps-place": "maps/MapsLocationEmbedPreview.svelte",
  "maps": "maps/MapsLocationEmbedPreview.svelte",
  "app:math:calculate": "math/MathCalculateEmbedPreview.svelte",
  "math-plot": "math/MathPlotEmbedPreview.svelte",
  "app:news:search": "news/NewsSearchEmbedPreview.svelte",
  "web-website": "web/WebsiteEmbedPreview.svelte",
  "pdf": "pdf/PDFEmbedPreview.svelte",
  "app:reminder:set-reminder": "reminder/ReminderEmbedPreview.svelte",
  "app:shopping:search_products": "shopping/ShoppingSearchEmbedPreview.svelte",
  "app:travel:search_connections": "travel/TravelSearchEmbedPreview.svelte",
  "travel-connection": "travel/TravelConnectionEmbedPreview.svelte",
  "app:travel:search_stays": "travel/TravelStaysEmbedPreview.svelte",
  "travel-stay": "travel/TravelStayEmbedPreview.svelte",
  "app:travel:price_calendar": "travel/TravelPriceCalendarEmbedPreview.svelte",
  "app:travel:get_flight": "travel/TravelFlightDetailsEmbedPreview.svelte",
  "app:videos:search": "videos/VideosSearchEmbedPreview.svelte",
  "videos-video": "videos/VideoEmbedPreview.svelte",
  "app:videos:get_transcript": "videos/VideoTranscriptEmbedPreview.svelte",
  "app:web:search": "web/WebSearchEmbedPreview.svelte",
  "app:web:read": "web/WebReadEmbedPreview.svelte",
  "sheets-sheet": "sheets/SheetEmbedPreview.svelte",
  "focus-mode-activation": "FocusModeActivationEmbed.svelte"
};

/**
 * Maps embed registry keys to fullscreen component import paths.
 * Keys use "app:<appId>:<skillId>" for app-skill-use, or frontend_type for direct.
 */
export const EMBED_FULLSCREEN_COMPONENTS: Record<string, string> = {
  "recording": "audio/RecordingEmbedFullscreen.svelte",
  "app:code:get_docs": "code/CodeGetDocsEmbedFullscreen.svelte",
  "code-code": "code/CodeEmbedFullscreen.svelte",
  "docs-doc": "docs/DocsEmbedFullscreen.svelte",
  "app:events:search": "events/EventsSearchEmbedFullscreen.svelte",
  "events-event": "events/EventEmbedFullscreen.svelte",
  "app:health:search_appointments": "health/HealthSearchEmbedFullscreen.svelte",
  "app:images:generate": "images/ImageGenerateEmbedFullscreen.svelte",
  "app:images:generate_draft": "images/ImageGenerateEmbedFullscreen.svelte",
  "image": "images/ImageEmbedFullscreen.svelte",
  "mail-email": "mail/MailEmbedFullscreen.svelte",
  "app:maps:search": "maps/MapsSearchEmbedFullscreen.svelte",
  "maps-place": "maps/MapsLocationEmbedFullscreen.svelte",
  "maps": "maps/MapsLocationEmbedFullscreen.svelte",
  "app:math:calculate": "math/MathCalculateEmbedFullscreen.svelte",
  "math-plot": "math/MathPlotEmbedFullscreen.svelte",
  "app:news:search": "news/NewsSearchEmbedFullscreen.svelte",
  "web-website": "web/WebsiteEmbedFullscreen.svelte",
  "pdf": "pdf/PDFEmbedFullscreen.svelte",
  "app:reminder:set-reminder": "reminder/ReminderEmbedFullscreen.svelte",
  "app:shopping:search_products": "shopping/ShoppingSearchEmbedFullscreen.svelte",
  "app:travel:search_connections": "travel/TravelSearchEmbedFullscreen.svelte",
  "travel-connection": "travel/TravelConnectionEmbedFullscreen.svelte",
  "app:travel:search_stays": "travel/TravelStaysEmbedFullscreen.svelte",
  "travel-stay": "travel/TravelStayEmbedFullscreen.svelte",
  "app:travel:price_calendar": "travel/TravelPriceCalendarEmbedFullscreen.svelte",
  "app:travel:get_flight": "travel/TravelFlightDetailsEmbedFullscreen.svelte",
  "app:videos:search": "videos/VideosSearchEmbedFullscreen.svelte",
  "videos-video": "videos/VideoEmbedFullscreen.svelte",
  "app:videos:get_transcript": "videos/VideoTranscriptEmbedFullscreen.svelte",
  "app:web:search": "web/WebSearchEmbedFullscreen.svelte",
  "app:web:read": "web/WebReadEmbedFullscreen.svelte",
  "sheets-sheet": "sheets/SheetEmbedFullscreen.svelte"
};

/**
 * Maps frontend embed type strings to TipTap renderer class identifiers.
 * Used by embed_renderers/index.ts to build the renderer registry.
 */
export const EMBED_RENDERER_MAP: Record<string, string> = {
  "recording": "RecordingRenderer",
  "app-skill-use": "AppSkillUseRenderer",
  "code-code": "GroupRenderer",
  "code-code-group": "GroupRenderer",
  "docs-doc": "GroupRenderer",
  "docs-doc-group": "GroupRenderer",
  "events-event": "GroupRenderer",
  "events-event-group": "GroupRenderer",
  "image": "ImageRenderer",
  "mail-email": "GroupRenderer",
  "mail-email-group": "GroupRenderer",
  "maps-place": "GroupRenderer",
  "maps-place-group": "GroupRenderer",
  "maps": "MapLocationRenderer",
  "math-plot": "MathPlotRenderer",
  "web-website": "GroupRenderer",
  "web-website-group": "GroupRenderer",
  "pdf": "PdfRenderer",
  "travel-connection": "GroupRenderer",
  "travel-connection-group": "GroupRenderer",
  "travel-stay": "GroupRenderer",
  "travel-stay-group": "GroupRenderer",
  "videos-video": "GroupRenderer",
  "videos-video-group": "GroupRenderer",
  "sheets-sheet": "GroupRenderer",
  "sheets-sheet-group": "GroupRenderer",
  "focus-mode-activation": "FocusModeActivationRenderer",
  "app-skill-use-group": "GroupRenderer"
};

/**
 * Per-embed-type metadata: icon, gradient CSS var, i18n namespace, etc.
 * Keys use "app:<appId>:<skillId>" for app-skill-use, or frontend_type for direct.
 */
export interface EmbedTypeMetadata {
  icon?: string;
  gradientVar?: string;
  i18nNamespace?: string;
  appId?: string;
  skillId?: string;
  hasChildren?: boolean;
  childFrontendType?: string;
}

export const EMBED_METADATA: Record<string, EmbedTypeMetadata> = {
  "recording": {
    "icon": "audio",
    "gradientVar": "--color-app-audio",
    "i18nNamespace": "embeds.audio.recording",
    "appId": "audio"
  },
  "app:code:get_docs": {
    "icon": "library",
    "gradientVar": "--color-app-code",
    "i18nNamespace": "embeds.code.get_docs",
    "appId": "code",
    "skillId": "get_docs"
  },
  "code-code": {
    "icon": "coding",
    "gradientVar": "--color-app-code",
    "i18nNamespace": "embeds.code.code",
    "appId": "code"
  },
  "docs-doc": {
    "icon": "docs",
    "gradientVar": "--color-app-docs",
    "i18nNamespace": "embeds.docs.doc",
    "appId": "docs"
  },
  "app:events:search": {
    "icon": "search",
    "gradientVar": "--color-app-events",
    "i18nNamespace": "embeds.events.search",
    "appId": "events",
    "skillId": "search",
    "hasChildren": true,
    "childFrontendType": "events-event"
  },
  "app:health:search_appointments": {
    "icon": "heart",
    "gradientVar": "--color-app-health",
    "i18nNamespace": "embeds.health.search_appointments",
    "appId": "health",
    "skillId": "search_appointments"
  },
  "app:images:generate": {
    "icon": "image",
    "gradientVar": "--color-app-images",
    "i18nNamespace": "embeds.images.generate",
    "appId": "images",
    "skillId": "generate"
  },
  "app:images:generate_draft": {
    "icon": "image",
    "gradientVar": "--color-app-images",
    "i18nNamespace": "embeds.images.generate",
    "appId": "images",
    "skillId": "generate_draft"
  },
  "image": {
    "icon": "image",
    "gradientVar": "--color-app-images",
    "i18nNamespace": "embeds.images.view",
    "appId": "images"
  },
  "mail-email": {
    "icon": "mail",
    "gradientVar": "--color-app-mail",
    "i18nNamespace": "embeds.mail.email",
    "appId": "mail"
  },
  "app:maps:search": {
    "icon": "search",
    "gradientVar": "--color-app-maps",
    "i18nNamespace": "embeds.maps.search",
    "appId": "maps",
    "skillId": "search",
    "hasChildren": true,
    "childFrontendType": "maps-place"
  },
  "maps": {
    "icon": "maps",
    "gradientVar": "--color-app-maps",
    "i18nNamespace": "embeds.maps.location",
    "appId": "maps"
  },
  "app:math:calculate": {
    "icon": "math",
    "gradientVar": "--color-app-math",
    "i18nNamespace": "embeds.math.calculate",
    "appId": "math",
    "skillId": "calculate"
  },
  "math-plot": {
    "icon": "function",
    "gradientVar": "--color-app-math",
    "i18nNamespace": "embeds.math.plot",
    "appId": "math"
  },
  "app:news:search": {
    "icon": "search",
    "gradientVar": "--color-app-news",
    "i18nNamespace": "embeds.news.search",
    "appId": "news",
    "skillId": "search",
    "hasChildren": true,
    "childFrontendType": "web-website"
  },
  "pdf": {
    "icon": "pdf",
    "gradientVar": "--color-app-pdf",
    "i18nNamespace": "embeds.pdf.view",
    "appId": "pdf"
  },
  "app:reminder:set-reminder": {
    "icon": "reminder",
    "gradientVar": "--color-app-reminder",
    "i18nNamespace": "embeds.reminder.set_reminder",
    "appId": "reminder",
    "skillId": "set-reminder"
  },
  "app:shopping:search_products": {
    "icon": "shopping",
    "gradientVar": "--color-app-shopping",
    "i18nNamespace": "embeds.shopping.search_products",
    "appId": "shopping",
    "skillId": "search_products",
    "hasChildren": true,
    "childFrontendType": "web-website"
  },
  "app:travel:search_connections": {
    "icon": "search",
    "gradientVar": "--color-app-travel",
    "i18nNamespace": "embeds.travel.search_connections",
    "appId": "travel",
    "skillId": "search_connections",
    "hasChildren": true,
    "childFrontendType": "travel-connection"
  },
  "app:travel:search_stays": {
    "icon": "search",
    "gradientVar": "--color-app-travel",
    "i18nNamespace": "embeds.travel.search_stays",
    "appId": "travel",
    "skillId": "search_stays",
    "hasChildren": true,
    "childFrontendType": "travel-stay"
  },
  "app:travel:price_calendar": {
    "icon": "calendar",
    "gradientVar": "--color-app-travel",
    "i18nNamespace": "embeds.travel.price_calendar",
    "appId": "travel",
    "skillId": "price_calendar"
  },
  "app:travel:get_flight": {
    "icon": "travel",
    "gradientVar": "--color-app-travel",
    "i18nNamespace": "embeds.travel.flight_details",
    "appId": "travel",
    "skillId": "get_flight"
  },
  "app:videos:search": {
    "icon": "search",
    "gradientVar": "--color-app-videos",
    "i18nNamespace": "embeds.videos.search",
    "appId": "videos",
    "skillId": "search",
    "hasChildren": true,
    "childFrontendType": "videos-video"
  },
  "app:videos:get_transcript": {
    "icon": "transcript",
    "gradientVar": "--color-app-videos",
    "i18nNamespace": "embeds.videos.get_transcript",
    "appId": "videos",
    "skillId": "get_transcript"
  },
  "app:web:search": {
    "icon": "search",
    "gradientVar": "--color-app-web",
    "i18nNamespace": "embeds.web.search",
    "appId": "web",
    "skillId": "search",
    "hasChildren": true,
    "childFrontendType": "web-website"
  },
  "app:web:read": {
    "icon": "web",
    "gradientVar": "--color-app-web",
    "i18nNamespace": "embeds.web.read",
    "appId": "web",
    "skillId": "read"
  },
  "sheets-sheet": {
    "icon": "sheets",
    "gradientVar": "--color-app-sheets",
    "i18nNamespace": "embeds.sheets.sheet",
    "appId": "sheets"
  },
  "focus-mode-activation": {
    "icon": "focus",
    "gradientVar": "--color-app-ai",
    "i18nNamespace": "embeds.ai.focus_mode_activation",
    "appId": "ai"
  }
};

/**
 * Frontend type strings that can be grouped in the TipTap editor.
 */
export const EMBED_GROUPABLE_TYPES: string[] = [
  "app-skill-use",
  "code-code",
  "docs-doc",
  "events-event",
  "mail-email",
  "maps-place",
  "sheets-sheet",
  "travel-connection",
  "travel-stay",
  "videos-video",
  "web-website"
];

// ── Content Type Contracts ─────────────────────────────────────────────
// Generated from content_fields and child_content_fields in app.yml.
// Use these interfaces for type-safe access to decoded embed content.
// Example: const content = decodedContent as WebSearchEmbedContent;

/** Content fields for code:get_docs embeds (finished state). */
export interface CodeGetDocsEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  library: string;
  results: unknown[];
  result_count: number;
  [key: string]: unknown;
}

/** Content fields for code:code embeds (finished state). */
export interface CodeCodeEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  language: string;
  code: string;
  filename?: string;
  line_count: number;
  [key: string]: unknown;
}

/** Content fields for docs:doc embeds (finished state). */
export interface DocsDocEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  html: string;
  title?: string;
  word_count: number;
  [key: string]: unknown;
}

/** Content fields for images:generate embeds (finished state). */
export interface ImagesGenerateEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  prompt: string;
  model: string;
  aspect_ratio?: string;
  s3_base_url: string;
  /** Record of file variants with S3 keys */
  files: Record<string, unknown>;
  aes_key: string;
  aes_nonce: string;
  [key: string]: unknown;
}

/** Content fields for images:generate_draft embeds (finished state). */
export interface ImagesGenerateDraftEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  prompt: string;
  model: string;
  s3_base_url: string;
  files: Record<string, unknown>;
  aes_key: string;
  aes_nonce: string;
  [key: string]: unknown;
}

/** Content fields for images:image embeds (finished state). */
export interface ImageEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  filename?: string;
  s3_base_url?: string;
  files?: Record<string, unknown>;
  aes_key?: string;
  aes_nonce?: string;
  content_hash?: string;
  [key: string]: unknown;
}

/** Content fields for mail:email embeds (finished state). */
export interface MailEmailEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  receiver: string;
  subject?: string;
  content: string;
  footer?: string;
  [key: string]: unknown;
}

/** Content fields for math:calculate embeds (finished state). */
export interface MathCalculateEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  results: unknown[];
  result_count: number;
  [key: string]: unknown;
}

/** Content fields for math:plot embeds (finished state). */
export interface MathPlotEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  plot_spec: string;
  [key: string]: unknown;
}

/** Content fields for web:search embeds (finished state). */
export interface WebSearchEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  query: string;
  provider?: string;
  result_count: number;
  /** Pipe-delimited child embed IDs (TOON tabular format) */
  embed_ids?: string;
  [key: string]: unknown;
}

/** Content fields for web-website child embeds. */
export interface WebWebsiteEmbedContent {
  url: string;
  title: string;
  description: string;
  page_age?: string;
  /** Favicon URL (flattened from meta_url.favicon) */
  meta_url_favicon?: string;
  /** Thumbnail URL (flattened from thumbnail.original) */
  thumbnail_original?: string;
  /** Pipe-delimited additional context snippets */
  extra_snippets?: string;
  language?: string;
  [key: string]: unknown;
}

/** Content fields for web:read embeds (finished state). */
export interface WebReadEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  url: string;
  results: unknown[];
  result_count: number;
  [key: string]: unknown;
}

/** Content fields for sheets:sheet embeds (finished state). */
export interface SheetsSheetEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  /** Raw markdown table content */
  table: string;
  title?: string;
  row_count: number;
  col_count: number;
  [key: string]: unknown;
}

/** Content fields for ai:focus_mode_activation embeds (finished state). */
export interface FocusModeActivationEmbedContent {
  /** App identifier */
  app_id: string;
  /** Skill identifier */
  skill_id: string;
  /** Embed status */
  status: string;
  focus_id: string;
  focus_mode_name: string;
  [key: string]: unknown;
}

/**
 * Normalize a server/backend embed type string to its frontend equivalent.
 * Drop-in replacement for the manual switch/map in embedStore.ts and embedParsing.ts.
 */
export function normalizeEmbedType(backendType: string): string {
  return EMBED_TYPE_NORMALIZATION_MAP[backendType] ?? backendType;
}

/**
 * Get the canonical child embed type for a composite embed's app_id + skill_id.
 * Returns "website" as default (matches existing backend behavior).
 */
export function getChildEmbedType(appId: string, skillId: string): string {
  const key = `${appId}:${skillId}`;
  return EMBED_CHILD_TYPE_MAP[key] ?? "website";
}

/**
 * Check if a frontend embed type can be grouped in the TipTap editor.
 */
export function isGroupableType(frontendType: string): boolean {
  return EMBED_GROUPABLE_TYPES.includes(frontendType);
}
