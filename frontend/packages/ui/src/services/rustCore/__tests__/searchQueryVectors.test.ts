/**
 * Vectors for the Rust search query
 * (packages/openmates-rust/src/web_search_query_tests.rs replays them).
 *
 * Runs `search()` against a recording stand-in of rustChatSearch.ts and checks
 * that the page transfers exactly the committed inputs to the Worker: each chat's
 * ingested entries and the query input. The expected results in the vector file
 * are frozen from the former TypeScript search (deleted).
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const fixtures = vi.hoisted(() => {
  const filler = 'The quick brown fox jumps over the lazy dog. ';
  const ref = (type: string, id: string) => '```json\n' + JSON.stringify({ type, embed_id: id }) + '\n```';
  const messages: Record<string, Array<{ message_id: string; content: string; created_at: number }>> = {
    'c-alpha': [
      { message_id: 'a1', content: 'Loading **pandas** dataframes in Python', created_at: 100 },
      { message_id: 'a2', content: 'The pandas library: ' + filler.repeat(2) + 'needle here ' + filler + '\n' + ref('code', 'e-code') + '\n' + ref('focus_mode_activation', 'e-focus'), created_at: 110 },
    ],
    'c-beta': [
      { message_id: 'b1', content: 'Straße und İstanbul: the needle \u{1F600} ' + '\u{1F600}'.repeat(30), created_at: 205 },
      { message_id: 'b2', content: ref('focus_mode_activation', 'e-focus-2') + ' focus again', created_at: 206 },
    ],
    'demo-1': [{ message_id: 'd1', content: 'Welcome to the demo needle', created_at: 50 }],
    'c-many': Array.from({ length: 8 }, (_, n) => ({
      message_id: `n${n}`,
      content: `Message ${n} has the needle ` + ref('docs', `e-doc-${n}`) + ' ' + ref('docs', `e-doc-x${n}`),
      created_at: 300 + n,
    })),
    'c-hidden': [{ message_id: 'h1', content: 'Hidden chat with the needle', created_at: 400 }],
  };
  const embeds: Record<string, Record<string, unknown>> = {
    'e-code': { type: 'code', status: 'finished', content: JSON.stringify({ title: 'pandas_demo.py', code: 'import pandas as pd # the needle', app_id: 'code' }) },
    'e-focus': { type: 'focus_mode_activation', status: 'finished', content: JSON.stringify({ focus_id: 'jobs-career', focus_mode_name: 'Career insights', description: 'Career focus needle' }) },
    'e-focus-2': { type: 'focus_mode_activation', status: 'finished', content: JSON.stringify({ focus_id: 'other-focus', focus_mode_name: 'Other', description: 'Another focus needle' }) },
  };
  for (let n = 0; n < 8; n++) {
    embeds[`e-doc-${n}`] = { type: 'docs', status: 'finished', content: JSON.stringify({ title: n % 2 ? `Needle doc ${n}` : `Doc ${n}`, body: `Document ${n} body with the needle` }) };
    embeds[`e-doc-x${n}`] = { type: 'docs', status: 'finished', content: JSON.stringify({ title: `Extra ${n}`, body: `Extra ${n} body with the needle` }) };
  }
  const metadata: Record<string, Record<string, unknown>> = {
    'c-alpha': { title: 'Pandas notebook', summary: 'Summary about ' + filler + 'pandas and the zoo needle', tags: ['data', 'Pandas'], draftPreview: null, activeFocusId: 'jobs-career' },
    'c-beta': { title: '', summary: null, tags: null, draftPreview: 'draft about the needle', activeFocusId: null },
    'c-meta': { title: 'Old trip', summary: 'Trip to the pandas reserve', tags: ['travel', 'Needle tag'], draftPreview: null },
    'c-many': { title: 'The many needles', summary: 'ΟΔΟΣ summary needle', tags: [], activeFocusId: null },
    'c-hidden': { title: 'Hidden', summary: null, tags: null },
  };
  const settings = [
    { path: 'privacy', translationKey: 'settings.privacy', icon: 'lock', keywords: ['data protection', 'needle'] },
    { path: 'admin', translationKey: 'settings.admin', icon: 'shield', keywords: ['needle admin'], access: 'admin' },
    { path: 'account', translationKey: 'settings.account', icon: 'user', keywords: ['the profile'], access: 'authenticated' },
    { path: 'public-x', translationKey: 'settings.public', icon: 'globe', keywords: [], access: 'public' },
  ];
  const apps = [
    { path: 'apps/code', nameTranslationKey: 'apps.code', icon: 'code', keywords: ['python pandas'], entryType: 'app' },
    { path: 'apps/jobs/focus/career', icon: null, keywords: ['career'], entryType: 'focus_mode' },
    { path: 'apps/the-needle', nameTranslationKey: 'apps.needle', icon: 'x', keywords: [], entryType: 'skill' },
  ];
  const labels: Record<string, string> = {
    'settings.privacy': 'Privacy', 'settings.admin': 'Admin tools', 'settings.account': 'Account', 'settings.public': 'Public Pandas',
    'apps.code': 'Code', 'apps.needle': 'Needle skill',
  };
  return { messages, embeds, metadata, settings, apps, labels };
});

vi.mock('../../db', () => ({
  chatDB: { getMessagesForChat: async (chatId: string) => fixtures.messages[chatId] ?? [], getAllAppSettingsMemoriesEntries: async () => [] },
}));
vi.mock('../../chatMetadataCache', () => ({
  chatMetadataCache: { getDecryptedMetadata: async (chat: { chat_id: string }) => fixtures.metadata[chat.chat_id] ?? null },
}));
vi.mock('../../embedStore', () => ({ embedStore: { get: async (key: string) => fixtures.embeds[key.slice('embed:'.length)] ?? null } }));
vi.mock('../../embedResolver', () => ({
  extractEmbedReferences: (markdown: string) => [...markdown.matchAll(/```json\n([\s\S]*?)\n```/g)].map((match) => JSON.parse(match[1])),
  decodeToonContent: async (content: string) => JSON.parse(content),
}));
vi.mock('../../searchSettingsCatalog', () => ({ getSettingsSearchCatalog: () => fixtures.settings, getAppSearchCatalog: () => fixtures.apps }));
vi.mock('../../../data/appsMetadata', () => ({ appsMetadata: {} }));
vi.mock('../../../demo_chats', () => ({
  getDemoMessages: (chatId: string) => fixtures.messages[chatId] ?? [], isPublicChat: (chatId: string) => chatId.startsWith('demo-'),
  isExampleChat: () => false, getExampleChatEmbed: () => undefined, INTRO_CHATS: [], LEGAL_CHATS: [],
}));

const recorded = vi.hoisted(() => ({ ingests: new Map<string, unknown>(), queries: [] as unknown[] }));
vi.mock('../search/rustChatSearch', () => ({
  isRustChatIndexed: (chatId: string) => recorded.ingests.has(chatId),
  rustChatEpoch: () => 0,
  invalidateRustChat: () => undefined,
  prepareRustChatSearch: async () => undefined,
  ingestRustChat: async (chatId: string, entries: unknown[]) => { recorded.ingests.set(chatId, entries); },
  queryRustSearch: async (input: unknown) => {
    recorded.queries.push(input);
    return { chats: [], embeds: [], settings: [], apps: [] };
  },
}));

import { search, warmUpMetadataSearchIndex } from '../../searchService';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_search_query_ts_vectors.json');

const chat = (chatId: string, title: string | null, lastEdited: number, metadataOnly = false) =>
  ({ chat_id: chatId, title, is_metadata_only: metadataOnly, last_edited_overall_timestamp: lastEdited }) as never;
const visible = [chat('c-alpha', 'Alpha', 9000), chat('c-beta', 'Beta needle chat', 8000), chat('c-meta', null, 7000, true), chat('demo-1', 'Demo: the welcome', 6000), chat('c-many', null, 5000)];
const hidden = [chat('c-hidden', null, 4000)];
const textFn = (key: string) => fixtures.labels[key] ?? key;
const queries: Array<[string, boolean, boolean, boolean]> = [
  ['needle', false, true, false], ['needle', true, true, true], ['the', true, false, false], ['PANDAS', true, true, false],
  ['career', true, true, false], ['straße', false, true, false], ['ος', false, true, false], ['zzz', true, true, true],
  ['data', false, true, false], ['draft', false, false, false], ['profile', false, true, false],
];

async function compute() {
  await warmUpMetadataSearchIndex(visible);
  let inputs: unknown = null;
  for (const [query, includeEmbeds, isAuthenticated, isAdmin] of queries) {
    recorded.queries.length = 0;
    await search(query, visible, textFn, hidden, isAuthenticated, isAdmin, undefined, includeEmbeds);
    expect(recorded.queries).toHaveLength(1);
    const input = recorded.queries[0] as { chats: unknown; settings: unknown; apps: unknown };
    inputs ??= { chats: input.chats, settings: input.settings, apps: input.apps };
    expect({ chats: input.chats, settings: input.settings, apps: input.apps }, 'per-query inputs do not depend on the query').toEqual(inputs);
  }
  return { ingests: Object.fromEntries(recorded.ingests), ...(inputs as object) };
}

describe('Rust search query vectors', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('transfers the committed per-chat inputs to the Worker', async () => {
    // Undefined fields are dropped like JSON drops them; Rust reads absent as undefined.
    const actual = JSON.parse(JSON.stringify(await compute()));
    expect(Object.keys(actual.ingests).sort()).toEqual(['c-alpha', 'c-beta', 'c-hidden', 'c-many', 'demo-1']);
    // The committed vectors also hold the expected results (frozen from the former
    // TypeScript search); only the page-built inputs are recomputed here.
    const { cases: _cases, ...committed } = JSON.parse(readFileSync(VECTORS, 'utf8'));
    // The page no longer sends `normalizedContent` (the Rust index lowercases itself);
    // the committed file keeps it for the Rust replay, which ignores the field.
    for (const entries of Object.values(committed.ingests as Record<string, Array<Record<string, unknown>>>)) {
      for (const entry of entries) delete entry.normalizedContent;
    }
    expect(actual).toEqual(committed);
  });
});
