// Streaming semantics for partial/unclosed blocks
// Handles detection and processing of incomplete content during writing
// Uses the shared CodeBlockStateMachine for reliable code fence detection

import { EmbedNodeAttributes } from './types';
import { EMBED_PATTERNS, generateUUID, CodeBlockStateMachine } from './utils';

/**
 * Handle streaming semantics for partial/unclosed blocks
 * In write mode, emit highlighted-but-unclosed nodes for visual feedback
 * Uses the shared CodeBlockStateMachine for reliable fence detection
 */
export function handleStreamingSemantics(markdown: string, mode: 'write' | 'read'): {
  partialEmbeds: EmbedNodeAttributes[];
  unclosedBlocks: { type: string; startLine: number; content: string; tokenStartCol?: number; tokenEndCol?: number }[];
} {
  const lines = markdown.split('\n');
  const partialEmbeds: EmbedNodeAttributes[] = [];
  const unclosedBlocks: { type: string; startLine: number; content: string; tokenStartCol?: number; tokenEndCol?: number }[] = [];
  
  // Use the shared state machine for reliable code block detection
  const stateMachine = new CodeBlockStateMachine();
  
  // Process all lines through the state machine
  for (let i = 0; i < lines.length; i++) {
    stateMachine.processLine(lines[i], i);
  }
  
  // After processing all lines, check if we have an unclosed block
  if (stateMachine.isInsideCodeBlock() && mode === 'write') {
    const partialInfo = stateMachine.getPartialBlockInfo();
    if (partialInfo) {
      const id = generateUUID();
      
      // Determine type based on special fence or language
      let embedType = 'code';
      if (partialInfo.specialFence === 'document_html') {
        embedType = 'doc';
      } else if (partialInfo.specialFence === 'json_embed' || partialInfo.specialFence === 'json') {
        // Skip json_embed and json blocks - they shouldn't create partial embeds
        // These are internal formats
      }
      
      if (embedType !== 'code' || !partialInfo.specialFence) {
        partialEmbeds.push({
          id,
          type: embedType,
          status: 'processing',
          contentRef: `stream:${id}`,
          language: partialInfo.language || undefined,
          filename: partialInfo.filename || undefined
        });
        
        unclosedBlocks.push({
          type: partialInfo.specialFence === 'document_html' ? 'document_html' : 'code',
          startLine: partialInfo.startLine,
          content: partialInfo.content
        });
      }
    }
  }
  
  // Also detect non-code-block elements (URLs, tables, markdown syntax)
  if (mode === 'write') {
    detectNonCodeBlockElements(lines, partialEmbeds, unclosedBlocks);
  }
  
  console.debug('[handleStreamingSemantics] Results:', {
    mode,
    partialEmbeds: partialEmbeds.length,
    unclosedBlocks: unclosedBlocks.length,
    unclosedBlockTypes: unclosedBlocks.map(b => b.type)
  });
  
  return { partialEmbeds, unclosedBlocks };
}

/**
 * Detect non-code-block elements for highlighting (URLs, tables, markdown syntax)
 * Uses the shared state machine to skip content inside code blocks
 */
