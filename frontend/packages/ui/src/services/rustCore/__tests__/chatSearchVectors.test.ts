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
import { decodeSearchReply, ingestColumns, queryColumns } from '../search/rustChatSearch';
import { installSearchUnit, type ChatSearchIndexBinding } from '../search/searchUnit';
import { createUnitPort, UnitPortError } from '../host/unitPort';
import { FOCUS_NONE, NO_TEXT, type SearchUnitProtocol } from '../search/searchUnitProtocol';

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
  it('encodes ingest and query columns and decodes Worker rows into searchService results', () => {
    const chat = ingestColumns(4, [
      { messageId: 'm1', content: 'plain', createdAt: 2 },
      { messageId: 'm1', content: 'embed', createdAt: 2, embedSourceLabel: 'Doc', embedId: 'e1', embedTitle: 'T' },
    ]);
    expect({ ...chat, createdAt: [...chat.createdAt], metaEntries: [...chat.metaEntries], metaMasks: [...chat.metaMasks] }).toEqual({
      handle: 4, messageIds: ['m1', 'm1'], contents: ['plain', 'embed'], createdAt: [2, 2],
      metaEntries: [1], metaMasks: [0b1011], metaValues: ['Doc', 'e1', 'T'],
    });
    const columns = queryColumns({
      query: 'q', includeEmbeds: true, isAuthenticated: true, isAdmin: false,
      chats: [
        { chatId: 'a', messages: true, title: 'Title', activeFocusId: null, summary: 'S', tags: ['x', 'y'], draft: null, lastEdited: 9 },
        { chatId: 'b', messages: false, title: null, activeFocusId: 'f', summary: null, tags: null, draft: 'D', lastEdited: 8 },
      ],
      settings: [{ label: 'Admin', keywords: ['k'], access: 'admin' }],
      apps: [{ label: 'App', keywords: [] }],
    }, (chatId) => (chatId === 'a' ? 7 : 99));
    expect([...columns.handles]).toEqual([7, 0]);
    expect([...columns.chatMasks]).toEqual([1 | 4 | 16, 2 | 8]);
    expect(columns.chatValues).toEqual(['Title', 'S', 'x', 'y', 'f', 'D']);
    expect([...columns.tagCounts]).toEqual([2, 0]);
    expect([...columns.catalogFlags]).toEqual([2, 4]);
    expect(columns.flags).toBe(3);

    const texts = ['... the snippet', 'm1', 'Doc', 'e1', 'tag', 'e1', 'docs-doc', 'm1', 'Title', 'Doc'];
    const rows = new Uint32Array([
      1, 1, 1, 1,
      0, 1, 1, 1, 0, 3,
      0, 4, 3, 1, 2, 3, NO_TEXT, NO_TEXT, NO_TEXT, NO_TEXT, NO_TEXT, FOCUS_NONE,
      4, 0, 3, 1,
      0, 5, 6, 7, 8, 9, NO_TEXT,
      0,
      3,
    ]);
    const decoded = decodeSearchReply({ rows, texts, numbers: new Float64Array([2]) }, ['a', 'b'], 1);
    expect(decoded).toEqual({
      chats: [{
        position: 0, titleMatchRanges: [{ start: 0, length: 3 }],
        messageSnippets: [{ messageId: 'm1', chatId: 'a', snippet: '... the snippet', matchStart: 4, matchLength: 3, embedSourceLabel: 'Doc', embedId: 'e1', embedFocusIsActive: undefined }],
        metadataSnippets: [{ chatId: 'a', snippet: 'tag', matchStart: 0, matchLength: 3, matchSource: 'tags' }],
      }],
      embeds: [{ embedId: 'e1', embedType: 'docs-doc', chatId: 'a', messageId: 'm1', title: 'Title', subtitle: 'Doc', appId: undefined, createdAt: 2 }],
      settings: [0],
      apps: [2],
    });
    expect(() => decodeSearchReply({ rows: new Uint32Array([1, 0, 0, 0, 5, 0, 0, 0]), texts: [], numbers: new Float64Array() }, ['a'], 0)).toThrow('rust_search_bad_rows');
    expect(() => decodeSearchReply({ rows: new Uint32Array([0, 0, 0, 0, 1]), texts: [], numbers: new Float64Array() }, ['a'], 0)).toThrow('rust_search_bad_rows');
    expect(() => decodeSearchReply({ rows: new Uint32Array([0, 1, 0, 0]), texts: [], numbers: new Float64Array() }, ['a'], 0)).toThrow('rust_search_bad_rows');
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('search unit applies removes before ingest and query, refuses bad payloads and frees the index on close', async () => {
    const calls: string[] = [];
    class FakeIndex implements ChatSearchIndexBinding {
      ingest_chat(handle: number, messageIds: string[], contents: string[]) { calls.push(`ingest:${handle}:${messageIds}:${contents}`); return new Uint32Array([2]); }
      remove_chat(handle: number) { calls.push(`remove:${handle}`); }
      clear() { calls.push('clear'); }
      chat_count() { return 2; }
      query(query: string, flags: number, handles: Uint32Array) {
        calls.push(`query:${query}:${flags}:${[...handles]}`);
        if (query === 'bad') throw 'protocol';
        return { rows: new Uint32Array([0, 0, 0, 0]), texts: [], numbers: new Float64Array() };
      }
      free() { calls.push('free'); }
    }
    const channel = new MessageChannel();
    const controller = new AbortController();
    installSearchUnit({ binding: { ChatSearchIndex: FakeIndex }, ports: [channel.port2], generation: null, principal: null, signal: controller.signal });
    const port = createUnitPort<SearchUnitProtocol>(channel.port1);
    const ingest = await port.request('ingest', { removes: [3], chat: ingestColumns(1, [{ messageId: 'm', content: 'text', createdAt: 1 }]) });
    expect([...ingest.evicted]).toEqual([2]);
    const query = { query: 'q', removes: [5], ...queryColumns({ query: 'q', includeEmbeds: false, isAuthenticated: false, isAdmin: false, chats: [], settings: [], apps: [] }, () => 0) };
    expect([...(await port.request('query', query)).rows]).toEqual([0, 0, 0, 0]);
    expect(calls).toEqual(['remove:3', 'ingest:1:m:text', 'remove:5', 'query:q:0:']);
    await expect(port.request('query', { ...query, removes: [], query: 'bad' })).rejects.toEqual(new UnitPortError('protocol'));
    await expect(port.request('query', { ...query, removes: [0] })).rejects.toEqual(new UnitPortError('protocol'));
    await expect(port.request('ingest', { removes: [], chat: { ...ingestColumns(1, []), createdAt: [] as unknown as Float64Array } })).rejects.toEqual(new UnitPortError('protocol'));
    expect(await port.request('close', {})).toEqual({ chats: 2 });
    await new Promise((settle) => setTimeout(settle, 5));
    expect(calls[calls.length - 1]).toBe('free');
    port.close();
    expect(() => installSearchUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: controller.signal })).toThrow('unavailable');
  });
});
