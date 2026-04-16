// frontend/packages/ui/src/utils/messageHighlights.ts
//
// Helpers that bridge the DOM (what the user selects on screen) with the
// decrypted raw markdown source of a chat message (where we store highlight
// anchors). Keeping offsets in the raw source makes them stable across
// re-renders and survives embed tokens like `[embed:xyz]`, which render as
// variable-height preview cards but are fixed-width in the source.
//
// These helpers are intentionally framework-light: they take a message's raw
// markdown + the DOM range the user selected, and return {start, end} offsets
// into that markdown. The heavy lifting (ProseMirror decoration rendering,
// store plumbing) lives in the Svelte components.
//
// NOTE: this first pass uses text-content walking over the rendered container.
// It handles plain text + inline markdown well. Integration with TipTap's
// `editor.state.doc` for embed-aware offset mapping is layered on in Phase 4
// of the plan (see plans/when-a-user-is-fuzzy-turing.md → Build order).

import type { HighlightAnchor, MessageHighlight } from "../types/chat";

const CONTEXT_LEN = 20;

/**
 * Build a text-quote anchor from the current DOM selection. Returns the
 * selected text verbatim (trimmed of surrounding whitespace) plus up to
 * ~20 characters of rendered-text context before and after, used to
 * disambiguate repeated occurrences at render time.
 *
 * The snapshot is taken SYNCHRONOUSLY from the live selection — so callers
 * that run this in a `touchstart` handler capture the selection as it
 * exists at that exact instant, beating iOS's tendency to clear or shift
 * the selection a tick later.
 */
export function captureHighlightAnchor(
  contentRoot: HTMLElement,
  range: Range,
): HighlightAnchor | null {
  if (range.collapsed) return null;
  if (!contentRoot.contains(range.commonAncestorContainer)) return null;

  const exact = range.toString().trim();
  if (!exact) return null;

  const pre = document.createRange();
  pre.selectNodeContents(contentRoot);
  pre.setEnd(range.startContainer, range.startOffset);
  const before = pre.toString();

  const post = document.createRange();
  post.selectNodeContents(contentRoot);
  post.setStart(range.endContainer, range.endOffset);
  const after = post.toString();

  return {
    exact,
    prefix: before.slice(-CONTEXT_LEN),
    suffix: after.slice(0, CONTEXT_LEN),
  };
}

/**
 * Locate a text-quote anchor inside `contentRoot`'s rendered text and return
 * a DOM Range that spans exactly the matched `exact` string. Returns null
 * when the anchor cannot be resolved — callers should skip rendering the
 * highlight for that one row (the store entry stays, so a later re-render
 * with updated DOM may resolve it).
 *
 * Strategy: walk text nodes to build the concatenated rendered text, enumerate
 * all occurrences of `anchor.exact`, score each by how well its surrounding
 * characters match `anchor.prefix`/`anchor.suffix`, pick the best match, and
 * convert that offset back to (text-node, offset-within-node) coordinates.
 *
 * This is the W3C Web Annotation text-quote-selector algorithm, minus the
 * fuzzy approximation (we require an exact substring match — fast, and good
 * enough for chat messages which don't get re-edited).
 */
