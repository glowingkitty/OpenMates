// Main entry point for the unified message parsing architecture
// Handles both write_mode (editing) and read_mode (display) parsing

import { EmbedNodeAttributes, ParseMessageOptions } from './types';
import { EMBED_PATTERNS, generateUUID } from './utils';
import { markdownToTipTap } from './serializers';

/**
 * Unified message parser for both write and read modes
 * @param markdown - The raw markdown content to parse
 * @param mode - 'write' for editing mode, 'read' for display mode
 * @param opts - Parsing options including feature flags
 * @returns TipTap document JSON with unified embed nodes
 */
export function parse_message(markdown: string, mode: 'write' | 'read', opts: ParseMessageOptions = {}): any {
  // If unified parsing is not enabled, fallback to existing behavior
  if (!opts.unifiedParsingEnabled) {
    return markdownToTipTap(markdown);
  }
  
  console.debug('[parse_message] Parsing with unified architecture:', { mode, length: markdown.length });
  
  // First, parse basic markdown structure using existing parser
  const basicDoc = markdownToTipTap(markdown);
  
  // Parse normal embed nodes
  const embedNodes = parseEmbedNodes(markdown, mode);
  
  // Handle streaming semantics for partial/unclosed blocks
  const streamingData = handleStreamingSemantics(markdown, mode);
  
  // Combine normal embeds with partial embeds for write mode
  const allEmbeds = mode === 'write' 
    ? [...embedNodes, ...streamingData.partialEmbeds]
    : embedNodes;
  
  // Create a new document with unified embed nodes
  const unifiedDoc = enhanceDocumentWithEmbeds(basicDoc, allEmbeds, mode);
  
  // Add streaming metadata for write mode highlighting
  if (mode === 'write' && streamingData.unclosedBlocks.length > 0) {
    unifiedDoc._streamingData = streamingData;
  }
  
  console.debug('[parse_message] Created unified document with embeds:', { 
    embedCount: allEmbeds.length,
    unclosedBlocks: streamingData.unclosedBlocks.length,
    mode 
  });
  
  return unifiedDoc;
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
    
    // Parse code fences: ```<lang>[:relative/path]
    if (line.startsWith('```') && !line.startsWith('```document_html')) {
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
          language,
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
    
    // Parse URLs and YouTube links
    const urlMatches = line.match(EMBED_PATTERNS.URL);
    if (urlMatches) {
      for (const url of urlMatches) {
        const id = generateUUID();
        let type = 'web';
        
        // Check if it's a YouTube URL
        if (EMBED_PATTERNS.YOUTUBE_URL.test(url)) {
          type = 'video';
        }
        
        embedNodes.push({
          id,
          type,
          status: mode === 'write' ? 'processing' : 'finished',
          contentRef: `stream:${id}`,
          url
        });
      }
    }
    
    i++;
  }
  
  return embedNodes;
}

/**
 * Enhance a TipTap document with unified embed nodes
 * @param doc - The basic TipTap document
 * @param embedNodes - Array of detected embed node attributes
 * @param mode - 'write' or 'read' mode
 * @returns Enhanced TipTap document with unified embed nodes
 */
export function enhanceDocumentWithEmbeds(doc: any, embedNodes: EmbedNodeAttributes[], mode: 'write' | 'read'): any {
  if (!doc || !doc.content || embedNodes.length === 0) {
    return doc;
  }
  
  // Create a map of embed nodes by their position in the text
  const embedMap = new Map<number, EmbedNodeAttributes>();
  
  // For now, append embeds at the end (in later iterations, we'll detect exact positions)
  const enhancedContent = [...doc.content];
  
  // Add unified embed nodes
  embedNodes.forEach(embedAttrs => {
    enhancedContent.push({
      type: 'embed',
      attrs: embedAttrs
    });
  });
  
  return {
    ...doc,
    content: enhancedContent
  };
}

/**
 * Handle streaming semantics for partial/unclosed blocks
 * In write mode, emit highlighted-but-unclosed nodes
 * In read mode, finalize nodes and rekey content references
 */
