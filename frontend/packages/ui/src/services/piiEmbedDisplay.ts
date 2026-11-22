/**
 * Display text for generated embeds (documents) that may carry privacy placeholders.
 * Presentation only, in the client: originals come from the client-held mapping and
 * are never sent anywhere. Models sometimes keep only the tail of a placeholder's
 * nonce (`[PHONE_1_234]`); such a form is restored only when its type and index
 * match exactly one mapping of the chat.
 */
import type { PIIMapping } from '../types/chat';
import { replacePIIOriginalsWithPlaceholders, restorePIIInText } from '../components/enter_message/services/piiDetectionService';
import { aliasEnhancedPlaceholders } from './piiDisplayAliases';

const canonicalParts = /^\[([A-Z][A-Z0-9_]*?)_([1-9][0-9]*)_[0-9a-f]{16}(?:_[1-9][0-9]*_[0-9a-f]{32})*\]$/;
const shortenedToken = /\[([A-Z][A-Z0-9_]*?)_([1-9][0-9]*)_([A-Za-z0-9]{1,15})\]/g;

/** Rewrites nonce-shortened placeholders to the canonical token of the one mapping they identify. */
export function normalizeShortenedPlaceholders(text: string, mappings: readonly PIIMapping[]): string {
  if (!mappings.length || !text.includes('[')) return text;
  return text.replace(shortenedToken, (token, type: string, index: string) => {
    const matches = mappings.filter((mapping) => {
      const parts = canonicalParts.exec(mapping.placeholder);
      return parts !== null && parts[1] === type && parts[2] === index;
    });
    if (matches.length !== 1) return token;
    return matches[0].placeholder;
  });
}

/**
 * Embed text as shown: originals when revealed and mapped, otherwise the short
 * `[TYPE_N]` label (never the long nonce form).
 */
export function displayPIIEmbedText(text: string, mappings: readonly PIIMapping[], revealed: boolean): string {
  if (!text) return text;
  const normalized = normalizeShortenedPlaceholders(text, mappings);
  if (revealed && mappings.length) return aliasEnhancedPlaceholders(restorePIIInText(normalized, [...mappings]));
  return aliasEnhancedPlaceholders(replacePIIOriginalsWithPlaceholders(normalized, [...mappings]));
}
