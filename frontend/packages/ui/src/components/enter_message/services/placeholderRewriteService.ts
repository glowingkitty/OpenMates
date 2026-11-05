// frontend/packages/ui/src/components/enter_message/services/placeholderRewriteService.ts
/**
 * @file placeholderRewriteService.ts
 * @description Rewrites outbound markdown using existing encrypted PII mappings.
 *
 * This client-only layer lets users refer to previously redacted originals in a
 * follow-up prompt while preserving the server/LLM boundary: only placeholder
 * tokens leave the owning browser, and originals stay in encrypted mappings.
 */

import type { PIIMapping } from "../../../types/chat";

export interface PlaceholderRewriteOptions {
  mappings: PIIMapping[];
  excludedOriginals?: Set<string>;
  excludedPlaceholders?: Set<string>;
}

export interface PlaceholderRewriteResult {
  markdown: string;
  appliedMappings: PIIMapping[];
}

interface TextRange {
  start: number;
  end: number;
}

interface RewriteSpan extends TextRange {
  mapping: PIIMapping;
}

export function rewriteKnownPIIPlaceholders(
  markdown: string,
  options: PlaceholderRewriteOptions,
): PlaceholderRewriteResult {
  if (!markdown || options.mappings.length === 0) {
    return { markdown, appliedMappings: [] };
  }

  const excludedOriginals = options.excludedOriginals ?? new Set<string>();
  const excludedPlaceholders = options.excludedPlaceholders ?? new Set<string>();
  const mappings = getRewriteMappings(
    options.mappings,
    excludedOriginals,
    excludedPlaceholders,
  );

  let reserved = mergeSortedRanges([], getProtectedRanges(markdown, options.mappings)
    .sort((a, b) => a.start - b.start));
  const spans: RewriteSpan[] = [];
  const appliedMappings: PIIMapping[] = [];
  const appliedKeys = new Set<string>();

  for (const mapping of mappings) {
    let searchFrom = 0;
    let reservedIndex = 0;
    const newRanges: TextRange[] = [];
    let applied = false;
    for (;;) {
      const start = markdown.indexOf(mapping.original, searchFrom);
      if (start === -1) break;
      const end = start + mapping.original.length;
      // Both candidates and prior reserved intervals advance monotonically.
      // Current-mapping matches cannot overlap because acceptance advances to
      // end; merge them only after this mapping instead of rescanning all
      // earlier matches for every repeated original in a large paste.
      while (reservedIndex < reserved.length && reserved[reservedIndex].end <= start) reservedIndex++;
      if (reservedIndex < reserved.length && reserved[reservedIndex].start < end) {
        // A rejected overlap must not hide a later eligible occurrence that
        // overlaps this rejected candidate (for example "aa" in "aaa").
        searchFrom = start + 1;
        continue;
      }
      spans.push({ start, end, mapping });
      newRanges.push({ start, end });
      applied = true;
      searchFrom = end;
    }
    if (applied) {
      reserved = mergeSortedRanges(reserved, newRanges);
      const appliedKey = `${mapping.placeholder}\u0000${mapping.original}`;
      if (!appliedKeys.has(appliedKey)) {
        appliedMappings.push(mapping);
        appliedKeys.add(appliedKey);
      }
    }
  }

  // Span selection uses only the original input, with longest originals taking
  // precedence globally. Assemble once so no emitted placeholder (or custom
  // replacement text) can become another mapping's input.
  const pieces: string[] = [];
  let cursor = 0;
  for (const span of spans.sort((a, b) => a.start - b.start)) {
    pieces.push(markdown.slice(cursor, span.start), span.mapping.placeholder);
    cursor = span.end;
  }
  pieces.push(markdown.slice(cursor));
  return {
    markdown: pieces.join(""),
    appliedMappings,
  };
}

/** Merge already sorted interval batches in linear time, without mutating them. */
function mergeSortedRanges(previous: TextRange[], added: TextRange[]): TextRange[] {
  const result: TextRange[] = [];
  let previousIndex = 0;
  let addedIndex = 0;
  while (previousIndex < previous.length || addedIndex < added.length) {
    const range = addedIndex >= added.length || (previousIndex < previous.length && previous[previousIndex].start <= added[addedIndex].start)
      ? previous[previousIndex++] : added[addedIndex++];
    const last = result[result.length - 1];
    if (last && range.start <= last.end) last.end = Math.max(last.end, range.end);
    else result.push({ start: range.start, end: range.end });
  }
  return result;
}

function getRewriteMappings(
  mappings: PIIMapping[],
  excludedOriginals: Set<string>,
  excludedPlaceholders: Set<string>,
): PIIMapping[] {
  const seenOriginals = new Set<string>();
  return mappings
    .filter((mapping) => {
      if (!mapping.original || !mapping.placeholder) return false;
      if (mapping.original === mapping.placeholder) return false;
      if (excludedOriginals.has(mapping.original)) return false;
      if (excludedPlaceholders.has(mapping.placeholder)) return false;
      if (seenOriginals.has(mapping.original)) return false;
      seenOriginals.add(mapping.original);
      return true;
    })
    .sort((a, b) => b.original.length - a.original.length);
}

function getProtectedRanges(markdown: string, mappings: PIIMapping[]): TextRange[] {
  const ranges: TextRange[] = [];
  for (const match of markdown.matchAll(/```json\n([\s\S]*?)\n```/g)) {
    try {
      const parsed = JSON.parse(match[1].trim()) as Record<string, unknown>;
      if (!("embed_id" in parsed) && !("embed_ids" in parsed)) continue;
      ranges.push({ start: match.index!, end: match.index! + match[0].length });
    } catch { /* Other code blocks retain ordinary literal rewrite behavior. */ }
  }
  // Canonical generated/category tokens stay opaque even without a matching
  // decrypted mapping. Nonces and labels can contain short known originals.
  for (const match of markdown.matchAll(/\[[A-Z][A-Z0-9_]*_[0-9]+(?:_[A-Za-z0-9_-]+)?\]/g)) {
    ranges.push({ start: match.index!, end: match.index! + match[0].length });
  }
  // Known custom bracket forms can use arbitrary labels. Plain-text aliases
  // stay eligible original input: Alice -> Bob must not shield a typed Bob
  // from its own mapping. All inserted aliases are safe through span assembly.
  const placeholders = new Set(mappings.filter(mapping => mapping.original && mapping.placeholder && mapping.placeholder.startsWith("[") && mapping.placeholder.endsWith("]") && mapping.original !== mapping.placeholder)
    .map(mapping => mapping.placeholder));
  for (const placeholder of placeholders) {
    let start = markdown.indexOf(placeholder);
    while (start !== -1) {
      ranges.push({ start, end: start + placeholder.length });
      start = markdown.indexOf(placeholder, start + 1);
    }
  }
  return ranges;
}
