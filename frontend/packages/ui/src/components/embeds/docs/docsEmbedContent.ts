// Document embed content parsing utilities
// Handles parsing, sanitization, and preview extraction for document_html embeds

import DOMPurify, { type Config } from "dompurify";

/**
 * DOMPurify configuration for document HTML sanitization
 * Allows semantic HTML elements but strips all dangerous content:
 * - No script/style/iframe/object/embed/form tags
 * - No on* event handler attributes
 * - No style attributes (prevents CSS-based attacks)
 * - No javascript: URLs
 */
const SANITIZE_CONFIG: Config = {
  ALLOWED_TAGS: [
    // Headings
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    // Text blocks
    "p",
    "blockquote",
    "pre",
    "code",
    // Lists
    "ul",
    "ol",
    "li",
    // Tables
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "colgroup",
    "col",
    // Inline elements
    "strong",
    "em",
    "b",
    "i",
    "u",
    "s",
    "del",
    "ins",
    "mark",
    "sub",
    "sup",
    "small",
    "abbr",
    "cite",
    "dfn",
    "kbd",
    "samp",
    "var",
    // Links
    "a",
    // Breaks
    "br",
    "hr",
    // Media (images only, no iframes/objects)
    "img",
    // Semantic
    "article",
    "section",
    "header",
    "footer",
    "nav",
    "aside",
    "main",
    "figure",
    "figcaption",
    "details",
    "summary",
    // Definition lists
    "dl",
    "dt",
    "dd",
    // Divs and spans (for structure)
    "div",
    "span",
  ],
  ALLOWED_ATTR: [
    // Links
    "href",
    "target",
    "rel",
    "title",
    // Images
    "src",
    "alt",
    "width",
    "height",
    // Tables
    "colspan",
    "rowspan",
    "scope",
    // Accessibility
    "role",
    "aria-label",
    "aria-describedby",
    "aria-hidden",
    // Generic
    "id",
    "class",
    "lang",
    "dir",
  ],
  // Force all links to open in new tab
  ADD_ATTR: ["target"],
  // Forbid dangerous URL schemes
  ALLOW_UNKNOWN_PROTOCOLS: false,
  // Always return a plain string (not TrustedHTML) for post-processing
  RETURN_TRUSTED_TYPE: false,
};

/**
 * Sanitize document HTML content using DOMPurify
 * Removes all potentially dangerous elements and attributes while preserving
 * semantic structure needed for document rendering
 *
 * @param html - Raw HTML content from the document embed
 * @returns Sanitized HTML string safe for innerHTML rendering
 */
export function sanitizeDocumentHtml(html: string): string {
  if (!html) return "";

  // Sanitize with DOMPurify (RETURN_TRUSTED_TYPE: false ensures string return)
  const sanitized = DOMPurify.sanitize(html, SANITIZE_CONFIG) as string;

  // Post-process: ensure all <a> tags have target="_blank" and rel="noopener noreferrer"
  // This prevents tab-napping attacks from links in documents
  return sanitized.replace(
    /<a\s/g,
    '<a target="_blank" rel="noopener noreferrer" ',
  );
}

/**
 * Extract title from document HTML content
 * Looks for <!-- title: "..." --> comment pattern as specified in the architecture
 *
 * @param html - HTML content that may contain a title comment
 * @returns Extracted title or undefined if not found
 */
export function extractDocumentTitle(html: string): string | undefined {
  if (!html) return undefined;

  const titleMatch = html.match(/<!--\s*title:\s*["'](.+?)["']\s*-->/);
  return titleMatch ? titleMatch[1] : undefined;
}

/**
 * Strip HTML tags from content to get plain text
 * Used for word count calculation and preview text extraction
 *
 * @param html - HTML content to strip
 * @returns Plain text without HTML tags
 */
export function stripHtmlTags(html: string): string {
  if (!html) return "";

  // Remove HTML comments (including title comments)
  let text = html.replace(/<!--[\s\S]*?-->/g, "");

  // Remove HTML tags
  text = text.replace(/<[^>]+>/g, " ");

  // Decode common HTML entities
  text = text.replace(/&amp;/g, "&");
  text = text.replace(/&lt;/g, "<");
  text = text.replace(/&gt;/g, ">");
  text = text.replace(/&quot;/g, '"');
  text = text.replace(/&#039;/g, "'");
  text = text.replace(/&nbsp;/g, " ");

  // Collapse whitespace
  text = text.replace(/\s+/g, " ").trim();

  return text;
}

/**
 * Count words in document HTML content
 * Strips HTML tags first for accurate word count
 *
 * @param html - HTML content to count words in
 * @returns Number of words
 */
export function countDocWords(html: string): number {
  const text = stripHtmlTags(html);
  if (!text) return 0;
  return text.split(/\s+/).filter((w) => w.trim().length > 0).length;
}

/**
 * Extract preview text from document HTML content
 * Returns the first N words of plain text for preview display
 *
 * @param html - HTML content to extract preview from
 * @param maxWords - Maximum number of words in preview (default: 200)
 * @returns Preview text string
 */
export function extractPreviewText(
  html: string,
  maxWords: number = 200,
): string {
  const text = stripHtmlTags(html);
  if (!text) return "";

  const words = text.split(/\s+/).filter((w) => w.trim().length > 0);
  if (words.length <= maxWords) return words.join(" ");

  return words.slice(0, maxWords).join(" ") + "...";
}

/**
 * Parse document embed content from decoded TOON data or raw attributes
 * Extracts all relevant fields for rendering
 *
 * @param content - Raw HTML content or decoded content object
 * @param hints - Optional hints (title from attributes, etc.)
 * @returns Parsed document content with all fields
 */
export interface ParsedDocContent {
  html: string;
  title: string | undefined;
  wordCount: number;
  previewText: string;
}

export function parseDocEmbedContent(
  content: string | Record<string, unknown>,
  hints?: { title?: string },
): ParsedDocContent {
  let html = "";
  let title: string | undefined;

  if (typeof content === "string") {
    html = content;
  } else if (content && typeof content === "object") {
    html = (content.html as string) || (content.code as string) || "";
    title = (content.title as string) || undefined;
  }

  // Extract title from content if not provided
  if (!title) {
    title = extractDocumentTitle(html) || hints?.title;
  }

  const wordCount = countDocWords(html);
  const previewText = extractPreviewText(html);

  return {
    html,
    title,
    wordCount,
    previewText,
  };
}
