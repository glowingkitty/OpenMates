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

import type { MessageHighlight } from "../types/chat";

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
 * Map a DOM Range inside a message content root to offsets in the raw markdown
 * source. Returns null when:
 *   - range is collapsed (no selection)
 *   - range leaves `contentRoot`
 *   - selected text cannot be located in the source (edge case: heavy markdown
 *     reshaping; callers treat this as "can't highlight this selection")
 *
 * Strategy: read the selection's visible text, then find it in the raw source
 * using a prefix/suffix context window to disambiguate when the text appears
 * more than once. This is resilient to markdown syntax (asterisks for bold,
 * brackets for links) because we search the source *as source* and pick the
 * occurrence whose surrounding characters best match the DOM context.
 */
export function domSelectionToSourceRange(
  contentRoot: HTMLElement,
  range: Range,
  rawSource: string,
): { start: number; end: number } | null {
  if (range.collapsed) return null;
  if (!contentRoot.contains(range.commonAncestorContainer)) return null;

  const selectedText = normalizeRenderedText(range.toString()).trim();
  if (!selectedText) return null;

  // Build the full rendered text once so we can compute what appears before /
  // after the selection — used as context to disambiguate duplicate matches.
  const fullRenderedText = normalizeRenderedText(
    contentRoot.textContent ?? "",
  );
  const preRange = document.createRange();
  preRange.selectNodeContents(contentRoot);
  preRange.setEnd(range.startContainer, range.startOffset);
  const beforeRendered = normalizeRenderedText(preRange.toString());

  const CONTEXT_LEN = 16;
  const prefix = beforeRendered.slice(-CONTEXT_LEN);
  const suffixStartInRendered =
    beforeRendered.length + selectedText.length;
  const suffix = fullRenderedText.slice(
    suffixStartInRendered,
    suffixStartInRendered + CONTEXT_LEN,
  );

  return locateInSource(rawSource, selectedText, prefix, suffix);
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
