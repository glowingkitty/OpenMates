// Embed renderer registry - handles all embed types including groups

import { GroupRenderer } from "./GroupRenderer";
import { ImageRenderer } from "./ImageRenderer";
import { AppSkillUseRenderer } from "./AppSkillUseRenderer";
import { FocusModeActivationRenderer } from "./FocusModeActivationRenderer";
import { MapLocationRenderer } from "./MapLocationRenderer";
import type { EmbedRendererRegistry } from "./types";

/**
 * Registry of all embed renderers
 * Includes individual renderers and generic group renderer
 */
export const embedRenderers: EmbedRendererRegistry = {
  // App skill use renderer (web search, code generation, etc.)
  "app-skill-use": new AppSkillUseRenderer(),
  // Focus mode activation indicator (countdown + activated state)
  "focus-mode-activation": new FocusModeActivationRenderer(),
  // App skill use group renderer (multiple search requests in horizontal scrollable group)
  "app-skill-use-group": new GroupRenderer(),
  // Use GroupRenderer for all website embeds (individual and grouped)
  "web-website": new GroupRenderer(),
  "web-website-group": new GroupRenderer(),
  // Use GroupRenderer for video embeds (individual and grouped)
  "videos-video": new GroupRenderer(),
  "videos-video-group": new GroupRenderer(),
  // Use GroupRenderer for code embeds (individual and grouped)
  "code-code": new GroupRenderer(),
  "code-code-group": new GroupRenderer(),
  "docs-doc": new GroupRenderer(),
  "docs-doc-group": new GroupRenderer(),
  // Use GroupRenderer for sheet/table embeds (individual and grouped)
  "sheets-sheet": new GroupRenderer(),
  "sheets-sheet-group": new GroupRenderer(),
  // Use GroupRenderer for travel connection embeds (individual and grouped)
  "travel-connection": new GroupRenderer(),
  "travel-connection-group": new GroupRenderer(),
  // Image renderer for static images and SVGs (used in legal documents)
  image: new ImageRenderer(),
  // Map location embed renderer — mounts MapsLocationEmbedPreview in the editor
  maps: new MapLocationRenderer(),
};

/**
 * Get renderer for a specific embed type
 * @param embedType - The embed type (e.g., 'web', 'website-group')
 * @returns The renderer instance or null if not found
 */
export function getEmbedRenderer(embedType: string) {
  return embedRenderers[embedType] || null;
}
