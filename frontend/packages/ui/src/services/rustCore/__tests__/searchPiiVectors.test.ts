// Vectors for the Rust web search / PII alias ports (U16/U18).
// The committed JSON (packages/openmates-rust/src/web_search_ts_vectors.json) holds
// inputs plus expected outputs (match/snippet outputs frozen from the former TypeScript
// search; saved-embed and PII outputs still come from the live TS helpers). The Rust
// unit tests check the same file. Regenerate the live parts with OPENMATES_REGEN_VECTORS.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../db', () => ({ chatDB: { getMessagesForChat: vi.fn(), getAllAppSettingsMemoriesEntries: async () => [] } }));
vi.mock('../../chatMetadataCache', () => ({ chatMetadataCache: { getDecryptedMetadata: vi.fn() } }));
vi.mock('../../embedStore', () => ({ embedStore: { get: vi.fn() } }));
vi.mock('../../embedResolver', () => ({ extractEmbedReferences: () => [], decodeToonContent: async () => ({}) }));
vi.mock('../../searchSettingsCatalog', () => ({ getSettingsSearchCatalog: () => [], getAppSearchCatalog: () => [] }));
vi.mock('../../../data/appsMetadata', () => ({ appsMetadata: {} }));
vi.mock('../../../demo_chats', () => ({
  getDemoMessages: () => [], isPublicChat: () => false, isExampleChat: () => false,
  getExampleChatEmbed: () => undefined, INTRO_CHATS: [], LEGAL_CHATS: [],
}));

import { searchSavedEmbedMemories } from '../../embedSuggestionSearch';
import { createPIIDisplayAliases } from '../../piiDisplayAliases';
import { createSearchPiiAdapter, toOrderedMemories, toOrderedSource, type SearchPiiBinding } from '../search/searchPiiAdapter';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_search_ts_vectors.json');

const long = 'The quick brown fox jumps over the lazy dog. '.repeat(8) + 'Needle in a haystack with \u{1F600} emoji and Straße, İstanbul. ' + 'tail words follow here '.repeat(6);
const matchCases = [
  { text: 'Hello hello HELLO', query: 'hello' },
  { text: 'aaaa', query: 'aa' },
  { text: 'Straße İstanbul \u{1F600} straße', query: 'straße' },
  { text: 'İİ x', query: 'x' },
  { text: long, query: 'needle' },
  { text: 'nothing here', query: 'zzz' },
  { text: '', query: 'a' },
];
const snippetCases = [
  { content: long, start: long.toLowerCase().indexOf('needle'), length: 6 },
  { content: 'short text match here', start: 11, length: 5 },
  { content: 'x'.repeat(200), start: 100, length: 3 },
  { content: 'one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen match eighteen nineteen twenty twenty-one twenty-two twenty-three', start: 88, length: 5 },
  { content: '\u{1F600} '.repeat(40) + 'hit ' + '\u{1F600} '.repeat(40), start: 120, length: 3 },
];
const memoryCases = [
  {
    entries: [
      ['events', { saved_events: [
        { id: 'a', item_value: { embed_id: 'e1', title: 'Berlin design Gathering', location: 'Berlin', note: ' Design  ', url: 'https://x' }, updated_at: 1 },
        { id: 'b', item_value: { embed_id: 'e1', title: 'Berlin design Gathering', location: 'Berlin' }, updated_at: 2 },
        { item_value: { embed_id: 'e2', name: 'Munich', where: 'Hall · 4', origin: 'A', provider: 'P' }, updated_at: 3 },
        { id: 'c', item_value: { embed_id: ' ', title: 'blank' }, updated_at: 9 },
      ], saved_trips: [
        { id: 'd', item_value: { embed_id: 'e3', foo: 'design notes', bar: 5, baz: null }, updated_at: 0.5 },
        { id: 'f', item_value: { embed_id: 'e4', title: 'Zebra İstanbul', address: 'x'.repeat(200), extra: 'y'.repeat(300) } },
      ] }],
      ['travel', { stays: [{ id: 'g', item_value: { embed_id: 'e5', title: 'DESIGN hotel' }, updated_at: 3 }] }],
    ],
    queries: [['design', 6], ['  DESIGN ', 2], ['munich', 6], ['', 6], ['zzz', 6], ['design', 0], ['İstanbul', 6], ['x', 6]],
  },
];
const piiFirst = { type: 'ADDRESS', original: 'Maple Avenue', placeholder: '[ADDRESS_1_0000000000000001]' };
const piiSecond = { type: 'ADDRESS', original: 'Birch Lane', placeholder: '[ADDRESS_1_0000000000000002]' };
const piiMail = { type: 'EMAIL', original: 'a@example.test', placeholder: '[EMAIL_2_00000000000000ff_3_0123456789abcdef0123456789abcdef]' };
const piiCases = [
  { source: `${piiSecond.placeholder} ${piiFirst.placeholder} ${piiSecond.placeholder}`, mappings: [piiFirst, piiSecond], configured: [] },
  { source: `[ADDRESS_1] ${piiFirst.placeholder} ${piiSecond.placeholder}`, mappings: [piiFirst, piiSecond, { type: 'ADDRESS', original: 'Existing Road', placeholder: '[ADDRESS_2]' }], configured: ['ADDRESS_3'] },
  { source: { a: ['text with Maple Avenue', { b: piiMail.placeholder }], 2: 'Birch Lane', n: 5, z: null }, mappings: [piiSecond, piiMail, piiFirst], configured: [] },
  { source: null, mappings: [piiFirst], configured: [] },
  { source: piiFirst.placeholder, mappings: [piiFirst], configured: [piiFirst.placeholder, ''] },
  { source: 'no mention of anything [EMAIL_1] [EMAIL_2]', mappings: [{ ...piiMail, original: '' }, { type: 'EMAIL', placeholder: '[EMAIL_9_00000000000000aa]' }], configured: [] },
];

