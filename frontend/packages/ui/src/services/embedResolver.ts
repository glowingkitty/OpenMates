/**
 * Embed Resolver Service
 * Resolves embed references (embed_id) to actual embed content from ContentStore or Directus.
 * Handles TOON-encoded content decoding when needed.
 */

import { embedStore } from './embedStore';
import { EmbedNodeAttributes } from '../message_parsing/types';
import { generateUUID } from '../message_parsing/utils';

// TOON decoder (will be imported when available)
// Using official @toon-format/toon package
let toonDecode: ((toonString: string) => any) | null = null;

/**
 * Initialize TOON decoder
 * Uses the official @toon-format/toon package for decoding TOON-encoded content
 */
async function initToonDecoder() {
  if (!toonDecode) {
    try {
      // Dynamic import for TOON decoder from official package
      const toonModule = await import('@toon-format/toon');
      toonDecode = toonModule.decode;
      console.debug('[embedResolver] TOON decoder initialized successfully');
    } catch (error) {
      console.warn('[embedResolver] TOON decoder not available, will use JSON fallback:', error);
      // Keep toonDecode as null to use JSON fallback
    }
  }
}

/**
 * Embed data structure from server/cache
 */
interface EmbedData {
  embed_id: string;
  type: string; // Decrypted type (client-side only)
  status: 'processing' | 'finished' | 'error';
  content: string; // TOON-encoded string
  text_preview?: string;
  embed_ids?: string[]; // For composite embeds (app_skill_use)
  createdAt: number;
  updatedAt: number;
}

/**
 * Resolve an embed by embed_id
 * @param embed_id - The embed identifier
 * @returns Embed data or null if not found
 */
export async function resolveEmbed(embed_id: string): Promise<EmbedData | null> {
  try {
    // Initialize TOON decoder
    await initToonDecoder();
    
    // First, try to load from EmbedStore (IndexedDB)
    const cachedEmbed = await embedStore.get(`embed:${embed_id}`);
    if (cachedEmbed) {
      console.debug('[embedResolver] Found embed in EmbedStore:', embed_id);
      return cachedEmbed as EmbedData;
    }
    
    // If not in EmbedStore, fetch from Directus
    // TODO: Implement Directus fetch when sync service is ready
    console.debug('[embedResolver] Embed not in EmbedStore, fetching from Directus:', embed_id);
    
    // For now, return null if not cached
    // This will be implemented when sync service handles embed fetching
    return null;
  } catch (error) {
    console.error('[embedResolver] Error resolving embed:', embed_id, error);
    return null;
  }
}

/**
 * Decode TOON content to JavaScript object
 * @param toonContent - TOON-encoded string
 * @returns Decoded object
 */
export async function decodeToonContent(toonContent: string): Promise<any> {
  await initToonDecoder();
  
  if (toonDecode) {
    try {
      return toonDecode(toonContent);
    } catch (error) {
      console.error('[embedResolver] Error decoding TOON content:', error);
      // Fallback to treating as JSON string
      try {
        return JSON.parse(toonContent);
      } catch (jsonError) {
        console.error('[embedResolver] Error parsing as JSON fallback:', jsonError);
        return null;
      }
    }
  } else {
    // Fallback to JSON parsing if TOON decoder not available
    try {
      return JSON.parse(toonContent);
    } catch (error) {
      console.error('[embedResolver] Error parsing content as JSON:', error);
      return null;
    }
  }
}

/**
 * Convert embed data to EmbedNodeAttributes for rendering
 * @param embedData - Embed data from resolver
 * @param embedType - The embed type (app_skill_use, website, etc.)
 * @returns EmbedNodeAttributes for TipTap rendering
 */
