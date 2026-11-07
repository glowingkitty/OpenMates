/**
 * Validation of a decrypted composer ghost suggestion payload (pure, import-free).
 * Mirrored by packages/openmates-rust/src/web_composer/suggestions.rs on the shared
 * Rust core Worker `composer` unit; suggestionVectors.test.ts keeps the committed
 * TS-generated vectors in sync with this file.
 */
export interface ComposerGhostSuggestion {
  text: string;
  sourceMessageId: string;
  sourceUserMessageId: string;
  sourceTaskId: string;
}

export function decodeComposerGhostSuggestion(value: string): ComposerGhostSuggestion | null {
  try {
    const parsed = JSON.parse(value) as Partial<ComposerGhostSuggestion>;
    if (typeof parsed.text !== 'string' || !parsed.text.trim() || parsed.text.length > 400 ||
        typeof parsed.sourceMessageId !== 'string' || !parsed.sourceMessageId ||
        typeof parsed.sourceUserMessageId !== 'string' || !parsed.sourceUserMessageId ||
        typeof parsed.sourceTaskId !== 'string' || !parsed.sourceTaskId) return null;
    return parsed as ComposerGhostSuggestion;
  } catch {
    return null;
  }
}
