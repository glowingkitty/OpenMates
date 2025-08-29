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
              type: 'web',
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
  if (!doc || !doc.content) {
    return doc;
  }
  
  // If there are no embed nodes, return the original document
  if (embedNodes.length === 0) {
    return doc;
  }
  
  // For json_embed blocks, we need to replace them in the text, not just append
  let modifiedContent = [...doc.content];
  
  console.debug('[enhanceDocumentWithEmbeds] Processing document with', embedNodes.length, 'embed nodes');
  
  // Find and replace json_embed blocks with embed nodes
  modifiedContent = modifiedContent.map(node => {
    if (node.type === 'paragraph' && node.content) {
      const newParagraphContent = [];
      
      for (const contentNode of node.content) {
        if (contentNode.type === 'text' && contentNode.text) {
          // Split text by json_embed blocks and create appropriate nodes
          const parts = splitTextByJsonEmbedBlocks(contentNode.text, embedNodes);
          newParagraphContent.push(...parts);
        } else {
          newParagraphContent.push(contentNode);
        }
      }
      
      return {
        ...node,
        content: newParagraphContent
      };
    }
    return node;
  });
  
  return {
    ...doc,
    content: modifiedContent
  };
}

/**
 * Split text content by json_embed blocks and replace them with embed nodes
 * @param text - The text content that may contain json_embed blocks
 * @param embedNodes - Array of embed nodes to use for replacement
 * @returns Array of text nodes and embed nodes
 */
function splitTextByJsonEmbedBlocks(text: string, embedNodes: EmbedNodeAttributes[]): any[] {
  const result = [];
  
  // Filter to only get web embed nodes that came from json_embed blocks
  const webEmbedNodes = embedNodes.filter(node => node.type === 'web');
  
  // If no web embed nodes, return the original text
  if (webEmbedNodes.length === 0) {
    result.push({
      type: 'text',
      text: text
    });
    return result;
  }
  
  // Find all json_embed blocks in the text and match them with embed nodes
  const jsonEmbedRegex = /```json_embed\n[\s\S]*?\n```/g;
  const embedMatches: { match: RegExpExecArray; embedNode: EmbedNodeAttributes }[] = [];
  let match;
  let embedIndex = 0;
  
  // Reset regex lastIndex to ensure we get all matches
  jsonEmbedRegex.lastIndex = 0;
  
  while ((match = jsonEmbedRegex.exec(text)) !== null && embedIndex < webEmbedNodes.length) {
    try {
      // Extract and parse the json content to match with the right embed node
      const jsonContent = match[0].match(/```json_embed\n([\s\S]*?)\n```/)?.[1];
      if (jsonContent) {
        const parsed = JSON.parse(jsonContent);
        
        // Find the corresponding embed node by URL
        const correspondingEmbedNode = webEmbedNodes.find(node => node.url === parsed.url);
        if (correspondingEmbedNode) {
          embedMatches.push({ match, embedNode: correspondingEmbedNode });
          console.debug('[splitTextByJsonEmbedBlocks] Matched json_embed block with embed node:', {
            url: parsed.url,
            embedNodeId: correspondingEmbedNode.id
          });
        }
      }
    } catch (error) {
      console.warn('[splitTextByJsonEmbedBlocks] Error parsing json_embed block:', error);
      // Still try to match by order if parsing fails
      if (embedIndex < webEmbedNodes.length) {
        embedMatches.push({ match, embedNode: webEmbedNodes[embedIndex] });
      }
    }
    embedIndex++;
  }
  
  // If no matches found, return original text
  if (embedMatches.length === 0) {
    result.push({
      type: 'text',
      text: text
    });
    return result;
  }
  
  // Sort matches by position to process them in order
  embedMatches.sort((a, b) => a.match.index - b.match.index);
  
  let lastIndex = 0;
  
  for (const { match, embedNode } of embedMatches) {
    // Add text before the json_embed block
    if (match.index > lastIndex) {
      const beforeText = text.substring(lastIndex, match.index);
      if (beforeText.trim() || beforeText.includes('\n')) {
        result.push({
          type: 'text',
          text: beforeText
        });
      }
    }
    
    console.debug('[splitTextByJsonEmbedBlocks] Replacing json_embed block with embed node:', embedNode);
    
    // Add the corresponding embed node
    result.push({
      type: 'embed',
      attrs: embedNode
    });
    
    lastIndex = match.index + match[0].length;
  }
  
  // Add remaining text after the last json_embed block
  if (lastIndex < text.length) {
    const afterText = text.substring(lastIndex);
    if (afterText.trim() || afterText.includes('\n')) {
      result.push({
        type: 'text',
        text: afterText
      });
    }
  }
  
  // If no content was added, ensure we have at least the original text
  if (result.length === 0) {
    result.push({
      type: 'text',
      text: text
    });
  }
  
  return result;
}

/**
 * Handle streaming semantics for partial/unclosed blocks
 * In write mode, emit highlighted-but-unclosed nodes
 * In read mode, finalize nodes and rekey content references
 */
