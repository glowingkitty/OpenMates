// Minimal sidebar metadata preserves hidden-key privacy without loading transcripts.
// These tests exercise real encryption/decoding and publication fences locally.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { OpenMatesClient } from '../src/client.js';
import { encryptBytesWithAesGcm, encryptWithAesGcmCombined } from '../src/crypto.js';
import { loadSyncCache, saveSyncCache } from '../src/storage.js';

function fixture() {
  let master = Buffer.alloc(32, 1);
  const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
  Object.assign(client, { requireSession: () => {}, hasSession: () => true,
    resolveTeamContext: () => null, getMasterKeyBytes: () => master,
    getChatWrappingKey: async () => master, getCliRequestHeaders: () => ({}), appendTeamQuery: (path: string) => path });
  return { client, master, changeAccount: () => { master = Buffer.alloc(32, 2); } };
}

// contract-test: supporting surface=cli assertions=chat-navigation.projects.organize
test('project naming sends structured titles through the naming route', async () => {
  const { client } = fixture();
  let request: unknown;
  Object.assign(client, { http: { post: async (route: string, body: unknown) => {
    assert.equal(route, '/v1/projects/ask/plan'); request = body;
    return { ok: true, data: { proposed_project: { name: 'Website launch' } } };
  } } });
  const result = await client.planProjectAsk({ instruction: 'Name a new project from chat titles.', chatTitles: ['Launch copy'] });
  assert.deepEqual(request, { instruction: 'Name a new project from chat titles.', chat_titles: ['Launch copy'] });
  assert.deepEqual(result.proposed_project, { name: 'Website launch' });
});

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running,chat-navigation.projects.nested-readable
test('sidebar metadata distinguishes a readable untitled chat from a locked hidden key', async () => {
  const { client, master } = fixture(), key = Buffer.alloc(32, 3);
  let path = '', body: unknown;
  Object.assign(client, { http: { post: async (route: string, payload: unknown) => {
    path = route; body = payload;
    return { ok: true, data: { chats: [
      { id: 'normal', encrypted_chat_key: await encryptBytesWithAesGcm(key, master), updated_at: '1700000100' },
      { id: 'locked', encrypted_chat_key: await encryptBytesWithAesGcm(key, Buffer.alloc(32, 9)), encrypted_title: await encryptWithAesGcmCombined('Private topic', key), parent_id: 'normal' },
    ] } };
  } } });
  const result = await client.getSidebarChats(['normal', 'locked']);
  assert.equal(path, '/v1/chats/metadata/batch'); assert.deepEqual(body, { chat_ids: ['normal', 'locked'] });
  assert.equal(result[0].isHiddenCandidate, false); assert.equal(result[0].title, null);
  assert.equal(result[0].updatedAt, 1700000100);
  assert.equal(result[1].isHiddenCandidate, true); assert.equal(result[1].title, null);
  assert.equal(result[1].parentId, 'normal');
});

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running
test('sidebar metadata cannot return plaintext after an account change during the request', async () => {
  const { client, master, changeAccount } = fixture(), key = Buffer.alloc(32, 3);
  const row = { id: 'normal', encrypted_chat_key: await encryptBytesWithAesGcm(key, master), encrypted_title: await encryptWithAesGcmCombined('Previous account', key) };
  Object.assign(client, { http: { post: async () => { changeAccount(); return { ok: true, data: { chats: [row] } }; } } });
  await assert.rejects(client.getSidebarChats(['normal']), /workspace changed/);
});

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running
test('activity census cannot cross accounts before metadata hydration starts', async () => {
  const { client, changeAccount } = fixture();
  let hydrated = false;
  Object.assign(client, { http: { get: async () => {
    changeAccount(); return { ok: true, data: { active_tasks: [{ chat_id: 'previous-chat' }], chats: [{ chat_id: 'previous-chat' }] } };
  } }, getSidebarChats: async () => { hydrated = true; return []; } });
  await assert.rejects(client.getChatActivity(), /workspace changed/);
  assert.equal(hydrated, false);
});

// contract-test: supporting surface=cli assertions=chat-navigation.draft-only.addressable,chat-navigation.order.sidebar-header-match
test('saved keyless drafts retain their preview and ordering metadata without revealing locked chats', async () => {
  const {client, master} = fixture(), key = Buffer.alloc(32, 3);
  const draft = await encryptWithAesGcmCombined('Plan the release', master);
  Object.assign(client, {ensureSynced: async () => ({chats: [
    {details: {id: 'draft', encrypted_draft_md: draft, encrypted_draft_preview: draft, pinned: true, last_edited_overall_timestamp: 100}, messages: []},
    {details: {id: 'locked', encrypted_chat_key: await encryptBytesWithAesGcm(key, Buffer.alloc(32, 9)), encrypted_draft_md: draft, encrypted_draft_preview: draft}, messages: []},
    {details: {id: 'empty'}, messages: []},
  ]})});
  const {chats} = await client.listChats();
  assert.equal(chats[0].isHiddenCandidate, false); assert.equal(chats[0].draftPreview, 'Plan the release');
  assert.equal(chats[0].hasDraft, true); assert.equal(chats[0].pinned, true); assert.equal(chats[0].updatedAt, 100);
  assert.equal(chats[1].isHiddenCandidate, true); assert.equal(chats[1].draftPreview, null);
  assert.equal(chats[2].isHiddenCandidate, true);
});

