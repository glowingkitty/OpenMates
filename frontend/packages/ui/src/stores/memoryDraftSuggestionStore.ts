/** Unsaved Memory draft handed to Settings > Memories by a deep link (e.g. a suggestion). Never persisted. */
import { writable } from 'svelte/store';

export interface MemoryDraftPayload {
  /** Memory id the draft applies to (matches settings/memories/<id>). */
  id: string;
  title: string;
  memory: string;
  when_to_use?: string;
  load_mode?: 'auto_include' | 'ask_first' | 'mention_only';
  valid_from?: string;
  valid_until?: string;
  /** True when the draft creates a memory that does not exist yet. */
  is_new?: boolean;
  /** Saved document at preview time; Save reports a conflict if it changed meanwhile. */
  base_document?: string;
}

export const memoryDraftSuggestion = writable<MemoryDraftPayload | null>(null);
