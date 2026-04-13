// frontend/packages/ui/src/stores/wikiTopicsStore.ts
//
// Lightweight store that holds the current chat's Wikipedia topics.
// Set by ActiveChat when currentChat changes; read by ReadOnlyMessage
// to pass into parse_message for wiki inline link injection.
//
// This store bypasses the 4-level prop chain (ActiveChat → ChatHistory →
// ChatMessage → ReadOnlyMessage) which has timing issues with lazy
// IntersectionObserver-based TipTap editor initialization.

import { writable } from 'svelte/store';

export interface WikiTopicEntry {
  topic: string;
  wiki_title: string;
  wikidata_id: string | null;
  thumbnail_url: string | null;
  description: string | null;
}

/** Current chat's Wikipedia topics. Empty array when no topics are available. */
export const wikiTopicsStore = writable<WikiTopicEntry[]>([]);
