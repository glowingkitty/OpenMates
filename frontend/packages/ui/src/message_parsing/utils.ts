// Utility functions and regexes for the unified message parsing architecture

// Regex patterns for different embed types
export const EMBED_PATTERNS = {
    // Code fence at start of line (for line-by-line parsing)
    // Updated to handle the same cases as CODE_FENCE
    CODE_FENCE_START: /^```(\w+)?(?::([^`\n]+))?\s*$/,
    
    // Table fence pattern (GitHub-style markdown tables)
    TABLE_FENCE: /^\|.*\|$/,
    
    // Title comment pattern: <!-- title: "..." -->
    TITLE_COMMENT: /^<!--\s*title:\s*["'](.+?)["']\s*-->$/,
    
    // URL pattern (http/https links)
    // Matches URLs with protocol AND common video platform URLs without protocol
    // This is more targeted than matching all URLs without protocol to avoid false positives
    // Matches:
    // - URLs with protocol: https://example.com/path, http://site.com
    // - YouTube URLs without protocol: youtube.com/watch?v=..., youtu.be/VIDEO_ID, www.youtube.com/...
    // Uses negative lookbehind to avoid matching URLs already inside other patterns
    URL: /(?:https?:\/\/[^\s\])"'<>]+|(?<![/\w@])(?:(?:www\.|m\.)?youtube\.com\/(?:watch\?v=|embed\/|shorts\/|v\/)[^\s\])"'<>]+|youtu\.be\/[^\s\])"'<>]+))/g,
    
    // YouTube URL patterns for type detection (after URL is matched)
    // Matches: youtube.com, www.youtube.com, m.youtube.com (mobile), youtu.be
    // Supports: /watch?v=, /embed/, /shorts/, /v/ (legacy) formats
    // Protocol is optional - works on both normalized and raw URLs
    YOUTUBE_URL: /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/g,
    
    // Markdown syntax patterns
    // Headings: # Heading, ## Heading, etc. - capture only the # characters
    HEADING: /^(#{1,6})/,
};