export function findAnchorInRendered(
  contentRoot: HTMLElement,
  anchor: HighlightAnchor,
): Range | null {
  if (!anchor.exact) return null;

  const textNodes: Text[] = [];
  const nodeStarts: number[] = [];
  const walker = document.createTreeWalker(contentRoot, NodeFilter.SHOW_TEXT);
  let n: Node | null = walker.nextNode();
  let rendered = "";
  while (n) {
    const t = n as Text;
    nodeStarts.push(rendered.length);
    rendered += t.nodeValue ?? "";
    textNodes.push(t);
    n = walker.nextNode();
  }
  if (!rendered) return null;

  // Enumerate all occurrences of the exact text.
  const occurrences: number[] = [];
  let from = 0;
  while (from <= rendered.length) {
    const idx = rendered.indexOf(anchor.exact, from);
    if (idx === -1) break;
    occurrences.push(idx);
    from = idx + 1;
  }
  if (occurrences.length === 0) return null;

  // Pick the occurrence whose surrounding context best matches the anchor.
  let best = occurrences[0];
  if (occurrences.length > 1) {
    let bestScore = -1;
    for (const idx of occurrences) {
      const beforeAt = rendered.slice(Math.max(0, idx - anchor.prefix.length), idx);
      const afterAt = rendered.slice(
        idx + anchor.exact.length,
        idx + anchor.exact.length + anchor.suffix.length,
      );
      const score =
        _commonSuffixLen(beforeAt, anchor.prefix) +
        _commonPrefixLen(afterAt, anchor.suffix);
      if (score > bestScore) {
        bestScore = score;
        best = idx;
      }
    }
  }

  const startAt = best;
  const endAt = best + anchor.exact.length;

  function locate(offset: number): { node: Text; off: number } | null {
    for (let i = 0; i < textNodes.length; i++) {
      const s = nodeStarts[i];
      const e = s + (textNodes[i].nodeValue?.length ?? 0);
      if (offset >= s && offset <= e) {
        return { node: textNodes[i], off: offset - s };
      }
    }
    return null;
  }

  const startLoc = locate(startAt);
  const endLoc = locate(endAt);
  if (!startLoc || !endLoc) return null;

  const range = document.createRange();
  try {
    range.setStart(startLoc.node, startLoc.off);
    range.setEnd(endLoc.node, endLoc.off);
  } catch {
    return null;
  }
  return range;
}

function _commonPrefixLen(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  let i = 0;
  while (i < n && a[i] === b[i]) i++;
  return i;
}

function _commonSuffixLen(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  let i = 0;
  while (i < n && a[a.length - 1 - i] === b[b.length - 1 - i]) i++;
  return i;
}

/**
 * Collapse whitespace the way the browser's text rendering does so that
 * offsets computed against rendered text line up with offsets a human picks
 * in the raw source. Matches how markdown collapses consecutive spaces/newlines.
 *
 * Exported for unit tests.
 */
export function normalizeRenderedText(s: string): string {
  return s.replace(/\s+/g, " ");
}

/**
 * Map a DOM Range inside a message content root to offsets in the
 * concatenated rendered text of that root (i.e. the text the user sees —
 * what `getRenderedTextSource()` returns). Returns null when the range is
 * collapsed or leaves `contentRoot`.
 *
 * The second parameter is accepted but unused for the actual offset math:
 * offsets come directly from counting characters in preceding text nodes,
 * which always matches the render-time source. The arg is kept for API
 * symmetry so callers can log/diagnose when the computed rendered source
 * differs from what they expected.
 */
export function domSelectionToSourceRange(
  contentRoot: HTMLElement,
  range: Range,
  _renderedSource: string,
): { start: number; end: number } | null {
  // _renderedSource is kept for API symmetry but unused; underscore prefix
  // opts into the allowed-unused convention in the workspace eslint config.
  void _renderedSource;
  if (range.collapsed) return null;
  if (!contentRoot.contains(range.commonAncestorContainer)) return null;

  // Count rendered characters that precede range.startContainer + startOffset,
  // walking text nodes in document order. This gives the absolute offset into
  // contentRoot's rendered text — the same coordinate system the highlight
  // overlay uses when resolving offsets back to a DOM Range.
  const walker = document.createTreeWalker(contentRoot, NodeFilter.SHOW_TEXT);
  let start: number | null = null;
  let end: number | null = null;
  let offset = 0;
  let node: Node | null = walker.nextNode();
  while (node) {
    const t = node as Text;
    const len = (t.nodeValue ?? "").length;
    if (start === null && t === range.startContainer) {
      start = offset + Math.min(range.startOffset, len);
    }
    if (end === null && t === range.endContainer) {
      end = offset + Math.min(range.endOffset, len);
    }
    offset += len;
    if (start !== null && end !== null) break;
    node = walker.nextNode();
  }

  // Fallbacks when startContainer/endContainer are element nodes (rare —
  // e.g. selection boundary lands exactly between text nodes). Playwright's
  // synthetic selection uses text nodes directly, so this is mostly a guard.
  if (start === null || end === null) {
    const pre = document.createRange();
    pre.selectNodeContents(contentRoot);
    pre.setEnd(range.startContainer, range.startOffset);
    if (start === null) start = pre.toString().length;
    const post = document.createRange();
    post.selectNodeContents(contentRoot);
    post.setEnd(range.endContainer, range.endOffset);
    if (end === null) end = post.toString().length;
  }

  if (start === null || end === null || end <= start) return null;
  return { start, end };
}

