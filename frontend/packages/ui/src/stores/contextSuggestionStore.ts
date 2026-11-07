/** Current post-processor context suggestion per chat plus locally remembered dismissals (no server). */
import { writable, type Readable } from 'svelte/store';
import { contextSuggestionKey, type ContextSuggestion } from '../services/contextSuggestionWire';

const DISMISS_STORAGE_KEY = 'openmates.contextSuggestionDismissals.v1';
const MAX_REMEMBERED = 200;

const suggestions = writable<Record<string, ContextSuggestion | null>>({});
export const contextSuggestions: Readable<Record<string, ContextSuggestion | null>> = { subscribe: suggestions.subscribe };

/** At most one suggestion per chat: a new turn replaces the previous one (null clears it). */
export function setContextSuggestion(chatId: string, suggestion: ContextSuggestion | null): void {
  suggestions.update(current => ({ ...current, [chatId]: suggestion }));
}

export function clearContextSuggestions(): void { suggestions.set({}); }

function readDismissed(): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(DISMISS_STORAGE_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

const dismissedKey = (chatId: string, suggestion: ContextSuggestion) => `${chatId}|${contextSuggestionKey(suggestion)}`;

export function isContextSuggestionDismissed(chatId: string, suggestion: ContextSuggestion): boolean {
  return readDismissed().includes(dismissedKey(chatId, suggestion));
}

export function dismissContextSuggestion(chatId: string, suggestion: ContextSuggestion): void {
  const next = [...readDismissed().filter(key => key !== dismissedKey(chatId, suggestion)), dismissedKey(chatId, suggestion)];
  try {
    localStorage.setItem(DISMISS_STORAGE_KEY, JSON.stringify(next.slice(-MAX_REMEMBERED)));
  } catch {
    // Storage unavailable (private mode/quota): the dismissal then only lasts for this view.
  }
  suggestions.update(current => ({ ...current, [chatId]: null }));
}
