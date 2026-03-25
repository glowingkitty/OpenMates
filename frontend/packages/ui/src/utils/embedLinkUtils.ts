/**
 * Embed link parsing and rendering utilities
 *
 * Provides functions to detect, convert, and hydrate inline embed links
 * (`[display text](embed:some-ref)` in markdown, or `<a href="embed:ref">` in HTML)
 * into interactive EmbedInlineLink Svelte components.
 *
 * Used by SheetEmbedFullscreen/Preview and DocsEmbedFullscreen/Preview where
 * content does NOT flow through the TipTap message-parsing pipeline and therefore
 * needs a separate path to render embed links.
 *
 * Architecture context: see docs/architecture/embed-types.md
 * Tests: (none yet)
 */

import { mount, unmount } from "svelte";
import EmbedInlineLink from "../components/embeds/EmbedInlineLink.svelte";
import { embedStore } from "../services/embedStore";

// ──────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────

/**
 * Regex matching `[display text](embed:some-ref)` in raw text (markdown).
 * Captures:
 *   [1] = display text
 *   [2] = embed_ref slug
 */
const EMBED_LINK_MARKDOWN_RE = /\[([^\]]+)\]\(embed:([^)]+)\)/g;

/**
 * Regex matching `<a href="embed:some-ref">display text</a>` in HTML.
 * Used to convert embed anchor tags before DOMPurify strips the unknown protocol.
 * Captures:
 *   [1] = embed_ref slug
 *   [2] = display text (innerHTML — should be plain text)
 */
const EMBED_LINK_HTML_RE =
  /<a\s[^>]*href=["']embed:([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;

/** CSS class for placeholder spans that will be hydrated with EmbedInlineLink */
const EMBED_PLACEHOLDER_CLASS = "embed-inline-placeholder";

/** Data attribute names used on placeholder spans */
const DATA_EMBED_REF = "data-embed-ref";
const DATA_DISPLAY_TEXT = "data-display-text";

// ──────────────────────────────────────────────────────────────
// Detection
// ──────────────────────────────────────────────────────────────

/**
 * Check if a text string contains any embed link references.
 * Works for both markdown `[text](embed:ref)` and raw embed refs.
 */
function containsEmbedLinks(text: string): boolean {
  if (!text) return false;
  // Reset regex lastIndex since we use the global flag
  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  return EMBED_LINK_MARKDOWN_RE.test(text);
}

/**
 * Check if HTML content contains any `<a href="embed:...">` links.
 */
function containsEmbedLinksHtml(html: string): boolean {
  if (!html) return false;
  EMBED_LINK_HTML_RE.lastIndex = 0;
  return EMBED_LINK_HTML_RE.test(html);
}

// ──────────────────────────────────────────────────────────────
// Conversion: Markdown → HTML with placeholder spans
// ──────────────────────────────────────────────────────────────

/**
 * Escape HTML special characters in a string to prevent XSS when
 * inserting user-controlled text into innerHTML.
 */
function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Build a placeholder `<span>` that will later be hydrated into EmbedInlineLink.
 * The display text is shown as fallback content inside the span, so even before
 * hydration (or if JS fails) the user sees readable text.
 */
function buildPlaceholderSpan(embedRef: string, displayText: string): string {
  return `<span class="${EMBED_PLACEHOLDER_CLASS}" ${DATA_EMBED_REF}="${escapeHtml(embedRef)}" ${DATA_DISPLAY_TEXT}="${escapeHtml(displayText)}">${escapeHtml(displayText)}</span>`;
}

/**
 * Replace `[display text](embed:ref)` patterns in a raw text string with
 * placeholder `<span>` elements. Non-embed text is HTML-escaped.
 *
 * Returns an HTML string suitable for {@html} rendering in Svelte.
 * Call `hydrateEmbedLinks()` after mount to make them interactive.
 *
 * If the text contains NO embed links, returns `null` so the caller can
 * fall back to plain text rendering (cheaper, no {@html} needed).
 */
export function replaceEmbedLinksInText(text: string): string | null {
  if (!text) return null;

  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  if (!EMBED_LINK_MARKDOWN_RE.test(text)) return null;

  // Reset for actual replacement
  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  let result = "";
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = EMBED_LINK_MARKDOWN_RE.exec(text)) !== null) {
    // Escape the text between the previous match and this one
    result += escapeHtml(text.slice(lastIndex, match.index));
    const displayText = match[1];
    const embedRef = match[2];
    result += buildPlaceholderSpan(embedRef, displayText);
    lastIndex = match.index + match[0].length;
  }

  // Escape any remaining text after the last match
  result += escapeHtml(text.slice(lastIndex));
  return result;
}

// ──────────────────────────────────────────────────────────────
// Conversion: HTML <a href="embed:..."> → placeholder spans
// ──────────────────────────────────────────────────────────────

/**
 * Replace `<a href="embed:ref">text</a>` in an HTML string with placeholder
 * `<span>` elements. This should be called BEFORE DOMPurify.sanitize()
 * because DOMPurify strips the non-standard `embed:` protocol.
 *
 * Returns the modified HTML string.
 */
