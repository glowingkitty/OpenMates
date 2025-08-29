// Embed node parsing functions
// Handles parsing of different embed types from markdown content

import { EmbedNodeAttributes } from './types';
import { EMBED_PATTERNS, generateUUID } from './utils';

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
    
    // Parse json_embed blocks for URL embeds
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
              type: 'website',
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
          type: 'code',
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
        type: 'doc',
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
          type: 'sheet',
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
    if (mode === 'read') {
      const urlMatches = line.match(EMBED_PATTERNS.URL);
      if (urlMatches) {
        for (const url of urlMatches) {
          const id = generateUUID();
          let type = 'website';
          
          // Check if it's a YouTube URL
          if (EMBED_PATTERNS.YOUTUBE_URL.test(url)) {
            type = 'video';
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
    }
    
    i++;
  }
  
  return embedNodes;
}
