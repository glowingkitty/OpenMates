// Embed renderer registry - currently only handles website embeds

import { WebsiteRenderer } from './WebsiteRenderer';
import type { EmbedRendererRegistry } from './types';

/**
 * Registry of all embed renderers
 * Currently only includes website renderer, but designed to be extensible
 */
export const embedRenderers: EmbedRendererRegistry = {
  web: new WebsiteRenderer(),
  'website-group': new WebsiteRenderer(), // Same renderer handles both individual and grouped websites
};

/**
 * Get renderer for a specific embed type
 * @param embedType - The embed type (e.g., 'web', 'website-group')
 * @returns The renderer instance or null if not found
 */
export function getEmbedRenderer(embedType: string) {
  return embedRenderers[embedType] || null;
}