function detectNonCodeBlockElements(
  lines: string[],
  partialEmbeds: EmbedNodeAttributes[],
  unclosedBlocks: { type: string; startLine: number; content: string; tokenStartCol?: number; tokenEndCol?: number }[]
): void {
  // Use a fresh state machine to track code blocks
  const stateMachine = new CodeBlockStateMachine();
  let inTableBlock = false;
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    const event = stateMachine.processLine(line, i);
    
    // Skip lines inside code blocks
    if (event.event === 'content_line' || event.event === 'block_opened') {
      continue;
    }
    
    // Also skip the closing fence line
    if (event.event === 'block_closed') {
      continue;
    }
    
    const isAnyFenceLine = trimmed.startsWith('```');
    
    // Detect table patterns
    if (EMBED_PATTERNS.TABLE_FENCE.test(trimmed)) {
      let tableContent = '';
      let j = i;
      while (j < lines.length) {
        const current = lines[j];
        const currentTrim = current.trim();
        if (currentTrim === '') {
          // Look ahead over blank lines
          let k = j + 1;
          while (k < lines.length && lines[k].trim() === '') k++;
          if (k < lines.length && EMBED_PATTERNS.TABLE_FENCE.test(lines[k].trim())) {
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
      if (tableContent) {
        const id = generateUUID();
        partialEmbeds.push({ id, type: 'sheet', status: 'processing', contentRef: `stream:${id}` });
        unclosedBlocks.push({ type: 'table', startLine: i, content: tableContent });
      }
      // Skip processed table lines (handled by continuing to next iteration)
      inTableBlock = true;
    } else if (trimmed === '') {
      inTableBlock = false;
    }
    
    // Detect URLs (not inside code blocks)
    if (event.event === 'outside_block') {
      // Build protected ranges for URLs inside markdown links
      const protectedRanges: Array<{ start: number; end: number }> = [];
      const linkRegex = /\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/g;
      let lm: RegExpExecArray | null;
      while ((lm = linkRegex.exec(line)) !== null) {
        const full = lm[0];
        const url = lm[1];
        const urlStartInFull = full.indexOf('(') + 1;
        const absStart = (lm.index ?? 0) + urlStartInFull;
        protectedRanges.push({ start: absStart, end: absStart + url.length });
      }

      const urlRegex = /https?:\/\/[^\s]+/g;
      let um: RegExpExecArray | null;
      while ((um = urlRegex.exec(line)) !== null) {
        const url = um[0];
        const startIdx = um.index ?? 0;
        const endIdx = startIdx + url.length;
        const isProtected = protectedRanges.some(r => startIdx >= r.start && startIdx < r.end);
        if (isProtected) continue;
        
        const id = generateUUID();
        let type = 'web-website';
        let blockType = 'url';
        if (EMBED_PATTERNS.YOUTUBE_URL.test(url)) { 
          type = 'videos-video'; 
          blockType = 'video'; 
        }
        partialEmbeds.push({ id, type, status: 'processing', contentRef: `stream:${id}`, url });
        unclosedBlocks.push({ 
          type: blockType, 
          startLine: i, 
          content: url, 
          tokenStartCol: startIdx, 
          tokenEndCol: endIdx 
        });
      }
    }
    
    // Detect markdown syntax (headings, bold, italic, etc.)
    if (event.event === 'outside_block' && !inTableBlock && !isAnyFenceLine) {
      detectMarkdownSyntax(line, i, partialEmbeds, unclosedBlocks);
    }
  }
}

/**
 * Detect markdown syntax tokens for highlighting
 */
function detectMarkdownSyntax(
  line: string,
  lineIndex: number,
  partialEmbeds: EmbedNodeAttributes[],
  unclosedBlocks: { type: string; startLine: number; content: string; tokenStartCol?: number; tokenEndCol?: number }[]
): void {
  // Helper to push an exact token range for markdown syntax
  const pushToken = (start: number, end: number) => {
    if (start == null || end == null || end <= start) return;
    const id = generateUUID();
    partialEmbeds.push({ id, type: 'markdown', status: 'processing', contentRef: `stream:${id}` });
    unclosedBlocks.push({ type: 'markdown', startLine: lineIndex, content: line.slice(start, end), tokenStartCol: start, tokenEndCol: end });
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
  // BUT exclude brackets/parentheses that are part of URLs
  {
    const protectedRanges: Array<{ start: number; end: number }> = [];
    const urlRegex = /https?:\/\/[^\s]+/g;
    let urlMatch: RegExpExecArray | null;
    while ((urlMatch = urlRegex.exec(line)) !== null) {
      const urlStart = urlMatch.index ?? 0;
      const urlEnd = urlStart + urlMatch[0].length;
      protectedRanges.push({ start: urlStart, end: urlEnd });
    }
    
    const bracketRegex = /\[|\]|\(|\)/g;
    let m: RegExpExecArray | null;
    while ((m = bracketRegex.exec(line)) !== null) {
      const idx = m.index;
      const isInsideUrl = protectedRanges.some(r => idx >= r.start && idx < r.end);
      if (!isInsideUrl) {
        pushToken(idx, idx + 1);
      }
    }
  }
  const bangIdx = line.indexOf('!['); if (bangIdx !== -1) pushToken(bangIdx, bangIdx + 1);
}

/**
 * Finalize streaming content by rekeying content references and updating status
 * @param embedNodes - Array of embed nodes to finalize
 * @param embedStore - EmbedStore instance for rekeying operations
 */
export async function finalizeStreamingContent(
  embedNodes: EmbedNodeAttributes[],
  embedStore: any
): Promise<EmbedNodeAttributes[]> {
  const finalizedNodes: EmbedNodeAttributes[] = [];
  
  for (const node of embedNodes) {
    if (node.status === 'processing' && node.contentRef.startsWith('stream:')) {
      try {
        // Rekey the embed from stream to CID
        const newContentRef = await embedStore.rekeyStreamToCid(node.contentRef);
        
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
