// Streaming semantics for partial/unclosed blocks
// Handles detection and processing of incomplete content during writing

import { EmbedNodeAttributes } from './types';
import { EMBED_PATTERNS, generateUUID } from './utils';

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
        let type = 'website';
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