export function handleStreamingSemantics(markdown: string, mode: 'write' | 'read'): {
  partialEmbeds: EmbedNodeAttributes[];
  unclosedBlocks: { type: string; startLine: number; content: string }[];
} {
  const lines = markdown.split('\n');
  const partialEmbeds: EmbedNodeAttributes[] = [];
  const unclosedBlocks: { type: string; startLine: number; content: string }[] = [];
  
  // Also check for inline unclosed fences in the full text
  if (mode === 'write') {
    detectInlineUnclosedFences(markdown, partialEmbeds, unclosedBlocks);
  }
  
  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trim();
    
    // Detect unclosed code fences
    if (line.startsWith('```')) {
      const codeMatch = line.match(EMBED_PATTERNS.CODE_FENCE_START);
      if (codeMatch) {
        const [, language, path] = codeMatch;
        let content = '';
        let j = i + 1;
        let foundClosing = false;
        
        // Look for closing fence
        while (j < lines.length) {
          if (lines[j].trim().startsWith('```')) {
            foundClosing = true;
            break;
          }
          content += lines[j] + '\n';
          j++;
        }
        
        if (!foundClosing && mode === 'write') {
          // In write mode, create a partial embed for highlighting
          const id = generateUUID();
          partialEmbeds.push({
            id,
            type: 'code',
            status: 'processing',
            contentRef: `stream:${id}`,
            language,
            filename: path || undefined
          });
          
          unclosedBlocks.push({
            type: 'code',
            startLine: i,
            content: line + '\n' + content
          });
        } else if (foundClosing) {
          // Normal processing for closed blocks
          i = j; // Skip to end of fence
        }
      }
    }
    
    // Detect unclosed document_html fences
    else if (line.startsWith('```document_html')) {
      let content = '';
      let j = i + 1;
      let foundClosing = false;
      
      while (j < lines.length) {
        if (lines[j].trim().startsWith('```')) {
          foundClosing = true;
          break;
        }
        content += lines[j] + '\n';
        j++;
      }
      
      if (!foundClosing && mode === 'write') {
        const id = generateUUID();
        partialEmbeds.push({
          id,
          type: 'doc',
          status: 'processing',
          contentRef: `stream:${id}`
        });
        
        unclosedBlocks.push({
          type: 'document_html',
          startLine: i,
          content: line + '\n' + content
        });
      } else if (foundClosing) {
        i = j; // Skip to end of fence
      }
    }
    
    // Detect partial table structures
    else if (EMBED_PATTERNS.TABLE_FENCE.test(line)) {
      let tableContent = '';
      let j = i;
      let hasHeaderSeparator = false;
      
      // Check if this looks like a complete table or partial
      while (j < lines.length && (EMBED_PATTERNS.TABLE_FENCE.test(lines[j].trim()) || lines[j].trim() === '')) {
        const currentLine = lines[j].trim();
        if (currentLine) {
          tableContent += currentLine + '\n';
          // Check for header separator (e.g., |---|---|)
          if (currentLine.includes('---')) {
            hasHeaderSeparator = true;
          }
        }
        j++;
      }
      
      // In write mode, if we have table rows but it looks incomplete, mark as partial
      if (mode === 'write' && tableContent && !hasHeaderSeparator) {
        const id = generateUUID();
        partialEmbeds.push({
          id,
          type: 'sheet',
          status: 'processing',
          contentRef: `stream:${id}`
        });
        
        unclosedBlocks.push({
          type: 'table',
          startLine: i,
          content: tableContent
        });
      }
      
      i = j - 1; // Will be incremented at end of loop
    }
    
    i++;
  }
  
  console.debug('[handleStreamingSemantics]', {
    mode,
    partialEmbeds: partialEmbeds.length,
    unclosedBlocks: unclosedBlocks.length
  });
  
  return { partialEmbeds, unclosedBlocks };
}

/**
 * Finalize streaming content by rekeying content references and updating status
 * @param embedNodes - Array of embed nodes to finalize
 * @param contentStore - ContentStore instance for rekeying operations
 */
export async function finalizeStreamingContent(
  embedNodes: EmbedNodeAttributes[],
  contentStore: any
): Promise<EmbedNodeAttributes[]> {
  const finalizedNodes: EmbedNodeAttributes[] = [];
  
  for (const node of embedNodes) {
    if (node.status === 'processing' && node.contentRef.startsWith('stream:')) {
      try {
        // Rekey the content from stream to CID
        const newContentRef = await contentStore.rekeyStreamToCid(node.contentRef);
        
        // Update the node with final status and CID
        const finalizedNode: EmbedNodeAttributes = {
          ...node,
          status: 'finished',
          contentRef: newContentRef,
          contentHash: newContentRef.replace('cid:sha256:', '') // Extract hash from CID
        };
        
        finalizedNodes.push(finalizedNode);
        console.debug('[finalizeStreamingContent] Finalized node:', finalizedNode.id);
      } catch (error) {
        console.warn('[finalizeStreamingContent] Failed to finalize node:', node.id, error);
        // Keep the node in processing state if finalization fails
        finalizedNodes.push(node);
      }
    } else {
      // Node is already finalized or doesn't need finalization
      finalizedNodes.push(node);
    }
  }
  
  return finalizedNodes;
}

