// Page-side pipelining of the Worker search index (rustChatSearch.ts): ingests are
// posted without waiting for the Worker's reply, a query settles every posted ingest
// first (so budget evictions are known and an ingest failure is not hidden), and the
// requests reach the Worker in the order the page posted them.
import { afterEach, describe, expect, it, vi } from 'vitest';

const harness = vi.hoisted(() => ({ openUnit: null as null | (() => Promise<MessagePort>) }));
vi.mock('../host/sharedCoreRegistry', () => ({
  whenSharedRustCore: async () => ({
    generation: 1,
    openUnit: () => harness.openUnit?.(),
    onCrash: () => () => undefined,
  }),
}));

import { clearRustChatSearch, ingestRustChat, invalidateRustChat, isRustChatIndexed, queryRustSearch, rustChatEpoch, settleRustIngests, type RustQueryInput } from '../search/rustChatSearch';
import { installSearchUnit, type ChatSearchIndexBinding } from '../search/searchUnit';

const entry = [{ messageId: 'm', content: 'text', createdAt: 1 }];
const input = (chatIds: string[]): RustQueryInput => ({
  query: 'q', includeEmbeds: false, isAuthenticated: false, isAdmin: false, settings: [], apps: [],
  chats: chatIds.map((chatId) => ({ chatId, messages: true, title: null, activeFocusId: null, summary: null, tags: null, draft: null, lastEdited: 1 })),
});

function openWith(index: new () => ChatSearchIndexBinding): void {
  harness.openUnit = async () => {
    const channel = new MessageChannel();
    installSearchUnit({ binding: { ChatSearchIndex: index }, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal });
    return channel.port1;
  };
}

afterEach(() => { clearRustChatSearch(); harness.openUnit = null; });

describe('rustChatSearch ingest pipelining', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('posts ingests without waiting for replies, then the query names only surviving handles', async () => {
    const calls: string[] = [];
    class Index implements ChatSearchIndexBinding {
      ingest_chat(handle: number) { calls.push(`ingest:${handle}`); return new Uint32Array(calls.length === 3 ? [Number(calls[0].split(':')[1])] : []); }
      remove_chat(handle: number) { calls.push(`remove:${handle}`); }
      clear() { /* unused */ }
      chat_count() { return 0; }
      query(_query: string, _flags: number, handles: Uint32Array) {
        calls.push(`query:${[...handles]}`);
        return { rows: new Uint32Array([0, 0, 0, 0]), texts: [], numbers: new Float64Array() };
      }
      free() { /* unused */ }
    }
    openWith(Index);
    await ingestRustChat('a', entry, 0);
    await ingestRustChat('b', entry, 0);
    await ingestRustChat('c', entry, 0);
    expect(['a', 'b', 'c'].map(isRustChatIndexed)).toEqual([true, true, true]);
    await queryRustSearch(input(['a', 'b', 'c']));
    // The first handle (chat a) was evicted by the Worker's budget when chat c was added: no message search for it.
    const base = Number(calls[0].split(':')[1]);
    expect(calls).toEqual([`ingest:${base}`, `ingest:${base + 1}`, `ingest:${base + 2}`, `query:0,${base + 1},${base + 2}`]);
    expect(isRustChatIndexed('a')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('drops an invalidated chat with the next request and keeps request order', async () => {
    const calls: string[] = [];
    class Index implements ChatSearchIndexBinding {
      ingest_chat(handle: number) { calls.push(`ingest:${handle}`); return new Uint32Array(); }
      remove_chat(handle: number) { calls.push(`remove:${handle}`); }
      clear() { /* unused */ }
      chat_count() { return 0; }
      query(_query: string, _flags: number, handles: Uint32Array) {
        calls.push(`query:${[...handles]}`);
        return { rows: new Uint32Array([0, 0, 0, 0]), texts: [], numbers: new Float64Array() };
      }
      free() { /* unused */ }
    }
    openWith(Index);
    await ingestRustChat('a', entry, rustChatEpoch('a'));
    invalidateRustChat('a');
    expect(isRustChatIndexed('a')).toBe(false);
    await ingestRustChat('a', entry, rustChatEpoch('a'));
    await queryRustSearch(input(['a']));
    const base = Number(calls[0].split(':')[1]);
    expect(calls).toEqual([`ingest:${base}`, `remove:${base}`, `ingest:${base + 1}`, `query:${base + 1}`]);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('rejects the query when a posted ingest failed instead of searching an unknown index', async () => {
    class Index implements ChatSearchIndexBinding {
      ingest_chat(): Uint32Array { throw 'protocol'; }
      remove_chat() { /* unused */ }
      clear() { /* unused */ }
      chat_count() { return 0; }
      query() { return { rows: new Uint32Array([0, 0, 0, 0]), texts: [], numbers: new Float64Array() }; }
      free() { /* unused */ }
    }
    openWith(Index);
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    await ingestRustChat('a', entry, 0);
    await expect(settleRustIngests()).rejects.toMatchObject({ code: 'protocol' });
    expect(isRustChatIndexed('a')).toBe(false);
  });
});
