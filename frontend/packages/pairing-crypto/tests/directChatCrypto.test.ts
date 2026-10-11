import { describe, expect, it } from 'vitest';
import {
  directChatBase64Url, generateIdentity, openDirectChatKey, sealDirectChatKey,
} from '../src/directChatCrypto.js';

describe('OMDM1 direct-chat envelopes', () => {
  // contract-test: direct surface=sdks.npm assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
  it('round trips the same key across independent recipient identities and binds each envelope', async () => {
    const alice = await generateIdentity();
    const bob = await generateIdentity();
    const chatKey = crypto.getRandomValues(new Uint8Array(32));
    const aliceBinding = { teamId: 'team-one', chatId: 'chat-one', recipientHash: 'a'.repeat(64), keyId: alice.keyId };
    const bobBinding = { ...aliceBinding, recipientHash: 'b'.repeat(64), keyId: bob.keyId };
    const aliceEnvelope = await sealDirectChatKey(chatKey, aliceBinding, alice.publicKey);
    const bobEnvelope = await sealDirectChatKey(chatKey, bobBinding, bob.publicKey);
    expect(aliceEnvelope).toMatch(/^OMDM1\.[A-Za-z0-9_-]+$/);
    expect(bobEnvelope).toMatch(/^OMDM1\.[A-Za-z0-9_-]+$/);
    expect(openDirectChatKey(aliceEnvelope, aliceBinding, alice.privateKey)).resolves.toEqual(chatKey);
    expect(openDirectChatKey(bobEnvelope, bobBinding, bob.privateKey)).resolves.toEqual(chatKey);
    await expect(openDirectChatKey(bobEnvelope, aliceBinding, alice.privateKey)).rejects.toThrow();
    await expect(openDirectChatKey(aliceEnvelope, { ...aliceBinding, chatId: 'other-chat' }, alice.privateKey)).rejects.toThrow(/binding/);
    await expect(openDirectChatKey(aliceEnvelope, { ...aliceBinding, teamId: 'other-team' }, alice.privateKey)).rejects.toThrow(/binding/);
  });

  // contract-test: direct surface=sdks.npm assertions=teams.direct-chat.account-key-exchange
  it('rejects malformed envelopes, weak public keys and invalid chat keys', async () => {
    const alice = await generateIdentity();
    const binding = { teamId: 'team-one', chatId: 'chat-one', recipientHash: 'a'.repeat(64), keyId: alice.keyId };
    await expect(sealDirectChatKey(new Uint8Array(32), binding, alice.publicKey)).rejects.toThrow(/chat key/);
    await expect(openDirectChatKey('OMDM1.abc=', binding, alice.privateKey)).rejects.toThrow(/envelope/);
    await expect(openDirectChatKey('OMDM1.' + 'x'.repeat(3000), binding, alice.privateKey)).rejects.toThrow(/envelope/);
    const weakPublicKey = directChatBase64Url(new Uint8Array(32));
    await expect(sealDirectChatKey(crypto.getRandomValues(new Uint8Array(32)), binding, weakPublicKey)).rejects.toThrow(/public key/);
  });
});
