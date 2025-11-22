// Embed node parsing functions
// Handles parsing of different embed types from markdown content

import { EmbedNodeAttributes } from './types';
import { EMBED_PATTERNS, generateUUID } from './utils';

/**
 * Map embed reference type from server to EmbedNodeType
 * @param embedType - Server embed type (app_skill_use, website, code, etc.)
 * @returns EmbedNodeType for TipTap
 */
function mapEmbedReferenceType(embedType: string): string {
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
 * Parse embed nodes from markdown content
 * Handles Path-or-Title fences for different embed types
 */
export function parseEmbedNodes(markdown: string, mode: 'write' | 'read'): EmbedNodeAttributes[] {
  const lines = markdown.split('\n');
  const embedNodes: EmbedNodeAttributes[] = [];
  let i = 0;
  
  while (i < lines.length) {
    const line = lines[i].trim();
    
    // Parse JSON code blocks for embed references (new embeds architecture)
    // Format: ```json\n{"type": "app_skill_use", "embed_id": "..."}\n```
    if (line.startsWith('```json')) {
      let content = '';
      let j = i + 1;
      while (j < lines.length && !lines[j].trim().startsWith('```')) {
        content += lines[j] + '\n';
        j++;
      }
      
      try {
        const embedRef = JSON.parse(content.trim());
        // Check if this is an embed reference (has type and embed_id)
        if (embedRef.type && embedRef.embed_id) {
          const id = generateUUID();
          embedNodes.push({
            id,
            type: mapEmbedReferenceType(embedRef.type),
            status: 'finished', // Will be updated when embed is resolved
            contentRef: `embed:${embedRef.embed_id}`, // Reference to embed in EmbedStore
            // Additional metadata will be loaded from embed when resolved
          });
          console.debug('[parseEmbedNodes] Created embed node from JSON reference:', {
            type: embedRef.type,
            embed_id: embedRef.embed_id,
            nodeId: id
          });
        }
      } catch (error) {
        // Not a valid embed reference, continue parsing
        console.debug('[parseEmbedNodes] JSON block is not an embed reference:', error);
      }
      
      i = j; // Skip to end of fence
      continue;
    }
    
    // Parse json_embed blocks for URL embeds (legacy format)
    if (line.startsWith('```json_embed')) {
      let content = '';
      let j = i + 1;
      while (j < lines.length && !lines[j].trim().startsWith('```')) {
        content += lines[j] + '\n';
        j++;
      }
      
        try {
          const embedData = JSON.parse(content.trim());
          if (embedData.type === 'website' && embedData.url) {
            const id = generateUUID();
            embedNodes.push({
              id,
              type: 'web-website',
              status: 'finished',
              contentRef: null,
              url: embedData.url,
              title: embedData.title || null,
              description: embedData.description || null,
              favicon: embedData.favicon || null,
              image: embedData.image || null
            });
            console.debug('[parseEmbedNodes] Created web embed from json_embed:', {
              url: embedData.url,
              title: embedData.title,
              hasMetadata: !!(embedData.title || embedData.description),
              hasFavicon: !!embedData.favicon,
              hasImage: !!embedData.image
            });
          }
        } catch (error) {
          console.error('[parseEmbedNodes] Error parsing json_embed block:', error);
        }
      
      i = j; // Skip to end of fence
    }
    // Parse code fences: ```<lang>[:relative/path] or ```[:relative/path]
    else if (line.startsWith('```') && !line.startsWith('```document_html')) {
      const codeMatch = line.match(EMBED_PATTERNS.CODE_FENCE_START);
      if (codeMatch) {
        const [, language, path] = codeMatch;
        const id = generateUUID();
        
        // Extract code content between fences
        let content = '';
        let j = i + 1;
        while (j < lines.length && !lines[j].trim().startsWith('```')) {
          content += lines[j] + '\n';
          j++;
        }
        
        embedNodes.push({
          id,
          type: 'code-code',
          status: mode === 'write' ? 'processing' : 'finished',
          contentRef: `stream:${id}`,
          language: language || undefined,
          filename: path || undefined,
          lineCount: content.split('\n').filter(l => l.trim()).length
        });
        
        i = j; // Skip to end of fence
      }
    }
    
    // Parse document HTML fences
    else if (line.startsWith('```document_html')) {
      const id = generateUUID();
      let title: string | undefined;
      let content = '';
      
      // Look for title in the next few lines
      for (let j = i + 1; j < Math.min(i + 5, lines.length); j++) {
        const titleMatch = lines[j].trim().match(EMBED_PATTERNS.TITLE_COMMENT);
        if (titleMatch) {
          title = titleMatch[1];
          break;
        }
      }
      
      // Extract content between fences
      let j = i + 1;
      while (j < lines.length && !lines[j].trim().startsWith('```')) {
        content += lines[j] + '\n';
        j++;
      }
      
      const wordCount = content.split(/\s+/).filter(w => w.trim()).length;
      
      embedNodes.push({
        id,
        type: 'docs-doc',
        status: mode === 'write' ? 'processing' : 'finished',
        contentRef: `stream:${id}`,
        title,
        wordCount
      });
      
      i = j; // Skip to end of fence
    }
    
    // Parse table blocks (GitHub-style markdown tables)
    else if (EMBED_PATTERNS.TABLE_FENCE.test(line)) {
      const id = generateUUID();
      let title: string | undefined;
      let tableContent = '';
      let rows = 0;
      let cols = 0;
      
      // Check for title comment in previous lines
      for (let j = Math.max(0, i - 3); j < i; j++) {
        const titleMatch = lines[j].trim().match(EMBED_PATTERNS.TITLE_COMMENT);
        if (titleMatch) {
          title = titleMatch[1];
          break;
        }
      }
      
      // Parse table rows
      let j = i;
      while (j < lines.length && EMBED_PATTERNS.TABLE_FENCE.test(lines[j].trim())) {
        const row = lines[j].trim();
        tableContent += row + '\n';
        rows++;
        
        // Count columns from first row
        if (cols === 0) {
          cols = row.split('|').filter(cell => cell.trim()).length;
        }
        j++;
      }
      
      if (rows > 0) {
        embedNodes.push({
          id,
          type: 'sheets-sheet',
          status: mode === 'write' ? 'processing' : 'finished',
          contentRef: `stream:${id}`,
          title,
          rows,
          cols,
          cellCount: rows * cols
        });
      }
      
      i = j - 1; // Will be incremented at end of loop
    }
    
    // Parse URLs and YouTube links only in read mode
    // In write mode, plain URLs are handled by handleStreamingSemantics for highlighting
    // and will be converted to json_embed blocks when closed
    // IMPORTANT: Skip URLs that are part of markdown links [text](url)
    // Only standalone URLs should be converted to embeds
    if (mode === 'read') {
      // Use the original untrimmed line for position calculations
      const originalLine = lines[i];
      
      // Build protected ranges for URL segments within markdown links
      // This prevents URLs in [text](url) format from being converted to embeds
      const protectedRanges: Array<{ start: number; end: number }> = [];
      const linkRegex = /\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/g;
      let linkMatch: RegExpExecArray | null;
      while ((linkMatch = linkRegex.exec(originalLine)) !== null) {
        const full = linkMatch[0];
        const url = linkMatch[1];
        const urlStartInFull = full.indexOf('(') + 1; // start of URL inside (...)
        const absStart = (linkMatch.index ?? 0) + urlStartInFull;
        protectedRanges.push({ start: absStart, end: absStart + url.length });
      }
      
      // Now find all URLs and check if they're protected (inside markdown links)
      const urlRegex = /https?:\/\/[^\s]+/g;
      let urlMatch: RegExpExecArray | null;
      while ((urlMatch = urlRegex.exec(originalLine)) !== null) {
        const url = urlMatch[0];
        const startIdx = urlMatch.index ?? 0;
        const endIdx = startIdx + url.length;
        
        // Skip URLs that are inside markdown link syntax [text](url)
        const isProtected = protectedRanges.some(r => startIdx >= r.start && startIdx < r.end);
        if (isProtected) {
          console.debug('[parseEmbedNodes] Skipping URL inside markdown link:', url);
          continue;
        }
        
          const id = generateUUID();
          let type = 'web-website';
          
          // Check if it's a YouTube URL
          if (EMBED_PATTERNS.YOUTUBE_URL.test(url)) {
            type = 'videos-video';
          }
          
          embedNodes.push({
            id,
            type,
            status: 'finished',
            contentRef: `stream:${id}`,
            url
          });
      }
    }
    
    i++;
  }
  
  return embedNodes;
}
