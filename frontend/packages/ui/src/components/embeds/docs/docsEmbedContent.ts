// Document embed content parsing utilities
// Handles parsing, sanitization, and preview extraction for document_html embeds
// Tests: (none yet)

import DOMPurify, { type Config } from "dompurify";
import {
  convertEmbedAnchorsToSpans,
  convertMarkdownEmbedLinksInHtml,
  convertMarkdownWikiLinksInHtml,
  convertWikiAnchorsToSpans,
} from "../../../utils/embedLinkUtils";

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
    // Inline embed link placeholder attributes (set by convertEmbedAnchorsToSpans)
    "data-embed-ref",
    "data-display-text",
    // Inline wiki link placeholder attributes
    "data-wiki-title",
    "data-wikidata-id",
    "data-thumbnail-url",
    "data-description",
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

  // Pre-process: convert embed links to placeholder <span> elements BEFORE DOMPurify runs.
  // DOMPurify strips the non-standard "embed:" protocol from <a href="embed:..."> tags.
  // The placeholder spans use data attributes (data-embed-ref, data-display-text) that
  // are in the ALLOWED_ATTR list, so DOMPurify preserves them.
  //
  // Two conversion steps are needed:
  // 1. convertEmbedAnchorsToSpans: handles <a href="embed:ref">text</a> HTML tags
  // 2. convertMarkdownEmbedLinksInHtml: handles [text](embed:ref) markdown syntax
  //    that the AI may write inside blockquotes or other HTML text nodes
  let preprocessed = convertEmbedAnchorsToSpans(html);
  preprocessed = convertWikiAnchorsToSpans(preprocessed);
  preprocessed = convertMarkdownEmbedLinksInHtml(preprocessed);
  preprocessed = convertMarkdownWikiLinksInHtml(preprocessed);

  // Sanitize with DOMPurify (RETURN_TRUSTED_TYPE: false ensures string return)
  const sanitized = DOMPurify.sanitize(preprocessed, SANITIZE_CONFIG) as string;

  // Post-process: ensure all <a> tags have target="_blank" and rel="noopener noreferrer"
  // This prevents tab-napping attacks from links in documents
  return sanitized.replace(
    /<a\s/g,
    '<a target="_blank" rel="noopener noreferrer" ',
  );
}

/** Render the structured source retained with a document embed when no artifact is available. */
export function docxModelToHtml(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const blocks = (value as { blocks?: unknown }).blocks;
  if (!Array.isArray(blocks)) return "";

  const escape = (text: unknown): string => String(text ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const renderRuns = (block: Record<string, unknown>): string => {
    if (!Array.isArray(block.runs)) return escape(block.text);
    return block.runs.map((value: unknown) => {
      if (!value || typeof value !== "object" || Array.isArray(value)) return "";
      const run = value as Record<string, unknown>;
      let content = escape(run.text).replace(/\n/g, "<br>");
      if (run.bold === true) content = `<strong>${content}</strong>`;
      if (run.italic === true) content = `<em>${content}</em>`;
      if (run.underline === true) content = `<u>${content}</u>`;
      return content;
    }).join("");
  };
  const cell = (value: unknown, tag: "td" | "th") => `<${tag}>${escape(value)}</${tag}>`;

  return blocks.map((value: unknown) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return "";
    const block = value as Record<string, unknown>;
    switch (block.type) {
      case "heading": {
        const level = Math.max(1, Math.min(4, Number(block.level) || 1));
        return `<h${level}>${escape(block.text)}</h${level}>`;
      }
      case "paragraph": return `<p>${renderRuns(block)}</p>`;
      case "blockquote": return `<blockquote>${escape(block.text)}</blockquote>`;
      case "list": {
        const tag = block.ordered === true ? "ol" : "ul";
        const items = Array.isArray(block.items) ? block.items : [];
        return `<${tag}>${items.map((item) => `<li>${escape(item)}</li>`).join("")}</${tag}>`;
      }
      case "table": {
        const headers = Array.isArray(block.headers) ? block.headers : [];
        const rows = Array.isArray(block.rows) ? block.rows : [];
        return `<table>${headers.length ? `<thead><tr>${headers.map((item) => cell(item, "th")).join("")}</tr></thead>` : ""}<tbody>${rows.map((row) => `<tr>${Array.isArray(row) ? row.map((item) => cell(item, "td")).join("") : ""}</tr>`).join("")}</tbody></table>`;
      }
      case "page_break": return "<hr>";
      default: return "";
    }
  }).join("\n");
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
 * Extract filename from document HTML content
 * Looks for <!-- filename: "Name.docx" --> comment pattern
 * The LLM is instructed to include this as the second line of document_html content
 *
 * @param html - HTML content that may contain a filename comment
 * @returns Extracted filename or undefined if not found
 */
export function extractDocumentFilename(html: string): string | undefined {
  if (!html) return undefined;

  const filenameMatch = html.match(/<!--\s*filename:\s*["'](.+?)["']\s*-->/);
  return filenameMatch ? filenameMatch[1] : undefined;
}

/**
 * Generate a fallback .docx filename from the document title
 * Converts the title to a snake_case filename with .docx extension
 *
 * @param title - Document title to convert
 * @returns Generated filename (e.g., "Rental_Agreement.docx")
 */
export function generateFilenameFromTitle(title: string): string {
  if (!title) return "Document.docx";

  // Replace spaces and special chars with underscores, keep alphanumeric and underscores
  const sanitized = title
    .replace(/[^a-zA-Z0-9\s_-]/g, "")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");

  // Truncate to reasonable length
  const truncated = sanitized.substring(0, 50);

  return truncated ? `${truncated}.docx` : "Document.docx";
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
