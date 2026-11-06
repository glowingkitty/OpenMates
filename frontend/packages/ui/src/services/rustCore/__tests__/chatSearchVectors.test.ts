// TS-generated vectors for the Rust chat message search (web_search_chats.rs) and
// unit tests of the page/Worker search adapter. The committed JSON
// (packages/openmates-rust/src/web_search_chats_ts_vectors.json) holds index
// entries, queries and the output of the existing TypeScript
// `searchMessagesInChat`; this test fails when the TS behaviour drifts and the
// Rust tests replay the same file. Snippets are stored as UTF-16 code units so a
// snippet cut inside a surrogate pair survives JSON parsing in Rust.
// Regenerate: OPENMATES_REGEN_VECTORS=1 vitest run chatSearchVectors.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
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

import { searchMessagesInChat, type SearchEntries } from '../../searchService';
import { decodeSearchRows, materializeHits, type RustSearchEntry } from '../search/rustChatSearch';
import { installSearchUnit, type ChatSearchIndexBinding } from '../search/searchUnit';
import { createUnitPort, UnitPortError } from '../host/unitPort';
import type { SearchUnitProtocol } from '../search/searchUnitProtocol';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_search_chats_ts_vectors.json');

interface CaseEntry { messageId: string; content: string; embedId?: string; embedTitle?: string }
const filler = 'The quick brown fox jumps over the lazy dog. ';
const emoji = '\u{1F600} ';
const chats: Record<string, CaseEntry[]> = {
  plain: [
    { messageId: 'm3', content: 'Needle at the start then ' + filler.repeat(3) },
    { messageId: 'm3', content: filler.repeat(2) + 'needle in the middle ' + filler.repeat(2), embedId: 'e1', embedTitle: 'Needle doc' },
    { messageId: 'm2', content: 'no match here' },
    { messageId: 'm2', content: 'NEEDLE uppercase', embedId: 'e2', embedTitle: '' },
    { messageId: 'm2', content: 'needle again for m2', embedId: 'e3', embedTitle: 'Third' },
    { messageId: 'm2', content: 'and a third needle for m2', embedId: 'e3', embedTitle: 'Third child' },
    { messageId: 'm1', content: filler.repeat(4) + 'trailing needle' },
    { messageId: 'm0', content: 'needle m0 a' },
    { messageId: 'm9', content: 'needle m9', embedId: 'e4', embedTitle: 'Four' },
    { messageId: 'm8', content: 'needle m8', embedId: 'e5', embedTitle: 'Five' },
    { messageId: 'm7', content: 'needle m7', embedId: 'e6', embedTitle: 'Six' },
    { messageId: 'm6', content: 'needle m6', embedId: 'e7', embedTitle: 'Seven' },
    { messageId: 'm5', content: 'needle m5', embedId: 'e8', embedTitle: 'Eight' },
  ],
  unicode: [
    { messageId: 'u1', content: 'Straße İstanbul ' + emoji.repeat(30) + 'Gespräch über straße und mehr ' + emoji.repeat(30) },
    { messageId: 'u2', content: emoji.repeat(40) + 'hit ' + emoji.repeat(40) },
    { messageId: 'u3', content: 'İİİİ ' + filler.repeat(2) + 'İstanbul hit ' + filler },
    { messageId: 'u4', content: 'ΟΔΟΣ τέλος ΣΟΦΟΣ' },
    { messageId: 'u5', content: 'x'.repeat(60) + emoji + 'y'.repeat(10) + ' hit' },
  ],
  empty: [],
};
const queries: Array<[string, string, boolean]> = [
  ['plain', 'needle', false], ['plain', 'needle', true], ['plain', 'NEEDLE', true], ['plain', 'zzz', true],
  ['plain', 'the', false], ['plain', 'needle m', true],
  ['unicode', 'straße', false], ['unicode', 'hit', false], ['unicode', 'istanbul', false], ['unicode', 'İstanbul', false],
  ['unicode', 'σοφος', false], ['unicode', 'ος', false], ['unicode', '\u{1F600}', false], ['unicode', 'y hit', false],
  ['empty', 'x', true],
];

function toEntries(entries: CaseEntry[]): SearchEntries {
  return entries.map((entry, index) => ({
    ...entry, normalizedContent: entry.content.toLowerCase(), createdAt: 1000 - index,
    ...(entry.embedId ? { embedSourceLabel: 'Doc', embedType: 'docs-doc' } : {}),
  }));
}
const units = (text: string) => Array.from({ length: text.length }, (_, i) => text.charCodeAt(i));

