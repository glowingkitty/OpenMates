import { it } from 'node:test';
import assert from 'node:assert/strict';
import { OpenMatesClient } from '../src/client.ts';
import { encryptWithAesGcmCombined, decryptWithAesGcmCombined } from '../src/crypto.ts';
import { prepareCliJevContext } from '../src/cliJevContext.ts';

const key = new Uint8Array(32).fill(9);
const guide = '---\ntitle: Project preference\ndescription: Personal context about a project.\nwhen_to_use: Discussing the project.\n---\nKeep private notes private.\n';
async function fixture() {
  const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
  const settings = { topic_preferences: { version: 1 }, rule_documents: [{id: 'personal:legacy', document: guide}],
    memory_documents: [{id: 'personal:legacy', document: guide + 'Current private preference.\n'}] };
  const user = { id: 'owner', encrypted_settings: await encryptWithAesGcmCombined(JSON.stringify(settings), key) };
  const writes: Array<Record<string, unknown>> = [];
  Object.assign(client, { getMasterKeyBytes: () => key, resolveTeamContext: () => null,
    requireSession: () => ({sessionId: 'owner-session'}), whoAmI: async () => user,
    sdkGetPersonalMemories: async () => [], settingsPost: async (path: string, body: Record<string, unknown>) => {
      assert.equal(path, '/v1/settings/encrypted-account'); writes.push(body);
    },
  });
  return { client, user, writes, settings };
}

// contract-test: supporting surface=sdks.npm assertions=app-memories.compatibility.legacy-documents,app-memories.privacy.client-encrypted
it('merges account Memory aliases once and edits/deletes in the encrypted owner store', async () => {
  const {client, writes} = await fixture();
  const entries = await client.listMemories({personal: true});
  assert.equal(entries.length, 1);
  assert.equal(entries[0].id, 'account-memory-legacy');
  assert.equal(entries[0].app_id, 'openmates');
  assert.ok(String(entries[0].data.document).includes('Current private preference.'));
  await client.updateMemory({entryId: entries[0].id, appId: 'openmates', itemType: 'memories',
    itemValue: {title: 'Updated preference', document: guide}, currentVersion: 1, personal: true});
  assert.deepEqual(Object.keys(writes[0]), ['encrypted_settings']);
  const saved = JSON.parse((await decryptWithAesGcmCombined(String(writes[0].encrypted_settings), key))!);
  assert.deepEqual(saved.topic_preferences, {version: 1});
  assert.equal(saved.rule_documents[0].document, guide);
  assert.ok(saved.memory_documents[0].document.includes('Updated preference'));
  await client.deleteMemory(entries[0].id, {personal: true});
  const deleted = JSON.parse((await decryptWithAesGcmCombined(String(writes[1].encrypted_settings), key))!);
  assert.deepEqual(deleted.rule_documents, []);
  assert.deepEqual(deleted.memory_documents, []);
});

// contract-test: supporting surface=sdks.npm assertions=app-memories.access.owner-scoped
it('rejects an account Memory edit when its encrypted source changes', async () => {
  const {client, user, writes} = await fixture();
  let reads = 0;
  Object.assign(client, {whoAmI: async () => ++reads === 1 ? user : {...user, encrypted_settings: 'changed'} });
  await assert.rejects(client.updateMemory({entryId: 'account-memory-legacy', appId: 'openmates', itemType: 'memories',
    itemValue: {title: 'Updated', document: guide}, currentVersion: 1, personal: true}), /settings changed/);
  assert.equal(writes.length, 0);
});

// contract-test: supporting surface=cli assertions=app-memories.conversation.explicit-approval,app-memories.selection.source-scoped
it('never decrypts or advertises personal guide bodies in automatic Jev context', async () => {
  const {client} = await fixture();
  let privateReads = 0;
  Object.assign(client, {getCustomRuleDocuments: async () => {privateReads += 1; return [];},
    listProjects: async () => [], listUserTasks: async () => [], getActiveProjectFocus: async () => null});
  const context = await prepareCliJevContext(client, 'chat', {}, {custom_memory_documents: [{id: 'personal:legacy', source: 'personal', document: guide}]}, 'Project');
  assert.equal(privateReads, 0);
  assert.deepEqual(context.custom_memory_documents, []);
  assert.equal(JSON.stringify(context).includes('Keep private notes private'), false);
});