// contract-test: supporting surface=cli assertions=chat-navigation.projects.nested-readable,chat-navigation.order.sidebar-header-match
test('linked metadata uses message time rather than a later metadata edit', async () => {
  const {client, master} = fixture(), key = Buffer.alloc(32, 3);
  Object.assign(client, {http: {post: async () => ({ok: true, data: {chats: [{id:'linked',
    encrypted_chat_key: await encryptBytesWithAesGcm(key,master), updated_at:'1700000300', last_message_at:'1700000100', pinned:true}]}})}});
  const [chat] = await client.getSidebarChats(['linked']);
  assert.equal(chat.updatedAt,1700000100); assert.equal(chat.pinned,true); assert.equal(chat.metadataUpdatedAt,1700000300);
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent
test('a list response cannot publish after the account changes while syncing', async () => {
  const {client,changeAccount} = fixture();
  Object.assign(client,{ensureSynced:async()=>{changeAccount();return {chats:[]};}});
  await assert.rejects(client.listChats(),/workspace changed/);
});

// contract-test: supporting surface=cli assertions=chat-navigation.draft-only.addressable,chat-navigation.open.local-first-coherent
test('saving a draft before the first list still syncs the complete chat census', async () => {
  const previousStateDir = process.env.OPENMATES_STATE_DIR;
  const stateDir = mkdtempSync(join(tmpdir(), 'openmates-sidebar-draft-'));
  process.env.OPENMATES_STATE_DIR = stateDir;
  try {
    const { client, master } = fixture(), key = Buffer.alloc(32, 3);
    let connections = 0;
    const serverChat = { id: 'server-chat', encrypted_chat_key: await encryptBytesWithAesGcm(key, master),
      encrypted_title: await encryptWithAesGcmCombined('Existing conversation', key) };
    Object.assign(client, {
      openWsClient: async () => { connections++; return { ws: {
        waitForMessage: async () => ({ payload: { chat_id: 'draft', draft_v: 1 } }),
        sendAsync: async () => {}, send: () => {}, close: () => {},
        collectMessages: async () => [{ type: 'phase_2_last_20_chats_ready', payload: {
          chats: [{ chat_details: serverChat }], total_chat_count: 2,
        } }], drainPassiveTaskUpdateJobs: () => [],
      } }; },
      persistPendingAIResponsesFromSync: async () => {},
      persistPendingTaskUpdateJobs: async () => new Set(),
    });
    await client.saveDraft({ chatId: 'draft', markdown: 'Finish the release' });
    const { chats } = await client.listChats();
    assert.equal(connections, 2, 'The draft connection cannot substitute for the full sync');
    assert.deepEqual(new Set(chats.map(chat => chat.id)), new Set(['draft', 'server-chat']));
    assert.equal(chats.find(chat => chat.id === 'server-chat')?.title, 'Existing conversation');
  } finally {
    if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = previousStateDir;
    rmSync(stateDir, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent
test('editing a draft does not extend the freshness of an existing chat census', async () => {
  const previousStateDir = process.env.OPENMATES_STATE_DIR;
  const stateDir = mkdtempSync(join(tmpdir(), 'openmates-sidebar-freshness-'));
  process.env.OPENMATES_STATE_DIR = stateDir;
  try {
    const { client } = fixture();
    const syncedAt = Date.now() - 600_000;
    saveSyncCache({ syncedAt, totalChatCount: 1, loadedChatCount: 1,
      chats: [{ details: { id: 'existing' }, messages: [] }], embeds: [], embedKeys: [] });
    Object.assign(client, { openWsClient: async () => ({ ws: {
      waitForMessage: async () => ({ payload: { chat_id: 'existing', draft_v: 2 } }),
      sendAsync: async () => {}, close: () => {},
    } }) });
    await client.saveDraft({ chatId: 'existing', markdown: 'Updated plan' });
    assert.equal(loadSyncCache()?.syncedAt, syncedAt);
    Object.assign(client, { openWsClient: async () => { throw new Error('full census sync requested'); } });
    await assert.rejects(client.listChats(), /full census sync requested/);
  } finally {
    if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = previousStateDir;
    rmSync(stateDir, { recursive: true, force: true });
  }
});
