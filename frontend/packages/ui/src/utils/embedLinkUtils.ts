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
export function containsEmbedLinks(text: string): boolean {
  if (!text) return false;
  // Reset regex lastIndex since we use the global flag
  EMBED_LINK_MARKDOWN_RE.lastIndex = 0;
  return EMBED_LINK_MARKDOWN_RE.test(text);
}

/**
 * Check if HTML content contains any `<a href="embed:...">` links.
 */
export function containsEmbedLinksHtml(html: string): boolean {
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