/**
 * Find `needle` in `source`, preferring the occurrence whose surrounding
 * characters match `prefix`/`suffix` best. Falls back to the first occurrence
 * when context is ambiguous. Returns null if `needle` isn't present at all.
 *
 * Exported for tests.
 */
export function locateInSource(
  source: string,
  needle: string,
  prefix: string,
  suffix: string,
): { start: number; end: number } | null {
  if (!needle) return null;
  const occurrences: number[] = [];
  let from = 0;
  while (from <= source.length) {
    const idx = source.indexOf(needle, from);
    if (idx === -1) break;
    occurrences.push(idx);
    from = idx + 1;
  }
  if (occurrences.length === 0) return null;
  if (occurrences.length === 1) {
    return { start: occurrences[0], end: occurrences[0] + needle.length };
  }

  // Score each occurrence by how much of the prefix/suffix context matches
  // the characters around it in the source. The best match wins.
  let best = occurrences[0];
  let bestScore = -1;
  for (const idx of occurrences) {
    const beforeSrc = normalizeRenderedText(
      source.slice(Math.max(0, idx - prefix.length), idx),
    );
    const afterSrc = normalizeRenderedText(
      source.slice(idx + needle.length, idx + needle.length + suffix.length),
    );
    const score =
      commonSuffixLength(beforeSrc, prefix) +
      commonPrefixLength(afterSrc, suffix);
    if (score > bestScore) {
      bestScore = score;
      best = idx;
    }
  }
  return { start: best, end: best + needle.length };
}

function commonPrefixLength(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  let i = 0;
  while (i < n && a[i] === b[i]) i++;
  return i;
}

function commonSuffixLength(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  let i = 0;
  while (i < n && a[a.length - 1 - i] === b[b.length - 1 - i]) i++;
  return i;
}

/**
 * Sort highlights into stable on-screen order for the navigation overlay.
 * Text highlights sort by `start` offset; embed highlights sort by a stable
 * fallback on their embed_id so the order is deterministic across reloads.
 */
export function sortHighlightsForNavigation(
  highlights: MessageHighlight[],
): MessageHighlight[] {
  return [...highlights].sort((a, b) => {
    if (a.kind === "text" && b.kind === "text") return a.start - b.start;
    if (a.kind === "text") return -1;
    if (b.kind === "text") return 1;
    return a.embed_id.localeCompare(b.embed_id);
  });
}

/**
 * Count total highlights + comments across all messages in the chat.
 * Used to populate the ChatHeader pill prop.
 */
export function countHighlightsAndComments(
  highlightsByMessageId: Record<string, MessageHighlight[]>,
): { highlights: number; comments: number } {
  let highlights = 0;
  let comments = 0;
  for (const list of Object.values(highlightsByMessageId)) {
    for (const h of list) {
      highlights += 1;
      if (h.comment && h.comment.trim().length > 0) comments += 1;
    }
  }
  return { highlights, comments };
}