export function convertEmbedAnchorsToSpans(html: string): string {
  if (!html) return html;

  EMBED_LINK_HTML_RE.lastIndex = 0;
  return html.replace(
    EMBED_LINK_HTML_RE,
    (_match, embedRef: string, innerHtml: string) => {
      // Strip any inner HTML tags from the display text (keep plain text only)
      const displayText = innerHtml.replace(/<[^>]*>/g, "").trim();
      return buildPlaceholderSpan(embedRef, displayText);
    },
  );
}

// ──────────────────────────────────────────────────────────────
// Hydration: Mount EmbedInlineLink into placeholder spans
// ──────────────────────────────────────────────────────────────

/** Tracks mounted Svelte instances for cleanup */
type MountedInstance = ReturnType<typeof mount>;

/**
 * Find all `.embed-inline-placeholder` spans inside a container element
 * and mount an `EmbedInlineLink` Svelte component into each one.
 *
 * Returns a cleanup function that unmounts all Svelte instances.
 * Call this inside a Svelte `$effect()` to ensure proper cleanup.
 *
 * @param container - DOM element to search for placeholder spans
 * @returns Cleanup function that unmounts all hydrated components
 */
export function hydrateEmbedLinks(
  container: HTMLElement | undefined,
): () => void {
  if (!container) return () => {};

  const placeholders = container.querySelectorAll<HTMLSpanElement>(
    `.${EMBED_PLACEHOLDER_CLASS}`,
  );
  if (placeholders.length === 0) return () => {};

  const instances: MountedInstance[] = [];

  placeholders.forEach((span) => {
    const embedRef = span.getAttribute(DATA_EMBED_REF);
    const displayText = span.getAttribute(DATA_DISPLAY_TEXT);

    if (!embedRef || !displayText) return;

    // Resolve appId from the embed store index (may be null if not yet indexed)
    const appId = embedStore.resolveAppIdByRef(embedRef) ?? null;

    // Clear the fallback text content before mounting the Svelte component
    span.textContent = "";

    try {
      const instance = mount(EmbedInlineLink, {
        target: span,
        props: {
          embedRef,
          displayText,
          appId,
          embedId: null, // Resolved lazily on click
        },
      });
      instances.push(instance);
    } catch (err) {
      // If mount fails, restore the fallback display text
      console.error("[embedLinkUtils] Failed to mount EmbedInlineLink:", err);
      span.textContent = displayText;
    }
  });

  // Return cleanup function
  return () => {
    instances.forEach((inst) => {
      try {
        unmount(inst);
      } catch {
        // Ignore unmount errors (component may already be destroyed)
      }
    });
  };
}

// ──────────────────────────────────────────────────────────────
// Plain text extraction (for export: CSV, TSV, XLSX, clipboard)
// ──────────────────────────────────────────────────────────────

/**
 * Strip embed link markdown syntax and return just the display text.
 * `[ChatGPT Limits](embed:blog.laozhang.ai-pOx)` → `ChatGPT Limits`
 *
 * Use this for export formats (TSV, XLSX) where interactive links
 * are not possible and the display text is sufficient.
 */
export function stripEmbedLinks(text: string): string {
  if (!text) return text;
  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  return text.replace(EMBED_LINK_MARKDOWN_RE, "$1");
}

// ──────────────────────────────────────────────────────────────
// Markdown embed links inside HTML content
// ──────────────────────────────────────────────────────────────

/**
 * Convert markdown-style `[text](embed:ref)` patterns found inside HTML
 * content into placeholder `<span>` elements that can be hydrated later.
 *
 * This handles the case where the AI generates HTML documents containing
 * embed link markdown syntax inside text nodes (e.g., inside blockquotes
 * like `<blockquote>[quoted text](embed:mistertour.it-AaM)</blockquote>`).
 * The `convertEmbedAnchorsToSpans` function only handles `<a href="embed:">` tags,
 * but the AI may also write raw markdown link syntax inside HTML elements.
 *
 * Should be called BEFORE DOMPurify sanitization, alongside convertEmbedAnchorsToSpans.
 *
 * @param html - HTML string that may contain markdown embed links in text nodes
 * @returns Modified HTML with embed links converted to placeholder spans
 */
export function convertMarkdownEmbedLinksInHtml(html: string): string {
  if (!html) return html;

  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  if (!EMBED_LINK_MARKDOWN_RE.test(html)) return html;

  // Reset for actual replacement
  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  return html.replace(
    EMBED_LINK_MARKDOWN_RE,
    (_match: string, displayText: string, embedRef: string) => {
      return buildPlaceholderSpan(embedRef, displayText);
    },
  );
}

// ──────────────────────────────────────────────────────────────
// URL resolution for export: replace embed: refs with real URLs
// ──────────────────────────────────────────────────────────────

/**
 * Resolve an embed_ref to its source web URL by looking up the embed
 * content via the embed store. Returns the URL or null if not resolvable.
 *
 * This function requires the embed to be already loaded and decrypted
 * in the client-side embed store (IndexedDB).
 *
 * @param embedRef - The embed reference slug (e.g. "mistertour.it-AaM")
 * @returns The source URL or null if not found
 */