export async function embedDataToNodeAttributes(
  embedData: EmbedData,
  embedType: string
): Promise<EmbedNodeAttributes | null> {
  try {
    // Decode TOON content
    const decodedContent = await decodeToonContent(embedData.content);
    if (!decodedContent) {
      console.warn('[embedResolver] Failed to decode embed content:', embedData.embed_id);
      return null;
    }
    
    // Create embed node attributes based on type
    const nodeAttrs: EmbedNodeAttributes = {
      id: generateUUID(),
      type: mapEmbedTypeToNodeType(embedType),
      status: embedData.status,
      contentRef: `embed:${embedData.embed_id}`,
      contentHash: undefined, // Will be computed if needed
    };
    
    // Add type-specific attributes
    if (embedType === 'app_skill_use') {
      // For app_skill_use, we might need to handle composite embeds
      // For now, store the decoded content
      // The actual rendering will be handled by the embed renderer
      nodeAttrs.title = decodedContent.skill_id || decodedContent.app_id;
    } else if (embedType === 'website') {
      // Extract website-specific fields
      nodeAttrs.url = decodedContent.url;
      nodeAttrs.title = decodedContent.title;
      nodeAttrs.description = decodedContent.description;
      nodeAttrs.favicon = decodedContent.meta_url_favicon || decodedContent.favicon;
      nodeAttrs.image = decodedContent.thumbnail_original || decodedContent.image;
    } else if (embedType === 'code') {
      nodeAttrs.language = decodedContent.language;
      nodeAttrs.filename = decodedContent.filename;
      nodeAttrs.lineCount = decodedContent.lineCount;
    } else if (embedType === 'sheet') {
      nodeAttrs.rows = decodedContent.rows;
      nodeAttrs.cols = decodedContent.cols;
      nodeAttrs.cellCount = decodedContent.cellCount;
    }
    
    return nodeAttrs;
  } catch (error) {
    console.error('[embedResolver] Error converting embed data to node attributes:', error);
    return null;
  }
}

/**
 * Map embed type from server to EmbedNodeType
 * @param embedType - Server embed type (app_skill_use, website, code, etc.)
 * @returns EmbedNodeType for TipTap
 */
function mapEmbedTypeToNodeType(embedType: string): string {
  const typeMap: Record<string, string> = {
    'app_skill_use': 'app-skill-use', // New type for app skill results
    'website': 'web-website',
    'place': 'maps-place',
    'event': 'maps-event',
    'code': 'code-code',
    'sheet': 'sheets-sheet',
    'document': 'docs-doc',
    'file': 'file',
  };
  
  return typeMap[embedType] || embedType;
}

/**
 * Store embed in EmbedStore with TOON content
 * @param embedData - Embed data to store
 */
export async function storeEmbed(embedData: EmbedData): Promise<void> {
  try {
    // Store embed with TOON content as-is (no decoding needed for storage)
    // Content will be decoded when needed for rendering
    await embedStore.put(
      `embed:${embedData.embed_id}`,
      embedData,
      mapEmbedTypeToNodeType(embedData.type) as any
    );
    console.debug('[embedResolver] Stored embed in EmbedStore:', embedData.embed_id);
  } catch (error) {
    console.error('[embedResolver] Error storing embed:', error);
  }
}

/**
 * Extract embed references from markdown content
 * Finds all JSON code blocks with embed references: {"type": "...", "embed_id": "..."}
 * @param markdown - The markdown content to parse
 * @returns Array of embed reference objects with embed_id and type
 */
export function extractEmbedReferences(markdown: string): Array<{type: string; embed_id: string; version?: number}> {
  const embedRefs: Array<{type: string; embed_id: string; version?: number}> = [];
  
  // Regex to match JSON code blocks: ```json\n{...}\n```
  const jsonCodeBlockRegex = /```json\n([\s\S]*?)\n```/g;
  let match;
  
  while ((match = jsonCodeBlockRegex.exec(markdown)) !== null) {
    try {
      const jsonContent = match[1].trim();
      const parsed = JSON.parse(jsonContent);
      
      // Check if this is an embed reference (has type and embed_id)
      if (parsed.type && parsed.embed_id) {
        embedRefs.push({
          type: parsed.type,
          embed_id: parsed.embed_id,
          version: parsed.version // Optional version number
        });
        console.debug('[embedResolver] Extracted embed reference:', {
          type: parsed.type,
          embed_id: parsed.embed_id,
          version: parsed.version
        });
      }
    } catch (error) {
      // Not a valid JSON embed reference, skip
      console.debug('[embedResolver] JSON block is not an embed reference:', error);
    }
  }
  
  return embedRefs;
}

/**
 * Load embeds from EmbedStore by embed_ids
 * @param embedIds - Array of embed IDs to load
 * @returns Array of embed data (with TOON content)
 */
export async function loadEmbeds(embedIds: string[]): Promise<EmbedData[]> {
  const embeds: EmbedData[] = [];
  
  for (const embedId of embedIds) {
    try {
      const embed = await resolveEmbed(embedId);
      if (embed) {
        embeds.push(embed);
      } else {
        console.warn('[embedResolver] Embed not found:', embedId);
      }
    } catch (error) {
      console.error('[embedResolver] Error loading embed:', embedId, error);
    }
  }
  
  return embeds;
}