// Generate a random UUID (v4)
export function generateUUID(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

// Compute SHA256 hash of content
export async function computeSHA256(content: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(content);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

// Create content ID from SHA256 hash
export function createContentId(hash: string): string {
  return `cid:sha256:${hash}`;
}

// Create stream key from UUID
export function createStreamKey(uuid: string): string {
  return `stream:${uuid}`;
}

/**
 * Normalize a URL by adding https:// protocol if missing
 * This ensures URLs detected without protocol are properly formatted
 * 
 * @param url The URL to normalize
 * @returns Normalized URL with protocol
 */
export function normalizeUrl(url: string): string {
  // If URL already has protocol, return as-is
  if (/^https?:\/\//i.test(url)) {
    return url;
  }
  
  // Add https:// prefix for URLs without protocol
  return `https://${url}`;
}

// ============================================================================
// Code Block State Machine - Single source of truth for code fence detection
// ============================================================================

/**
 * Classification result for a single line
 * Determines if a line is a code fence opening, closing, or neither
 */
export interface CodeFenceClassification {
  /** Type of fence: 'opening' for ```lang, 'closing' for ```, 'none' for regular lines */
  type: 'opening' | 'closing' | 'none';
  /** Language specified after opening fence (e.g., 'python', 'javascript') */
  language?: string;
  /** Filename/path specified after language (e.g., ```python:file.py) */
  filename?: string;
  /** Special fence type that should be handled differently */
  specialFence?: 'json_embed' | 'document_html' | 'json';
}

/**
 * Result from processing a line through the state machine
 */
export interface CodeBlockEvent {
  /** Event type: what happened when processing this line */
  event: 'block_opened' | 'block_closed' | 'content_line' | 'outside_block';
  /** Language of the code block (available on open/close) */
  language?: string;
  /** Filename of the code block (available on open/close) */
  filename?: string;
  /** Full content of the block (available on close) */
  content?: string;
  /** Line index where block started (available on open/close) */
  startLine?: number;
  /** Line index where block ended (available on close) */
  endLine?: number;
  /** Special fence type if applicable */
  specialFence?: 'json_embed' | 'document_html' | 'json';
}

/**
 * Classify a single line to determine if it's a code fence
 * This is the SINGLE SOURCE OF TRUTH for code fence detection
 * 
 * Rules:
 * - Opening fence: ``` followed by optional language and/or :filename
 * - Closing fence: ``` with nothing meaningful after (whitespace only)
 * - Special fences: ```json_embed, ```document_html, ```json are handled specially
 * 
 * @param line - The line to classify (can be trimmed or untrimmed)
 * @returns Classification result
 */
export function classifyCodeFenceLine(line: string): CodeFenceClassification {
  const trimmed = line.trim();
  
  // Not a fence at all - doesn't start with ```
  if (!trimmed.startsWith('```')) {
    return { type: 'none' };
  }
  
  // Check for special fence types first (order matters!)
  // These are internal formats that need special handling
  if (trimmed.startsWith('```json_embed')) {
    return { type: 'opening', specialFence: 'json_embed' };
  }
  if (trimmed.startsWith('```document_html')) {
    return { type: 'opening', specialFence: 'document_html' };
  }
  // ```json without _embed suffix - used for embed references from server
  if (trimmed === '```json' || trimmed.startsWith('```json\n') || trimmed.startsWith('```json ')) {
    return { type: 'opening', specialFence: 'json', language: 'json' };
  }
  
  // Check if it's a closing fence
  // A closing fence is ``` with nothing meaningful after (only whitespace)
  const afterBackticks = trimmed.replace(/^```+/, '').trim();
  if (afterBackticks.length === 0) {
    return { type: 'closing' };
  }
  
  // It's an opening fence with language/path
  // Match pattern: ```language or ```language:path
  const match = trimmed.match(EMBED_PATTERNS.CODE_FENCE_START);
  if (match) {
    return {
      type: 'opening',
      language: match[1] || undefined,
      filename: match[2] || undefined
    };
  }
  
  // Edge case: ``` followed by text that doesn't match our pattern
  // Treat as opening with no language (plain code block)
  // This handles cases like ```some-weird-format
  if (afterBackticks.length > 0 && !afterBackticks.includes(' ')) {
    return {
      type: 'opening',
      language: afterBackticks.split(':')[0] || undefined,
      filename: afterBackticks.includes(':') ? afterBackticks.split(':').slice(1).join(':') : undefined
    };
  }
  
  // Fallback - treat as none (shouldn't reach here normally)
  return { type: 'none' };
}

/**
 * State machine for tracking code block boundaries across multiple lines
 * 
 * Usage:
 * ```typescript
 * const sm = new CodeBlockStateMachine();
 * for (let i = 0; i < lines.length; i++) {
 *   const event = sm.processLine(lines[i], i);
 *   if (event.event === 'block_closed') {
 *     // Handle completed code block
 *     console.log('Found code block:', event.language, event.content);
 *   }
 * }
 * // Check for unclosed blocks at end
 * if (sm.isInsideCodeBlock()) {
 *   const partial = sm.getPartialBlockInfo();
 *   // Handle unclosed block for streaming/highlighting
 * }
 * ```
 */
export class CodeBlockStateMachine {
  // Current state tracking
  private inCodeFence = false;
  private inJsonEmbed = false;
  private inDocFence = false;
  private inJsonFence = false;
  
  // Current block info
  private currentLanguage?: string;
  private currentFilename?: string;
  private currentSpecialFence?: 'json_embed' | 'document_html' | 'json';
  private contentLines: string[] = [];
  private blockStartLine = -1;
  
  /**
   * Process a single line and return what happened
   * Call this for each line in sequence
   * 
   * @param line - The line content (with or without leading/trailing whitespace)
   * @param lineIndex - Zero-based line number in the document
   * @returns Event describing what happened
   */
  processLine(line: string, lineIndex: number): CodeBlockEvent {
    const classification = classifyCodeFenceLine(line);
    
    // ========================================
    // Handle json_embed fences (highest priority)
    // ========================================
    if (classification.specialFence === 'json_embed') {
      if (!this.inJsonEmbed && !this.inCodeFence && !this.inDocFence && !this.inJsonFence) {
        // Opening a json_embed block
        this.inJsonEmbed = true;
        this.currentSpecialFence = 'json_embed';
        this.contentLines = [];
        this.blockStartLine = lineIndex;
        return { 
          event: 'block_opened', 
          specialFence: 'json_embed', 
          startLine: lineIndex 
        };
      }
    }
    
    // Closing json_embed
    if (this.inJsonEmbed && classification.type === 'closing') {
      this.inJsonEmbed = false;
      const content = this.contentLines.join('\n');
      const result: CodeBlockEvent = { 
        event: 'block_closed', 
        specialFence: 'json_embed',
        content,
        startLine: this.blockStartLine,
        endLine: lineIndex
      };
      this.resetBlockState();
      return result;
    }
    
    // Content inside json_embed
    if (this.inJsonEmbed) {
      this.contentLines.push(line);
      return { event: 'content_line', specialFence: 'json_embed' };
    }
    
    // ========================================
    // Handle document_html fences
    // ========================================
    if (classification.specialFence === 'document_html') {
      if (!this.inDocFence && !this.inCodeFence && !this.inJsonEmbed && !this.inJsonFence) {
        this.inDocFence = true;
        this.currentSpecialFence = 'document_html';
        this.contentLines = [];
        this.blockStartLine = lineIndex;
        return { 
          event: 'block_opened', 
          specialFence: 'document_html', 
          startLine: lineIndex 
        };
      }
    }
    
    // Closing document_html
    if (this.inDocFence && classification.type === 'closing') {
      this.inDocFence = false;
      const content = this.contentLines.join('\n');
      const result: CodeBlockEvent = { 
        event: 'block_closed', 
        specialFence: 'document_html',
        content,
        startLine: this.blockStartLine,
        endLine: lineIndex
      };
      this.resetBlockState();
      return result;
    }
    
    // Content inside document_html
    if (this.inDocFence) {
      this.contentLines.push(line);
      return { event: 'content_line', specialFence: 'document_html' };
    }
    
    // ========================================
    // Handle json fences (embed references)
    // ========================================
    if (classification.specialFence === 'json') {
      if (!this.inJsonFence && !this.inCodeFence && !this.inJsonEmbed && !this.inDocFence) {
        this.inJsonFence = true;
        this.currentSpecialFence = 'json';
        this.currentLanguage = 'json';
        this.contentLines = [];
        this.blockStartLine = lineIndex;
        return { 
          event: 'block_opened', 
          specialFence: 'json',
          language: 'json',
          startLine: lineIndex 
        };
      }
    }
    
    // Closing json fence
    if (this.inJsonFence && classification.type === 'closing') {
      this.inJsonFence = false;
      const content = this.contentLines.join('\n');
      const result: CodeBlockEvent = { 
        event: 'block_closed', 
        specialFence: 'json',
        language: 'json',
        content,
        startLine: this.blockStartLine,
        endLine: lineIndex
      };
      this.resetBlockState();
      return result;
    }
    
    // Content inside json fence
    if (this.inJsonFence) {
      this.contentLines.push(line);
      return { event: 'content_line', specialFence: 'json' };
    }
    
    // ========================================
    // Handle regular code fences
    // ========================================
    if (classification.type === 'opening' && !this.inCodeFence) {
      // Opening a regular code block
      this.inCodeFence = true;
      this.currentLanguage = classification.language;
      this.currentFilename = classification.filename;
      this.currentSpecialFence = undefined;
      this.contentLines = [];
      this.blockStartLine = lineIndex;
      return { 
        event: 'block_opened', 
        language: classification.language, 
        filename: classification.filename,
        startLine: lineIndex 
      };
    }
    
    if (classification.type === 'closing' && this.inCodeFence) {
      // Closing a regular code block
      this.inCodeFence = false;
      const content = this.contentLines.join('\n');
      const result: CodeBlockEvent = {
        event: 'block_closed',
        language: this.currentLanguage,
        filename: this.currentFilename,
        content,
        startLine: this.blockStartLine,
        endLine: lineIndex
      };
      this.resetBlockState();
      return result;
    }
    
    // Content inside regular code block
    if (this.inCodeFence) {
      this.contentLines.push(line);
      return { event: 'content_line' };
    }
    
    // Outside any code block
    return { event: 'outside_block' };
  }
  
  /**
   * Check if currently inside any type of code block
   */
  isInsideCodeBlock(): boolean {
    return this.inCodeFence || this.inJsonEmbed || this.inDocFence || this.inJsonFence;
  }
  
  /**
   * Check if inside a specific type of special fence
   */
  isInsideSpecialFence(): boolean {
    return this.inJsonEmbed || this.inDocFence || this.inJsonFence;
  }
  
  /**
   * Get info about the current partial (unclosed) block
   * Useful for streaming/highlighting unclosed blocks
   */
  getPartialBlockInfo(): {
    language?: string;
    filename?: string;
    specialFence?: 'json_embed' | 'document_html' | 'json';
    content: string;
    startLine: number;
  } | null {
    if (!this.isInsideCodeBlock()) {
      return null;
    }
    
    return {
      language: this.currentLanguage,
      filename: this.currentFilename,
      specialFence: this.currentSpecialFence,
      content: this.contentLines.join('\n'),
      startLine: this.blockStartLine
    };
  }
  
  /**
   * Reset the state machine to initial state
   */
  reset(): void {
    this.inCodeFence = false;
    this.inJsonEmbed = false;
    this.inDocFence = false;
    this.inJsonFence = false;
    this.resetBlockState();
  }
  
  /**
   * Reset only the current block state (not the fence tracking)
   */
  private resetBlockState(): void {
    this.currentLanguage = undefined;
    this.currentFilename = undefined;
    this.currentSpecialFence = undefined;
    this.contentLines = [];
    this.blockStartLine = -1;
  }
}