export async function resolveEmbedRefToUrl(
  embedRef: string,
): Promise<string | null> {
  try {
    const embedId = embedStore.resolveByRef(embedRef);
    if (!embedId) return null;

    // Dynamic import to avoid circular dependency.
    // Both resolveEmbed and decodeToonContent are in embedResolver.
    const { resolveEmbed, decodeToonContent } = await import(
      "../services/embedResolver"
    );
    const embedData = await resolveEmbed(embedId);
    if (!embedData?.content) return null;

    // Decode the TOON content to extract the url field
    const decoded = await decodeToonContent(embedData.content);

    if (decoded && typeof decoded === "object") {
      const content = decoded as Record<string, unknown>;
      // The 'url' field contains the actual web URL for search results
      if (typeof content.url === "string" && content.url) {
        return content.url;
      }
    }

    return null;
  } catch (error) {
    console.error(
      "[embedLinkUtils] Failed to resolve embed ref to URL:",
      embedRef,
      error,
    );
    return null;
  }
}

/**
 * Replace all `[display text](embed:ref)` patterns in a text string with
 * `display text (url)` format, resolving each embed ref to its actual web URL.
 * If a ref cannot be resolved, just the display text is kept.
 *
 * Used for plain-text export (clipboard copy) where embed IDs are meaningless
 * outside of OpenMates.
 *
 * @param text - Text string containing markdown embed link syntax
 * @returns Promise resolving to text with embed refs replaced by URLs
 */
export async function replaceEmbedRefsWithUrls(
  text: string,
): Promise<string> {
  if (!text) return text;

  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  const matches: Array<{
    fullMatch: string;
    displayText: string;
    embedRef: string;
    index: number;
  }> = [];

  let match: RegExpExecArray | null;
  while ((match = EMBED_LINK_MARKDOWN_RE.exec(text)) !== null) {
    matches.push({
      fullMatch: match[0],
      displayText: match[1],
      embedRef: match[2],
      index: match.index,
    });
  }

  if (matches.length === 0) return text;

  // Resolve all embed refs in parallel
  const urlResults = await Promise.all(
    matches.map((m) => resolveEmbedRefToUrl(m.embedRef)),
  );

  // Replace from end to start so indices remain valid
  let result = text;
  for (let i = matches.length - 1; i >= 0; i--) {
    const m = matches[i];
    const url = urlResults[i];
    const replacement = url ? `${m.displayText} (${url})` : m.displayText;
    result =
      result.slice(0, m.index) +
      replacement +
      result.slice(m.index + m.fullMatch.length);
  }

  return result;
}

/**
 * Replace all embed placeholder spans in an HTML string with proper `<a>` tags
 * pointing to the resolved web URLs. Used for .docx export where the embed IDs
 * are meaningless but actual hyperlinks are useful.
 *
 * Also handles any remaining markdown-style `[text](embed:ref)` patterns.
 *
 * @param html - HTML string with embed placeholder spans or markdown embed links
 * @returns Promise resolving to HTML with embed refs replaced by real <a> tags
 */
export async function replaceEmbedRefsWithUrlsInHtml(
  html: string,
): Promise<string> {
  if (!html) return html;

  // Collect all embed refs from placeholder spans
  const PLACEHOLDER_RE =
    /<span\s+class="embed-inline-placeholder"\s+data-embed-ref="([^"]+)"\s+data-display-text="([^"]+)"[^>]*>[^<]*<\/span>/gi;

  const refs = new Set<string>();

  let m: RegExpExecArray | null;
  while ((m = PLACEHOLDER_RE.exec(html)) !== null) {
    refs.add(m[1]);
  }

  // Also collect markdown-style refs
  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  while ((m = EMBED_LINK_MARKDOWN_RE.exec(html)) !== null) {
    refs.add(m[2]);
  }

  if (refs.size === 0) return html;

  // Resolve all unique refs in parallel
  const refArray = Array.from(refs);
  const urlResults = await Promise.all(
    refArray.map((ref) => resolveEmbedRefToUrl(ref)),
  );
  const refToUrl = new Map<string, string | null>();
  refArray.forEach((ref, i) => refToUrl.set(ref, urlResults[i]));

  // Replace placeholder spans with <a> tags (or plain text if no URL)
  let result = html.replace(
    PLACEHOLDER_RE,
    (_match: string, embedRef: string, displayText: string) => {
      const url = refToUrl.get(embedRef);
      if (url) {
        return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(displayText)}</a>`;
      }
      return escapeHtml(displayText);
    },
  );

  // Replace any remaining markdown-style embed links
  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  result = result.replace(
    EMBED_LINK_MARKDOWN_RE,
    (_match: string, displayText: string, embedRef: string) => {
      const url = refToUrl.get(embedRef);
      if (url) {
        return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(displayText)}</a>`;
      }
      return escapeHtml(displayText);
    },
  );

  return result;
}
