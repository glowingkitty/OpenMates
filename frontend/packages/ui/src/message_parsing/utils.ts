// Utility functions and regexes for the unified message parsing architecture

// Regex patterns for different embed types
export const EMBED_PATTERNS = {
  // Code fence pattern: ```<lang>[:relative/path] - can appear anywhere in line
  CODE_FENCE: /```(\w+)(?::(.+?))?/,
  
  // Code fence at start of line (for line-by-line parsing)
  CODE_FENCE_START: /^```(\w+)(?::(.+?))?\s*$/,
  
  // Document HTML fence pattern
  DOCUMENT_HTML_FENCE: /^```document_html\s*$/,
  
  // Table fence pattern (GitHub-style markdown tables)
  TABLE_FENCE: /^\|.*\|$/,
  
  // Title comment pattern: <!-- title: "..." -->
  TITLE_COMMENT: /^<!--\s*title:\s*["'](.+?)["']\s*-->$/,
  
  // URL pattern (http/https links)
  URL: /https?:\/\/[^\s]+/g,
  
  // YouTube URL patterns
  YOUTUBE_URL: /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/g
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
