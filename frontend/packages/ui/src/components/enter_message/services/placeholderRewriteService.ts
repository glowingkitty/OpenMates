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

interface ProtectedBlock {
  token: string;
  value: string;
}

const EMBED_REF_TOKEN_PREFIX = "__OPENMATES_EMBED_REF_REWRITE_PROTECTED_";

export function rewriteKnownPIIPlaceholders(
  markdown: string,
  options: PlaceholderRewriteOptions,
): PlaceholderRewriteResult {
  if (!markdown || options.mappings.length === 0) {
    return { markdown, appliedMappings: [] };
  }

  const excludedOriginals = options.excludedOriginals ?? new Set<string>();
  const excludedPlaceholders = options.excludedPlaceholders ?? new Set<string>();
  const { safeMarkdown, restore } = protectEmbedReferenceBlocks(markdown);
  const mappings = getRewriteMappings(
    options.mappings,
    excludedOriginals,
    excludedPlaceholders,
  );

  let rewritten = safeMarkdown;
  const appliedMappings: PIIMapping[] = [];
  const appliedKeys = new Set<string>();

  for (const mapping of mappings) {
    if (!rewritten.includes(mapping.original)) continue;

    rewritten = rewritten.split(mapping.original).join(mapping.placeholder);
    const appliedKey = `${mapping.placeholder}\u0000${mapping.original}`;
    if (!appliedKeys.has(appliedKey)) {
      appliedMappings.push(mapping);
      appliedKeys.add(appliedKey);
    }
  }

  return {
    markdown: restore(rewritten),
    appliedMappings,
  };
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

function protectEmbedReferenceBlocks(markdown: string): {
  safeMarkdown: string;
  restore: (processed: string) => string;
} {
  const protectedBlocks: ProtectedBlock[] = [];
  const safeMarkdown = markdown.replace(
    /```json\n([\s\S]*?)\n```/g,
    (block, content) => {
      try {
        const parsed = JSON.parse(content.trim()) as Record<string, unknown>;
        if (!("embed_id" in parsed) && !("embed_ids" in parsed)) return block;
      } catch {
        return block;
      }

      const token = `${EMBED_REF_TOKEN_PREFIX}${protectedBlocks.length}__`;
      protectedBlocks.push({ token, value: block });
      return token;
    },
  );

  return {
    safeMarkdown,
    restore: (processed: string) => {
      let result = processed;
      for (const block of protectedBlocks) {
        result = result.split(block.token).join(block.value);
      }
      return result;
    },
  };
}
