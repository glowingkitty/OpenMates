import test from 'node:test';
import assert from 'node:assert/strict';

import { readHotMessageWindow, readHotMessageTimeline } from '../src/hot-message-window.js';

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.access-and-lifecycle
test('timeline projection keeps tied-ID keyset reads content-free and bounded', async () => {
  const source = { id: 'legacy-row', client_message_id: null, chat_id: 'chat-1', created_at: 42,
    role: 'assistant', user_message_id: 'question-1', encrypted_content: 'must-not-read',
    hashed_user_id: 'private-owner', encrypted_sender_name: 'private-name' };
  const trx = { raw: async (sql, bindings) => {
    assert.deepEqual(bindings, ['chat-1', 42, 'question-2', 201]);
    assert.match(sql, /COALESCE\(NULLIF\(client_message_id, ''\), id::text\) COLLATE "C"\) < \(\?, \?::text COLLATE "C"\)/);
    const fields = sql.match(/^SELECT ([\s\S]+?) FROM messages/)[1].split(', ');
    return { rows: [Object.fromEntries(fields.map(field => [field, source[field]]))] };
  } };
  const result = await readHotMessageTimeline(trx, { chat_id: 'chat-1', direction: 'before',
    cursor_timestamp: 42, cursor_message_id: 'question-2', limit: 201 });
  assert.deepEqual(result.messages, [{ id: source.id, client_message_id: null, chat_id: 'chat-1',
    created_at: 42, role: 'assistant', user_message_id: 'question-1' }]);
  await assert.rejects(readHotMessageTimeline(trx, { chat_id: 'chat-1', direction: 'latest', limit: 202 }),
    /invalid_hot_message_window/);
  await assert.rejects(readHotMessageWindow(trx, { chat_id: 'chat-1', direction: 'latest', limit: 102 }),
    /invalid_hot_message_window/);
});

// contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.lifecycle.recovery-and-billing,chats.persistence.client-encrypted
test('hot message query retains zero and confirmed revisions for monotonic history hydration', async () => {
  for (const revision of [0, 3]) {
    const source = { id: 'row-1', client_message_id: 'message-1', chat_id: 'personal-chat',
      encrypted_content: 'ciphertext', role: 'user', created_at: 42, queue_revision: revision };
    const trx = { raw: async (sql, bindings) => {
      assert.deepEqual(bindings, ['personal-chat', 10]);
      const fields = sql.match(/^SELECT ([\s\S]+?) FROM messages/)[1].split(', ');
      // Apply the actual generated SELECT projection; returning the whole
      // fixture row would hide a missing server-side metadata column.
      return { rows: [Object.fromEntries(fields.map(field => [field, source[field] ?? null]))] };
    } };
    const result = await readHotMessageWindow(trx, {
      chat_id: 'personal-chat', direction: 'latest', limit: 10,
    });
    assert.equal(result.messages[0].queue_revision, revision);
    assert.equal(typeof result.messages[0].queue_revision, 'number');
    assert.equal(result.messages[0].encrypted_content, source.encrypted_content);
  }
});

// contract-test: direct surface=rest_api assertions=teams.chat.sender-identity-layout
test('hot message window selects encrypted sender identity for Team history', async () => {
  const source = {
    id: 'row-1', client_message_id: 'message-1', chat_id: 'team-chat',
    encrypted_content: 'ciphertext', role: 'user',
    hashed_user_id: 'a'.repeat(64), encrypted_sender_name: 'encrypted-name',
    created_at: 42,
  };
  let calls = 0;
  const trx = { raw: async (sql, bindings) => {
    calls += 1;
    assert.match(sql, /FROM messages\s+WHERE chat_id = \?/);
    assert.deepEqual(bindings, ['team-chat', 10]);
    const fields = sql.match(/^SELECT ([\s\S]+?) FROM messages/)[1].split(', ');
    return { rows: [Object.fromEntries(fields.map(field => [field, source[field] ?? null]))] };
  } };

  const result = await readHotMessageWindow(trx, {
    chat_id: 'team-chat', direction: 'latest', limit: 10,
  });
  assert.equal(calls, 1);
  assert.equal(result.messages[0].hashed_user_id, source.hashed_user_id);
  assert.equal(result.messages[0].encrypted_sender_name, source.encrypted_sender_name);
  assert.equal(result.messages[0].encrypted_content, source.encrypted_content);
});
