import test from 'node:test';
import assert from 'node:assert/strict';

import { readHotMessageWindow } from '../src/hot-message-window.js';

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
