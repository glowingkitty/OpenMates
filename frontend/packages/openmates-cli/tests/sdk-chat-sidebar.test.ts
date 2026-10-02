// Minimal sidebar metadata preserves hidden-key privacy without loading transcripts.
// These tests exercise real encryption/decoding and publication fences locally.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { OpenMatesClient } from '../src/client.js';
import { encryptBytesWithAesGcm, encryptWithAesGcmCombined } from '../src/crypto.js';

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