function memoriesMap(entries: unknown[]) {
  return new Map(entries.map(([app, groups]) => [app as string, groups as Record<string, Array<{ id?: string; item_value: Record<string, unknown>; updated_at?: number }>>]));
}

function compute() {
  return {
    matchRanges: matchCases,
    snippets: snippetCases,
    savedEmbeds: memoryCases.flatMap(m => m.queries.map(([query, limit]) => ({
      entries: toOrderedMemories(memoriesMap(m.entries)),
      query, limit,
      expected: searchSavedEmbedMemories({ entriesByApp: memoriesMap(m.entries) }, query as string, limit as number),
    }))),
    piiAliases: piiCases.map(c => ({
      source: toOrderedSource(c.source), mappings: c.mappings, configured: c.configured,
      expected: [...createPIIDisplayAliases(c.source as never, c.mappings as never, c.configured)],
    })),
  };
}

describe('Rust search/PII vectors', () => {
  // contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
  it('matches the committed TypeScript-generated vectors', () => {
    const actual = JSON.parse(JSON.stringify(compute()));
    const committed = JSON.parse(readFileSync(VECTORS, 'utf8'));
    // matchRanges/snippets expectations were frozen from the former TypeScript
    // functions (deleted); only their inputs are checked here, Rust asserts the outputs.
    const inputsOnly = (cases: Array<Record<string, unknown>>) => cases.map(({ expected: _expected, ...input }) => input);
    expect({ ...actual, matchRanges: inputsOnly(actual.matchRanges), snippets: inputsOnly(actual.snippets) })
      .toEqual({ ...committed, matchRanges: inputsOnly(committed.matchRanges), snippets: inputsOnly(committed.snippets) });
  });

  // contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
  it('adapter converts to ordered JSON and parses binding results', () => {
    const calls: string[] = [];
    const binding: SearchPiiBinding = {
      search_find_match_ranges: (t, q) => { calls.push(`r:${t}:${q}`); return '[{"start":1,"length":2}]'; },
      search_build_snippet: () => '{"snippet":"s","snippetMatchStart":0,"snippetMatchLength":1}',
      search_saved_embed_memories: (json) => { calls.push(json); return '[]'; },
      pii_create_display_aliases: (s) => { calls.push(s); return '[["[A_1_x]","[A_1]"]]'; },
    };
    const adapter = createSearchPiiAdapter(binding);
    expect(adapter.findMatchRanges('ab', 'b')).toEqual([{ start: 1, length: 2 }]);
    expect(adapter.createPIIDisplayAliases({ b: 'x', a: ['y'] }, [], []).get('[A_1_x]')).toBe('[A_1]');
    expect(calls[1]).toBe('{"$entries":[["b","x"],["a",["y"]]]}');
    adapter.searchSavedEmbedMemories({ entriesByApp: memoriesMap([['app', { g: [{ id: '1', item_value: { k: 'v' } }] }]]) }, 'q');
    expect(JSON.parse(calls[2])).toEqual([['app', [['g', [{ id: '1', item_value: [['k', 'v']] }]]]]]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
  it('records TypeScript timings for the Rust comparison', () => {
    const t2 = performance.now();
    const big = memoriesMap([['app', { g: Array.from({ length: 2000 }, (_, i) => ({ id: String(i), item_value: { embed_id: `e${i}`, title: `Design item ${i}`, location: 'Berlin' }, updated_at: i })) }]]);
    for (let i = 0; i < 20; i++) searchSavedEmbedMemories({ entriesByApp: new Map(big) }, 'design');
    const t3 = performance.now();
    const line = `TS_TIMINGS_MS memories=${(t3 - t2).toFixed(2)}\n`;
    if (process.env.OPENMATES_TIMINGS_FILE) writeFileSync(process.env.OPENMATES_TIMINGS_FILE, line);
    expect(t3).toBeGreaterThan(0);
  });
});
