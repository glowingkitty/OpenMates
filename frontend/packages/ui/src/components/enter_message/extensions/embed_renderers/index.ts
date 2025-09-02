// Embed renderer registry - handles all embed types including groups

import { GroupRenderer } from './GroupRenderer';
import type { EmbedRendererRegistry } from './types';

/**
 * Registry of all embed renderers
 * Includes individual renderers and generic group renderer
 */
export const embedRenderers: EmbedRendererRegistry = {
  // Use GroupRenderer for all website embeds (individual and grouped)
  'web-website': new GroupRenderer(),
  'web-website-group': new GroupRenderer(),
  'videos-video-group': new GroupRenderer(),
  'code-code-group': new GroupRenderer(),
  'docs-doc-group': new GroupRenderer(),
  'sheets-sheet-group': new GroupRenderer(),
};

/**
 * Get renderer for a specific embed type
 * @param embedType - The embed type (e.g., 'web', 'website-group')
 * @returns The renderer instance or null if not found
 */
export function getEmbedRenderer(embedType: string) {
  return embedRenderers[embedType] || null;
}
