import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { generateIdentity, openDirectChatKey } from '@repo/pairing-crypto/direct-chat';
import { OpenMates } from '../src/sdk.js';

describe('npm SDK Team direct-chat creation', () => {
  // contract-test: direct surface=sdks.npm assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
  it('enrolls the own key and wraps one chat key independently for both participants', async () => {
    const ownUserId = '11111111-1111-4111-8111-111111111111';
    const ownHash = createHash('sha256').update(ownUserId).digest('hex');
    const recipientHash = 'b'.repeat(64);
    const recipient = await generateIdentity();
    const master = new Uint8Array(randomBytes(32));
    const sdk = new OpenMates({ apiKey: 'sk-api-test', apiUrl: 'https://example.invalid', deviceId: 'test-device' });
    const client = sdk as unknown as Record<string, unknown>;
    client.masterKey = async () => master;
    client.sdkSession = async () => ({ user: { id: ownUserId } });
    let accountKey: Record<string, unknown> | null = null;
    let chat: Record<string, unknown> | null = null;
    let createCount = 0;
    client.get = async (path: string) => {
      if (path === '/v1/account/chat-encryption-key') return { key: accountKey };
      if (path.endsWith(`/members/${recipientHash}/chat-encryption-key`)) return { key_id: recipient.keyId, public_key: recipient.publicKey };
      throw new Error(`Unexpected GET ${path}`);
    };
    client.put = async (path: string, body: Record<string, unknown>) => {
      assert.equal(path, '/v1/account/chat-encryption-key'); accountKey = body; return { key: body };
    };
    client.request = async (path: string, body: Record<string, unknown>) => {
      assert.equal(path, '/v1/teams/team-one/direct-chats');
      createCount++;
      assert.equal(body.recipient_user_hash, recipientHash);
      const envelopes = body.participant_key_envelopes as Record<string, { key_id: string; encrypted_chat_key: string }>;
      assert.deepEqual(Object.keys(envelopes).sort(), [ownHash, recipientHash].sort());
      const ownIdentity = await sdk.chatIdentity();
      const ownKey = await openDirectChatKey(envelopes[ownHash].encrypted_chat_key,
        { teamId: 'team-one', chatId: String(body.chat_id), recipientHash: ownHash, keyId: ownIdentity.keyId }, ownIdentity.privateKey);
      const recipientKey = await openDirectChatKey(envelopes[recipientHash].encrypted_chat_key,
        { teamId: 'team-one', chatId: String(body.chat_id), recipientHash, keyId: recipient.keyId }, recipient.privateKey);
      assert.deepEqual(ownKey, recipientKey);
      chat = { id: body.chat_id, team_id: 'team-one', chat_visibility: 'direct', participant_user_hashes: [ownHash, recipientHash],
        encrypted_chat_key: envelopes[ownHash].encrypted_chat_key, encrypted_title: body.encrypted_title };
      return { chat };
    };
    const first = await sdk.teams.openDirectChat('team-one', recipientHash);
    assert.equal(first.chat_visibility, 'direct');
    assert.equal(createCount, 1);
    assert.equal(accountKey?.algorithm, 'x25519-xsalsa20poly1305');
  });
});


describe('npm SDK private creation response binding', () => {
  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,teams.direct-chat.participant-isolation
  it('rejects wrong visibility, Team, chat ID and participant pair before any decryption', async () => {
    const ownUserId = '11111111-1111-4111-8111-111111111111';
    const ownHash = createHash('sha256').update(ownUserId).digest('hex');
    const recipientHash = 'b'.repeat(64);
    const own = await generateIdentity();
    const recipient = await generateIdentity();
    const mismatches: Array<Record<string, unknown>> = [
      { chat_visibility: 'team' }, { team_id: 'team-two' }, { id: 'wrong-chat' },
      { participant_user_hashes: [ownHash, 'c'.repeat(64)] },
    ];
    for (const mismatch of mismatches) {
      const sdk = new OpenMates({ apiKey: 'sk-api-test', apiUrl: 'https://example.invalid', deviceId: 'test-device' });
      const client = sdk as unknown as Record<string, unknown>;
      client.sdkSession = async () => ({ user: { id: ownUserId } });
      client.chatIdentity = async () => own;
      client.get = async () => ({ key_id: recipient.keyId, public_key: recipient.publicKey });
      client.request = async (_path: string, body: Record<string, unknown>) => ({ chat: {
        id: body.chat_id, team_id: 'team-one', chat_visibility: 'direct',
        participant_user_hashes: [ownHash, recipientHash], ...mismatch,
      } });
      let decryptions = 0;
      client.decryptChatMetadata = async () => { decryptions++; throw new Error('Unexpected private metadata decryption'); };
      await assert.rejects(sdk.teams.openDirectChat('team-one', recipientHash), /mismatched metadata/);
      assert.equal(decryptions, 0);
    }
  });
});