export function handleStreamingSemantics(markdown: string, mode: 'write' | 'read'): {
  partialEmbeds: EmbedNodeAttributes[];
  unclosedBlocks: { type: string; startLine: number; content: string; tokenStartCol?: number; tokenEndCol?: number }[];
} {
  const lines = markdown.split('\n');
  const partialEmbeds: EmbedNodeAttributes[] = [];
  const unclosedBlocks: { type: string; startLine: number; content: string }[] = [];
  
  // Also check for inline unclosed fences in the full text
  if (mode === 'write') {
      detectInlineUnclosedFences(markdown, mode, partialEmbeds, unclosedBlocks);
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
            language: language || undefined,
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
      
      // Remove empty lines from table content to prevent spacing issues
      tableContent = tableContent.replace(/\n\s*\n/g, '\n');
      
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
  mode: 'write' | 'read',
  partialEmbeds: EmbedNodeAttributes[],
  unclosedBlocks: { type: string; startLine: number; content: string; tokenStartCol?: number; tokenEndCol?: number }[]
): void {
  const lines = markdown.split('\n');
  // Track whether we are inside a triple backtick code fence block.
  // When true, we should not emit markdown token highlights for this region.
  let inCodeFence = false;
  // Track whether we are inside a document_html fenced block
  let inDocFence = false;
  // Track whether we are inside a json_embed fenced block
  let inJsonEmbedFence = false;
  // Track whether we are inside a table block (contiguous table lines)
  let inTableBlock = false;
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    const isDocFenceStart = trimmed.startsWith('```document_html');
    const isJsonEmbedFenceStart = trimmed.startsWith('```json_embed');
    const isAnyFenceLine = trimmed.startsWith('```');
    const isCodeFenceLine = isAnyFenceLine && !isDocFenceStart && !isJsonEmbedFenceStart;
    
    // Look for code fences anywhere in the line (but skip if inside json_embed or doc fences)
    // Updated regex to handle:
    // - Code fences with language and optional path: ```python:test.py
    // - Code fences without language: ```
    // - Code fences with language only: ```python
    if (!inJsonEmbedFence && !inDocFence) {
      const codeFenceRegex = /```(\w+)?(?::([^`\n]+))?/g;
      let codeFenceMatch;
      while ((codeFenceMatch = codeFenceRegex.exec(line)) !== null) {
        const [fullMatch, language, path] = codeFenceMatch;
        const fenceIndex = codeFenceMatch.index;
        
        // Skip if this is a json_embed or document_html fence
        if (fullMatch.includes('json_embed') || fullMatch.includes('document_html')) {
          continue;
        }
        
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
        
        // For code fences, we want to highlight even if there's no content yet
        // This ensures the blue color is maintained after typing the colon
        if (!foundClosing) {
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
            language: language || undefined,
            filename: path || undefined
          });
          
          unclosedBlocks.push({
            type: 'code',
            startLine: i,
            content: line.substring(fenceIndex) + '\n' + content
          });
        }
      }
    }
    
    // Look for table patterns: highlight contiguous table block, allowing single/multiple blank lines between rows
    if (EMBED_PATTERNS.TABLE_FENCE.test(line)) {
      let tableContent = '';
      let j = i;
      while (j < lines.length) {
        const current = lines[j];
        const currentTrim = current.trim();
        if (currentTrim === '') {
          // Look ahead over blank lines; continue table if next non-blank is a table row
          let k = j + 1;
          while (k < lines.length && lines[k].trim() === '') k++;
          if (k < lines.length && EMBED_PATTERNS.TABLE_FENCE.test(lines[k].trim())) {
            // Include the blank line(s) as part of the block (to keep continuous range)
            tableContent += currentTrim + '\n';
            j = k;
            continue;
          }
          break;
        }
        if (!EMBED_PATTERNS.TABLE_FENCE.test(currentTrim)) break;
        tableContent += currentTrim + '\n';
        j++;
      }
      if (mode === 'write' && tableContent) {
        const id = generateUUID();
        partialEmbeds.push({ id, type: 'sheet', status: 'processing', contentRef: `stream:${id}` });
        unclosedBlocks.push({ type: 'table', startLine: i, content: tableContent });
      }
      i = j - 1;
    }
    
    // Look for URLs that aren't part of markdown links [text](url)
    // Skip URL detection if we're inside ANY type of code block
    if (!(inCodeFence || inDocFence || inJsonEmbedFence)) {
      // Build protected ranges for URL segments within markdown links
      const protectedRanges: Array<{ start: number; end: number }> = [];
      const linkRegex = /\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/g;
      let lm: RegExpExecArray | null;
      while ((lm = linkRegex.exec(line)) !== null) {
        const full = lm[0];
        const url = lm[1];
        const urlStartInFull = full.indexOf('(') + 1; // start of URL inside (...)
        const absStart = (lm.index ?? 0) + urlStartInFull;
        protectedRanges.push({ start: absStart, end: absStart + url.length });
      }

      const urlRegex = /https?:\/\/[^\s]+/g;
      let um: RegExpExecArray | null;
      while ((um = urlRegex.exec(line)) !== null) {
        const url = um[0];
        const startIdx = um.index ?? 0;
        const isProtected = protectedRanges.some(r => startIdx >= r.start && startIdx < r.end);
        if (isProtected) continue;

        console.debug('[detectInlineUnclosedFences] Found URL:', { url, line: i });
        const id = generateUUID();
        let type = 'web';
        let blockType = 'url';
        if (EMBED_PATTERNS.YOUTUBE_URL.test(url)) { type = 'video'; blockType = 'video'; }
        partialEmbeds.push({ id, type, status: 'processing', contentRef: `stream:${id}`, url });
        unclosedBlocks.push({ type: blockType, startLine: i, content: url });
      }
    }
    
    // Look for markdown syntax like headings, bold, italic, etc.
    if (mode === 'write') {
      // Maintain table block state: enter on table row, exit on blank line
      if (EMBED_PATTERNS.TABLE_FENCE.test(line)) {
        inTableBlock = true;
      } else if (trimmed === '') {
        inTableBlock = false;
      }

      // Skip markdown token highlighting inside code/doc/json_embed/table regions or on fence lines
      if (!(inCodeFence || inDocFence || inJsonEmbedFence || inTableBlock || isAnyFenceLine)) {
      // Helper to push an exact token range for markdown syntax
      const pushToken = (start: number, end: number) => {
        if (start == null || end == null || end <= start) return;
        const id = generateUUID();
        partialEmbeds.push({ id, type: 'markdown', status: 'processing', contentRef: `stream:${id}` });
        unclosedBlocks.push({ type: 'markdown', startLine: i, content: line.slice(start, end), tokenStartCol: start, tokenEndCol: end });
      };

      // Headings: highlight only the leading # run
      const h = line.match(EMBED_PATTERNS.HEADING);
      if (h && h[1]) pushToken(0, h[1].length);

      // Bold tokens: ** or __
      {
        const boldRegex = /\*\*|__/g;
        let m: RegExpExecArray | null;
        while ((m = boldRegex.exec(line)) !== null) {
          const idx = m.index; pushToken(idx, idx + m[0].length);
        }
      }

      // Italic tokens: * or _ not part of bold
      {
        const italicRegex = /\*|_/g;
        let m: RegExpExecArray | null;
        while ((m = italicRegex.exec(line)) !== null) {
          const idx = m.index; const ch = m[0];
          const prev = idx > 0 ? line[idx - 1] : ''; const next = idx + 1 < line.length ? line[idx + 1] : '';
          if (prev === ch || next === ch) continue; // part of ** or __
          pushToken(idx, idx + 1);
        }
      }

      // Strikethrough: ~~
      {
        const strikeRegex = /~~/g;
        let m: RegExpExecArray | null;
        while ((m = strikeRegex.exec(line)) !== null) {
          const idx = m.index; pushToken(idx, idx + 2);
        }
      }

      // Blockquotes at start of line: >> or >
      if (line.startsWith('>>')) pushToken(0, 2); else if (line.startsWith('>')) pushToken(0, 1);

      // Unordered list markers at start: -, *, + followed by space
      const ul = line.match(/^([-*+])(\s+)/); if (ul) pushToken(0, ul[1].length);

      // Ordered list markers: number. at start
      const ol = line.match(/^(\d+\.)/); if (ol && ol[1]) pushToken(0, ol[1].length);

      // Task list: - [ ] or - [x]
      if (/^- \[[ x]\]/.test(line)) {
        pushToken(0, 1); // '-'
        const openIdx = line.indexOf('['); if (openIdx !== -1) pushToken(openIdx, openIdx + 1);
        const closeIdx = line.indexOf(']'); if (closeIdx !== -1) pushToken(closeIdx, closeIdx + 1);
      }

      // Link/image syntax tokens: [, ], (, ), and leading '!'
      {
        const bracketRegex = /\[|\]|\(|\)/g;
        let m: RegExpExecArray | null;
        while ((m = bracketRegex.exec(line)) !== null) {
          const idx = m.index; pushToken(idx, idx + 1);
        }
      }
      const bangIdx = line.indexOf('!['); if (bangIdx !== -1) pushToken(bangIdx, bangIdx + 1);
      }
    }

    // Toggle fence states after processing the line
    if (isJsonEmbedFenceStart) {
      inJsonEmbedFence = !inJsonEmbedFence; // opening line of json_embed
    } else if (inJsonEmbedFence && isAnyFenceLine) {
      // Any ``` that occurs while inside json_embed closes it
      inJsonEmbedFence = false;
    } else if (isDocFenceStart) {
      inDocFence = !inDocFence; // opening line of document_html
    } else if (inDocFence && isAnyFenceLine) {
      // Any ``` that occurs while inside document_html closes it
      inDocFence = false;
    } else if (!inDocFence && !inJsonEmbedFence && isCodeFenceLine) {
      // Regular code fence toggle (only if not inside doc or json_embed)
      inCodeFence = !inCodeFence;
    }
  }
}