/**
 * Detect inline unclosed fences that may appear anywhere in the text
 * This handles cases where code fences are not at the start of a line
 */
function detectInlineUnclosedFences(
  markdown: string,
  partialEmbeds: EmbedNodeAttributes[],
  unclosedBlocks: { type: string; startLine: number; content: string }[]
): void {
  const lines = markdown.split('\n');
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    
    // Look for code fences anywhere in the line
    const codeFenceRegex = /```(\w+)(?::(.+?))?/g;
    let codeFenceMatch;
    while ((codeFenceMatch = codeFenceRegex.exec(line)) !== null) {
      const [fullMatch, language, path] = codeFenceMatch;
      const fenceIndex = codeFenceMatch.index;
      
      // Check if there's a closing fence
      let foundClosing = false;
      let content = '';
      
      // Look for closing fence in the same line first
      const afterFence = line.substring(fenceIndex + fullMatch.length);
      if (afterFence.includes('```')) {
        foundClosing = true;
      } else {
        // Look for closing fence in subsequent lines
        for (let j = i + 1; j < lines.length; j++) {
          if (lines[j].includes('```')) {
            foundClosing = true;
            break;
          }
          content += lines[j] + '\n';
        }
      }
      
      // Only consider it an unclosed fence if there's content after the opening fence
      if (!foundClosing && content.trim()) {
        console.debug('[detectInlineUnclosedFences] Found unclosed code fence:', {
          language,
          path,
          line: i,
          fenceIndex,
          fullMatch
        });
        
        const id = generateUUID();
        partialEmbeds.push({
          id,
          type: 'code',
          status: 'processing',
          contentRef: `stream:${id}`,
          language,
          filename: path || undefined
        });
        
        unclosedBlocks.push({
          type: 'code',
          startLine: i,
          content: line.substring(fenceIndex) + '\n' + content
        });
      }
    }
    
    // Look for table patterns
    if (EMBED_PATTERNS.TABLE_FENCE.test(line)) {
      // Check if this is a complete table or partial
      let hasHeaderSeparator = false;
      
      // Look ahead to see if there are more table rows and a header separator
      for (let j = i; j < lines.length && EMBED_PATTERNS.TABLE_FENCE.test(lines[j]); j++) {
        if (lines[j].includes('---')) {
          hasHeaderSeparator = true;
          break;
        }
      }
      
      // Only consider it an incomplete table if we have multiple rows but no header separator
      if (!hasHeaderSeparator && i + 1 < lines.length && EMBED_PATTERNS.TABLE_FENCE.test(lines[i + 1])) {
        console.debug('[detectInlineUnclosedFences] Found incomplete table:', {
          line: i,
          content: line
        });
        
        const id = generateUUID();
        partialEmbeds.push({
          id,
          type: 'sheet',
          status: 'processing',
          contentRef: `stream:${id}`
        });
        
        unclosedBlocks.push({
          type: 'table',
          startLine: i,
          content: line
        });
      }
    }
    
    // Look for URLs that aren't in complete link format
    const urlMatches = line.match(EMBED_PATTERNS.URL);
    if (urlMatches) {
      for (const url of urlMatches) {
        // Only highlight URLs that are not already in markdown link format
        if (!line.includes(`[${url}](`)) {
          console.debug('[detectInlineUnclosedFences] Found URL:', {
            url,
            line: i
          });
          
          const id = generateUUID();
          let type = 'web';
          
          // Check if it's a YouTube URL
          if (EMBED_PATTERNS.YOUTUBE_URL.test(url)) {
            type = 'video';
          }
          
          partialEmbeds.push({
            id,
            type,
            status: 'processing',
            contentRef: `stream:${id}`,
            url
          });
          
          unclosedBlocks.push({
            type: 'url',
            startLine: i,
            content: url
          });
        }
      }
    }
  }
}
