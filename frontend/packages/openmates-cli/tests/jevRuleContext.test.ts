/** Actual client crypto plus bounded transport doubles; no provider or account state. */
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { encryptWithAesGcmCombined, decryptWithAesGcmCombined } from '../src/crypto.ts';
import { loadActiveCliProjectContext } from '../src/cliJevContext.ts';
import { chatContextDetails, parseChatContextEvent, registerChatContextEvents } from '../src/chatContextEvents.ts';
import type { OpenMatesClient } from '../src/client.ts';
import type { OpenMatesWsClient } from '../src/ws.ts';

const key = new Uint8Array(32).fill(7);
const document = '---\ntitle: Private Python practices\ndescription: Reliable services.\nwhen_to_use: Writing Python.\n---\n- Release resources.\n- Preserve cancellation.\n';

// contract-test: supporting surface=cli assertions=rules.ownership.encrypted-custom,rules.selection.focus-aware
it('does not decrypt Project definitions before activation and drops revoked results', async () => {
  let active: { project_id: string; focus_id: string; team_id: null } | null = null;
  let projectReads = 0;
  let bodyReads = 0;
  const ruleItem = { project_item_id: 'private-rule-id', item_type: 'embed',
    encrypted_metadata: await encryptWithAesGcmCombined(JSON.stringify({ path: '.openmates/rules/guide.md', title: 'Private Python practices', description: 'Reliable services.' }), key),
    target_id_encrypted: await encryptWithAesGcmCombined('embed-id', key) };
  const client = {
    getActiveProjectFocus: async () => active,
    getProject: async () => { projectReads += 1; return { project: {}, items: [ruleItem], folders: [] }; },
    decryptProjectKey: async () => key,
    selectProjectContext: async (_projectId: string, request: { candidates: Array<{ id: string; kind: string; revision: string }> }) => {
      assert.equal(JSON.stringify(request).includes('Release resources'), false);
      return request.candidates;
    },
    readEncryptedProjectFile: async () => { bodyReads += 1; active = null; return { content: { code: document }, revision: 1 }; },
  } as unknown as OpenMatesClient;
  assert.deepEqual(await loadActiveCliProjectContext(client, 'chat-id', 'Write Python'), {});
  assert.equal(projectReads, 0);
  assert.equal(bodyReads, 0);
  active = { project_id: 'project-id', focus_id: 'focus-id', team_id: null };
  assert.deepEqual(await loadActiveCliProjectContext(client, 'chat-id', 'Write Python'), {});
  assert.equal(bodyReads, 1);
});

// contract-test: supporting surface=cli assertions=rules.transparency.applied-set,rules.definition.guide-format
it('counts a multi-practice Rule once and persists the exact applied receipt as ciphertext once', async () => {
  const body = '- Release resources.\n- Preserve cancellation.';
  const event = { event_id: 'rule-event-1', created_at: 1, chat_id: 'chat-id',
    type: 'rules_loaded', count: 1, set_key: 'a'.repeat(64), rules: [
      { id: 'private-rule-id', title: 'Private Python practices', source: 'project', project_id: 'project-id', revision: 'b'.repeat(64), body },
    ] };
  const parsed = parseChatContextEvent(event, 'chat-id');
  assert.ok(parsed);
  assert.deepEqual(chatContextDetails(parsed).slice(3, 5), body.split('\n'));
  assert.equal(parseChatContextEvent({ ...event, count: 2 }, 'chat-id'), null);
  const messages: Array<Record<string, unknown>> = [];
  const ws = {
    onMessageType: () => () => undefined,
    sendAsync: async (_type: string, payload: Record<string, unknown>) => { messages.push(payload); },
  } as unknown as OpenMatesWsClient;
  const listener = registerChatContextEvents({ ws, chatId: 'chat-id', chatKey: key, existingMessageIds: [] });
  listener.persist(parsed);
  listener.persist(parsed);
  await listener.flush();
  assert.equal(messages.length, 1);
  const stored = messages[0].message as Record<string, unknown>;
  assert.equal(stored.content, undefined);
  assert.equal(String(stored.encrypted_content).includes('Release resources'), false);
  const plaintext = await decryptWithAesGcmCombined(String(stored.encrypted_content), key);
  assert.deepEqual(JSON.parse(plaintext!), event);
  listener.stop();
});
