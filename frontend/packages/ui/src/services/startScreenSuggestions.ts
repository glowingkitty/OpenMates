// frontend/packages/ui/src/services/startScreenSuggestions.ts
//
// New-chat suggestions shown below the Chats start-screen row (TASK-1321).
// Signed-in users see their own synced suggestions (decrypted locally with the
// master key, newest first); guests and users without stored suggestions see the
// translated defaults, ranked by the guest's selected interests when present.
// The composer's search rail (NewChatSuggestions.svelte) keeps its own loader.
//
// Spec: specifications/features/daily-inspiration (daily-inspiration.start-row-suggestions)

import { chatDB } from './db';
import { decryptWithMasterKey } from './cryptoService';
import { DEFAULT_NEW_CHAT_SUGGESTION_KEYS } from '../demo_chats/defaultNewChatSuggestions';
import { getInterestSurfaceIds, rankSuggestionKeysByInterests } from '../demo_chats/guestSmartSelection';
import type { InterestTagId } from '../demo_chats/interestTags';
import type { NewChatSuggestion } from '../types/chat';

export type StartScreenSuggestion = {
  /** Plain natural-language prompt shown to the user. */
  text: string;
  /** Encrypted record for the user's own suggestions ('' for defaults). */
  encrypted: string;
  id: string;
};

/** Suggestions with fewer words are fragments, not prompts (same rule as the composer rail). */
const MIN_WORDS = 4;
const MIN_CJK_CHARS = 8;
const CJK_REGEX = /[㐀-鿿豈-﫿぀-ヿ가-힯]/g;

function toPlainText(html: string): string {
  const withoutTags = html.replace(/<[^>]+>/g, '');
  return withoutTags.replace(/^\s*\[[^\]]+\]\s*/, '').trim();
}

function isFullPrompt(text: string): boolean {
  const cjk = text.match(CJK_REGEX);
  if (cjk && cjk.length >= MIN_CJK_CHARS) return true;
  return text.split(/\s+/).filter(Boolean).length >= MIN_WORDS;
}

function unique(suggestions: StartScreenSuggestion[]): StartScreenSuggestion[] {
  const seen = new Set<string>();
  return suggestions.filter((suggestion) => {
    if (!isFullPrompt(suggestion.text) || seen.has(suggestion.text)) return false;
    seen.add(suggestion.text);
    return true;
  });
}

/** Translated default suggestions, ranked by the selected guest interests. */
export function buildDefaultStartScreenSuggestions(
  translate: (key: string) => string,
  selectedInterestTagIds: readonly InterestTagId[],
): StartScreenSuggestion[] {
  const tags = [...selectedInterestTagIds];
  const keys = tags.length > 0
    ? rankSuggestionKeysByInterests(DEFAULT_NEW_CHAT_SUGGESTION_KEYS, tags)
      .filter((key) => getInterestSurfaceIds(tags, 'suggestions').has(key))
    : DEFAULT_NEW_CHAT_SUGGESTION_KEYS;
  return unique(keys.map((key) => ({ text: toPlainText(translate(key)), encrypted: '', id: key })));
}

/**
 * The signed-in user's synced new-chat suggestions in storage order, decrypted
 * locally. Records that do not decrypt with the current master key are skipped
 * (they belong to an older key). Shared by the composer rail and the start screen.
 */
export async function loadStoredNewChatSuggestions(): Promise<Array<StartScreenSuggestion & { createdAt: number }>> {
  await chatDB.init();
  const records: NewChatSuggestion[] = await chatDB.getAllNewChatSuggestions();
  const decrypted = await Promise.all(
    records.map(async (record) => {
      const plain = await decryptWithMasterKey(record.encrypted_suggestion);
      return plain
        ? { text: toPlainText(plain), encrypted: record.encrypted_suggestion, id: record.id, createdAt: record.created_at ?? 0 }
        : null;
    }),
  );
  return decrypted.filter((item): item is StartScreenSuggestion & { createdAt: number } => item !== null);
}

/** Start-screen order: the user's own suggestions, newest first, full prompts only, no duplicates. */
export async function loadStoredStartScreenSuggestions(): Promise<StartScreenSuggestion[]> {
  const stored = await loadStoredNewChatSuggestions();
  return unique(
    [...stored].sort((a, b) => b.createdAt - a.createdAt).map(({ text, encrypted, id }) => ({ text, encrypted, id })),
  );
}