async function compute() {
  const cases = [];
  for (const [chat, query, includeEmbeds] of queries) {
    const { snippets, embeds } = await searchMessagesInChat('chat', query, null, toEntries(chats[chat]), undefined, includeEmbeds);
    cases.push({
      chat, query, includeEmbeds,
      expected: {
        snippets: snippets.map((s) => ({ messageId: s.messageId, embedId: s.embedId ?? null, snippetUnits: units(s.snippet), matchStart: s.matchStart, matchLength: s.matchLength })),
        embeds: embeds.map((e) => ({ embedId: e.embedId, messageId: e.messageId })),
      },
    });
  }
  return { chats, cases };
}

describe('Rust chat search vectors', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('matches the committed TypeScript-generated vectors', async () => {
    const actual = JSON.parse(JSON.stringify(await compute()));
    if (process.env.OPENMATES_REGEN_VECTORS === '1') writeFileSync(VECTORS, JSON.stringify(actual) + '\n');
    expect(actual).toEqual(JSON.parse(readFileSync(VECTORS, 'utf8')));
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('rebuilds searchMessagesInChat results from Worker rows', async () => {
    const entries = toEntries(chats.plain) as RustSearchEntry[];
    const text = entries[1].content;
    const start = text.toLowerCase().indexOf('needle');
    // Row of the second entry: plan the TS snippet by hand as [from, to, flags, matchStart].
    const ts = await searchMessagesInChat('chat', 'needle', null, entries as SearchEntries, undefined, true);
    const expected = ts.snippets.find((snippet) => snippet.embedId === 'e1')!;
    const body = expected.snippet.replace(/^\.\.\. /, '').replace(/ \.\.\.$/, '');
    const from = text.indexOf(body);
    const rows = new Uint32Array([0, 1, 1, 1, from, from + body.length, 3, expected.matchStart, 1]);
    const decoded = decodeSearchRows(rows, [{ chatId: 'chat', entries }]);
    const built = materializeHits(decoded.get('chat'), 6, null);
    expect(start).toBeGreaterThan(0);
    expect(built.snippets).toEqual([expected]);
    expect(built.embeds).toEqual([ts.embeds.find((embed) => embed.embedId === 'e1')]);
    expect(() => decodeSearchRows(new Uint32Array([5, 0, 0]), [{ chatId: 'chat', entries }])).toThrow('rust_search_bad_rows');
    expect(() => decodeSearchRows(new Uint32Array([0, 2, 0, 1]), [{ chatId: 'chat', entries }])).toThrow('rust_search_bad_rows');
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('search unit applies removes and sets in order, refuses bad payloads and frees the index on close', async () => {
    const calls: string[] = [];
    class FakeIndex implements ChatSearchIndexBinding {
      reset_chat(handle: number) { calls.push(`reset:${handle}`); }
      push_entry(handle: number, messageId: string, text: string, embedId: string, titled: boolean) { calls.push(`push:${handle}:${messageId}:${text}:${embedId}:${titled}`); }
      remove_chat(handle: number) { calls.push(`remove:${handle}`); }
      clear() { calls.push('clear'); }
      chat_count() { return 2; }
      search(query: string, handles: Uint32Array, includeEmbeds: boolean) { calls.push(`search:${query}:${[...handles]}:${includeEmbeds}`); return new Uint32Array([0, 0, 0]); }
      free() { calls.push('free'); }
    }
    const channel = new MessageChannel();
    const controller = new AbortController();
    installSearchUnit({ binding: { ChatSearchIndex: FakeIndex }, ports: [channel.port2], generation: null, principal: null, signal: controller.signal });
    const port = createUnitPort<SearchUnitProtocol>(channel.port1);
    const reply = await port.request('search', {
      removes: [3], query: 'q', handles: new Uint32Array([1]), includeEmbeds: true,
      sets: [{ handle: 1, messageIds: ['m'], contents: ['text'], embedIds: [''], embedTitled: new Uint8Array([0]) }],
    });
    expect([...reply.rows]).toEqual([0, 0, 0]);
    expect(calls).toEqual(['remove:3', 'reset:1', 'push:1:m:text::false', 'search:q:1:true']);
    await expect(port.request('search', { removes: [0], sets: [], query: 'q', handles: new Uint32Array(), includeEmbeds: false }))
      .rejects.toEqual(new UnitPortError('protocol'));
    expect(await port.request('close', {})).toEqual({ chats: 2 });
    await new Promise((settle) => setTimeout(settle, 5));
    expect(calls[calls.length - 1]).toBe('free');
    port.close();
    expect(() => installSearchUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: controller.signal })).toThrow('unavailable');
  });
});
