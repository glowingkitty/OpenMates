// Serializers for the unified message parsing architecture
// Handles conversion between different formats and clipboard operations

import { EmbedNodeAttributes, EmbedType, EmbedClipboardData } from './types';

/**
 * Convert TipTap document JSON to canonical markdown format for sending
 * This ensures embeds are serialized in a standard way that can be parsed consistently
 */
export function tipTapToCanonicalMarkdown(doc: any): string {
  if (!doc || !doc.content) {
    return '';
  }
  
  const lines: string[] = [];
  
  for (const node of doc.content) {
    switch (node.type) {
      case 'paragraph':
        lines.push(serializeParagraph(node));
        break;
      
      case 'embed':
        lines.push(serializeEmbedToMarkdown(node.attrs));
        break;
      
      case 'heading':
        lines.push(serializeHeading(node));
        break;
      
      case 'bulletList':
      case 'orderedList':
        lines.push(serializeList(node));
        break;
      
      case 'blockquote':
        lines.push(serializeBlockquote(node));
        break;
      
      default:
        // For unknown nodes, try to extract text content
        lines.push(extractTextContent(node));
    }
  }
  
  return lines.filter(line => line.length > 0).join('\n\n');
}

/**
 * Convert markdown to TipTap document JSON format for display
 * This parses markdown and creates appropriate TipTap nodes including embeds
 */
export function markdownToTipTap(markdown: string): any {
  // Simple fallback implementation for testing
  // In later phases, this will be enhanced with unified embed handling
  console.debug('[markdownToTipTap] Parsing markdown:', markdown.substring(0, 100));
  
  if (!markdown.trim()) {
    return {
      type: 'doc',
      content: []
    };
  }
  
  // Create a simple paragraph with the markdown text
  return {
    type: 'doc',
    content: [
      {
        type: 'paragraph',
        content: [
          {
            type: 'text',
            text: markdown
          }
        ]
      }
    ]
  };
}

/**
 * Create clipboard data for embed nodes
 * Generates both text/markdown representation and JSON payload for rich copy/paste
 */
export function createEmbedClipboardData(attrs: EmbedNodeAttributes): EmbedClipboardData {
  return {
    version: 1,
    id: attrs.id,
    type: attrs.type,
    language: attrs.language,
    filename: attrs.filename,
    contentRef: attrs.contentRef,
    contentHash: attrs.contentHash,
    inlineContent: undefined // Will be filled during implementation with actual content
  };
}

/**
 * Parse clipboard JSON data back to embed attributes
 * Used when pasting embeds to reconstruct the node properly
 */
export function parseEmbedClipboardData(data: EmbedClipboardData): EmbedNodeAttributes {
  return {
    id: data.id,
    type: data.type,
    status: 'finished', // Clipboard data represents completed embeds
    contentRef: data.contentRef,
    contentHash: data.contentHash,
    language: data.language,
    filename: data.filename
  };
}

/**
 * Serialize embed node to canonical markdown format
 */
function serializeEmbedToMarkdown(attrs: EmbedNodeAttributes): string {
  switch (attrs.type) {
    case 'code':
      const pathSuffix = attrs.filename ? `:${attrs.filename}` : '';
      return `\`\`\`${attrs.language || ''}${pathSuffix}\n\`\`\``;
    
    case 'doc':
      let result = '```document_html\n';
      if (attrs.title) {
        result += `<!-- title: "${attrs.title}" -->\n`;
      }
      result += '```';
      return result;
    
    case 'sheet':
      let tableResult = '';
      if (attrs.title) {
        tableResult += `<!-- title: "${attrs.title}" -->\n\n`;
      }
      // Create a simple table placeholder
      tableResult += '| Column 1 | Column 2 |\n';
      tableResult += '|----------|----------|\n';
      tableResult += '| Data     | Data     |';
      return tableResult;
    
    case 'video':
    case 'web':
      return attrs.url || '';
    
    default:
      return '';
  }
}

/**
 * Serialize paragraph node to markdown
 */
function serializeParagraph(node: any): string {
  if (!node.content) return '';
  
  return node.content.map((child: any) => {
    if (child.type === 'text') {
      let text = child.text || '';
      
      // Apply marks
      if (child.marks) {
        for (const mark of child.marks) {
          switch (mark.type) {
            case 'bold':
              text = `**${text}**`;
              break;
            case 'italic':
              text = `*${text}*`;
              break;
            case 'code':
              text = `\`${text}\``;
              break;
            case 'link':
              text = `[${text}](${mark.attrs?.href || ''})`;
              break;
          }
        }
      }
      
      return text;
    }
    return '';
  }).join('');
}

/**
 * Serialize heading node to markdown
 */
function serializeHeading(node: any): string {
  const level = node.attrs?.level || 1;
  const prefix = '#'.repeat(Math.min(level, 6));
  const text = extractTextContent(node);
  return `${prefix} ${text}`;
}

/**
 * Serialize list node to markdown
 */
function serializeList(node: any): string {
  if (!node.content) return '';
  
  const isOrdered = node.type === 'orderedList';
  const lines: string[] = [];
  
  node.content.forEach((item: any, index: number) => {
    const prefix = isOrdered ? `${index + 1}. ` : '- ';
    const text = extractTextContent(item);
    lines.push(`${prefix}${text}`);
  });
  
  return lines.join('\n');
}

/**
 * Serialize blockquote node to markdown
 */
function serializeBlockquote(node: any): string {
  const text = extractTextContent(node);
  return text.split('\n').map(line => `> ${line}`).join('\n');
}

/**
 * Extract text content from a node recursively
 */
function extractTextContent(node: any): string {
  if (!node) return '';
  
  if (node.type === 'text') {
    return node.text || '';
  }
  
  if (node.content) {
    return node.content.map(extractTextContent).join('');
  }
  
  return '';
}
