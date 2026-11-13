/**
 * Thin adapter for the shared Rust web search and PII display alias ports
 * (U16/U18). Exports in packages/openmates-browser-bindings/src/browser_search_pii.rs.
 *
 * Flag-off contract: with VITE_OPENMATES_RUST_CORE unset nothing here is
 * constructed and searchService.ts / embedSuggestionSearch.ts / piiDisplayAliases.ts
 * stay authoritative. The coordinator wires an instance through the shared worker:
 *
 *   const adapter = createSearchPiiAdapter(binding);   // binding = wasm module exports
 *   adapter.findMatchRanges(text, query)                // == searchService.findMatchRanges
 *   adapter.buildSnippet(content, start, length)        // == searchService.buildSnippet
 *   adapter.searchSavedEmbedMemories(state, query, 6)   // == embedSuggestionSearch
 *   adapter.createPIIDisplayAliases(src, mappings, cfg) // == piiDisplayAliases
 *
 * All offsets are UTF-16 code units. A malformed payload rejects with the code
 * `protocol`. The adapter never falls back to the TypeScript implementations.
 */
import type { PIIMapping } from '../../../types/chat';
import type { SavedEmbedSuggestion, SavedMemoriesLike } from '../../embedSuggestionSearch';

/** Worker module exports (snake_case, JSON strings). */
export interface SearchPiiBinding {
  search_find_match_ranges(text: string, query: string): string;
  search_build_snippet(content: string, matchStart: number, matchLength: number): string;
  search_saved_embed_memories(entriesJson: string, query: string, limit: number): string;
  pii_create_display_aliases(sourceJson: string, mappingsJson: string, configuredJson: string): string;
}

export interface SearchPiiAdapter {
  findMatchRanges(text: string, query: string): Array<{ start: number; length: number }>;
  buildSnippet(content: string, matchStart: number, matchLength: number): { snippet: string; snippetMatchStart: number; snippetMatchLength: number };
  searchSavedEmbedMemories(state: SavedMemoriesLike, query: string, limit?: number): SavedEmbedSuggestion[];
  createPIIDisplayAliases(
    sourceContent: string | Record<string, unknown> | null,
    mappings: readonly PIIMapping[],
    configuredReplacements?: readonly string[],
  ): ReadonlyMap<string, string>;
}

type OrderedSource = string | null | OrderedSource[] | { $entries: Array<[string, OrderedSource]> };

/** Objects become ordered pairs so Object.values order crosses the boundary exactly. */
export function toOrderedSource(value: unknown): OrderedSource {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(toOrderedSource);
  if (value && typeof value === 'object') {
    return { $entries: Object.entries(value).map(([key, node]) => [key, toOrderedSource(node)] as [string, OrderedSource]) };
  }
  return null;
}

export function toOrderedMemories(entriesByApp: SavedMemoriesLike['entriesByApp']) {
  return Array.from(entriesByApp, ([appId, groups]) => [
    appId,
    Object.entries(groups).map(([group, entries]) => [
      group,
      entries.map(entry => ({
        id: entry.id,
        item_value: entry.item_value && typeof entry.item_value === 'object' ? Object.entries(entry.item_value) : [],
        updated_at: entry.updated_at,
      })),
    ]),
  ]);
}

export function createSearchPiiAdapter(binding: SearchPiiBinding): SearchPiiAdapter {
  return {
    findMatchRanges: (text, query) => JSON.parse(binding.search_find_match_ranges(text, query)),
    buildSnippet: (content, start, length) => JSON.parse(binding.search_build_snippet(content, start, length)),
    searchSavedEmbedMemories: (state, query, limit = 6) =>
      JSON.parse(binding.search_saved_embed_memories(JSON.stringify(toOrderedMemories(state.entriesByApp)), query, limit)),
    createPIIDisplayAliases: (sourceContent, mappings, configuredReplacements = []) =>
      new Map(JSON.parse(binding.pii_create_display_aliases(
        JSON.stringify(toOrderedSource(sourceContent)),
        JSON.stringify(mappings),
        JSON.stringify(configuredReplacements),
      )) as Array<[string, string]>),
  };
}

/**
 * Worker-resident search state (wasm classes `SearchCorpus` and `SavedMemoriesIndex`).
 *
 * The per-call exports above copy their whole input across the wasm boundary and
 * cannot beat the in-heap TypeScript string operations (measured 1.6x to 17x
 * slower, see packages/openmates-browser-bindings/tests/bench/searchSnippetBench.cjs).
 * The hot paths therefore keep the data inside the core:
 *
 *   const corpus = new wasm.SearchCorpus();            // one per chat (or per search scope)
 *   corpus.set_texts_json(JSON.stringify([[messageId, content], ...]));  // once per ingest
 *   corpus.set_text(messageId, content); corpus.remove(messageId);       // incremental updates
 *   parseFirstHits(corpus.first_hits(query, 5));        // == searchMessagesInChat's indexOf+buildSnippet loop
 *   parseCorpusMatches(corpus.search(query, 1));        // all ranges + snippets per matching text
 *
 *   const memories = new wasm.SavedMemoriesIndex();
 *   memories.set_entries_json(JSON.stringify(toOrderedMemories(state.entriesByApp)));  // per snapshot
 *   JSON.parse(memories.search(query, 6));              // == searchSavedEmbedMemories (cached index)
 *
 * Texts are visited in insertion order (replacing a key keeps its position; remove
 * moves the last text into the freed slot), so callers ingest newest first.
 */
export interface SearchCorpusBinding {
  set_text(key: string, text: string): void;
  set_texts_json(entriesJson: string): void;
  remove(key: string): void;
  len(): number;
  search(query: string, maxSnippets: number): string;
  first_hits(query: string, maxResults: number): string;
}

export interface SavedMemoriesIndexBinding {
  set_entries_json(entriesJson: string): void;
  search(query: string, limit: number): string;
}

export interface CorpusFirstHit { key: string; snippet: string; snippetMatchStart: number; snippetMatchLength: number }
export interface CorpusMatch {
  key: string;
  ranges: Array<{ start: number; length: number }>;
  snippets: Array<{ snippet: string; snippetMatchStart: number; snippetMatchLength: number }>;
}

export const parseFirstHits = (json: string): CorpusFirstHit[] => JSON.parse(json);
export const parseCorpusMatches = (json: string): CorpusMatch[] => JSON.parse(json);
