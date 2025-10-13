// frontend/packages/ui/src/message_parsing/migration.ts
// Migration utilities for converting old embed node types to the new unified embed structure

import { EmbedNodeAttributes } from './types';
import { generateUUID } from './utils';

/**
 * Migrate old embed node types to the new unified embed structure
 * This handles the conversion from individual node types (webEmbed, codeEmbed, etc.)
 * to the unified embed node with type attributes
 */
export function migrateEmbedNodes(content: any): any {
  if (!content || !content.content) {
    return content;
  }

  // Recursively process all nodes in the document
  const migratedContent = {
    ...content,
    content: content.content.map((node: any) => migrateNode(node))
  };

  return migratedContent;
}

/**
 * Migrate a single node, handling embed conversions
 */
function migrateNode(node: any): any {
  // If this is an old embed node type, convert it to the new unified structure
  if (isOldEmbedNode(node)) {
    return convertOldEmbedToNew(node);
  }

  // If this node has children, recursively migrate them
  if (node.content && Array.isArray(node.content)) {
    return {
      ...node,
      content: node.content.map((childNode: any) => migrateNode(childNode))
    };
  }

  return node;
}

/**
 * Check if a node is an old embed node type that needs migration
 */
function isOldEmbedNode(node: any): boolean {
  const oldEmbedTypes = [
    'webEmbed',
    'codeEmbed', 
    'videoEmbed',
    'docEmbed',
    'sheetEmbed',
    'imageEmbed',
    'fileEmbed',
    'audioEmbed',
    'pdfEmbed',
    'bookEmbed',
    'mapsEmbed',
    'recordingEmbed'
  ];

  return oldEmbedTypes.includes(node.type);
}

/**
 * Convert an old embed node to the new unified embed structure
 */
function convertOldEmbedToNew(oldNode: any): any {
  const id = generateUUID();
  const attrs = oldNode.attrs || {};

  // Map old node types to new type attributes
  const typeMapping: { [key: string]: string } = {
    'webEmbed': 'web-website',
    'codeEmbed': 'code-code',
    'videoEmbed': 'videos-video',
    'docEmbed': 'docs-doc',
    'sheetEmbed': 'sheets-sheet',
    'imageEmbed': 'image',
    'fileEmbed': 'file',
    'audioEmbed': 'audio',
    'pdfEmbed': 'pdf',
    'bookEmbed': 'book',
    'mapsEmbed': 'maps',
    'recordingEmbed': 'recording'
  };

  const newType = typeMapping[oldNode.type] || 'web-website';
  
  // Create the new unified embed node attributes
  const newAttrs: EmbedNodeAttributes = {
    id,
    type: newType,
    status: attrs.status || 'finished',
    contentRef: attrs.contentRef || null,
    url: attrs.url || null,
    title: attrs.title || null,
    description: attrs.description || null,
    favicon: attrs.favicon || null,
    image: attrs.image || null,
    language: attrs.language || null,
    filename: attrs.filename || null,
    rows: attrs.rows || null,
    cols: attrs.cols || null,
    cellCount: attrs.cellCount || null
  };

  // Create the new unified embed node
  return {
    type: 'embed',
    attrs: newAttrs
  };
}

/**
 * Check if content needs migration (contains old embed node types)
 */
export function needsMigration(content: any): boolean {
  if (!content || !content.content) {
    return false;
  }

  return hasOldEmbedNodes(content.content);
}

/**
 * Recursively check if any nodes are old embed types
 */
function hasOldEmbedNodes(nodes: any[]): boolean {
  for (const node of nodes) {
    if (isOldEmbedNode(node)) {
      return true;
    }
    
    if (node.content && Array.isArray(node.content)) {
      if (hasOldEmbedNodes(node.content)) {
        return true;
      }
    }
  }
  
  return false;
}
