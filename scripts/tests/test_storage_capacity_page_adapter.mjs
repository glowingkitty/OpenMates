import assert from 'node:assert/strict';
import { test } from 'node:test';

import { readArchivedPage } from '../storage_capacity_page_adapter.mjs';

test('archived page requires exact decrypted user plaintext from the sent ledger', async () => {
  const expectedUserMessages = new Set(['original encrypted message plaintext']);
  const client = { getChatMessagesWindow: async () => ({
    messages: [{ role: 'user', content: 'different nonempty plaintext' }],
    archivePageIds: ['archive-ledger-mismatch'], storageTier: 'archive',
    archivePayloadCache: 'disabled',
  }) };
  const result = await readArchivedPage({ client, chatId: 'disposable-chat', expectedUserMessages });
  assert.equal(result.archived, true);
  assert.equal(result.decrypted, false);
  assert.equal(result.cache, 'cold');
});

test('archived page accepts exact decrypted user plaintext', async () => {
  const plaintext = 'original encrypted message plaintext';
  const client = { getChatMessagesWindow: async () => ({
    messages: [{ role: 'user', content: plaintext }],
    archivePageIds: ['archive-ledger-match'], storageTier: 'archive',
    archivePayloadCache: 'disabled',
  }) };
  const result = await readArchivedPage({
    client, chatId: 'disposable-chat', expectedUserMessages: new Set([plaintext]),
  });
  assert.equal(result.archived, true);
  assert.equal(result.decrypted, true);
  assert.deepEqual(result.archivePageIds, ['archive-ledger-match']);
});

test('mixed hot and archive window does not claim archived plaintext proof', async () => {
  const client = { getChatMessagesWindow: async () => ({
    messages: [{ role: 'user', content: 'hot matching plaintext' }],
    archivePageIds: ['archive-mixed-hot-user'], storageTier: 'mixed',
    hasMoreBefore: false,
  }) };
  const result = await readArchivedPage({
    client, chatId: 'disposable-chat', expectedUserMessages: new Set(['hot matching plaintext']),
  });
  assert.equal(result.archived, false);
});
