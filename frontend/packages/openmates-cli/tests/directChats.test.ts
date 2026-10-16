import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes, webcrypto } from 'node:crypto';
import { createAccountChatIdentity, recoverAccountChatIdentity } from '../src/directChats.js';
import { directChatBase64Url } from '@repo/pairing-crypto/direct-chat';

describe('direct chat identity backup', () => {
  // contract-test: direct surface=sdks.npm assertions=teams.direct-chat.account-key-exchange
  it('opens the browser combined AES-GCM bytes and publishes the same private key format', async () => {
    const master = new Uint8Array(randomBytes(32));
    const { identity, record } = await createAccountChatIdentity(master);
    assert.match(record.encrypted_private_key, /^[A-Za-z0-9_-]+$/);
    const combined = new Uint8Array(Buffer.from(record.encrypted_private_key, 'base64url'));
    const aes = await webcrypto.subtle.importKey('raw', new Uint8Array(master), 'AES-GCM', false, ['decrypt', 'encrypt']);
    const opened = await webcrypto.subtle.decrypt({ name: 'AES-GCM', iv: combined.slice(0, 12) }, aes, combined.slice(12));
    assert.equal(new TextDecoder().decode(opened), identity.privateKey);
    const iv = new Uint8Array(randomBytes(12));
    const browserCiphertext = new Uint8Array(await webcrypto.subtle.encrypt({ name: 'AES-GCM', iv }, aes, new TextEncoder().encode(identity.privateKey)));
    const browserCombined = new Uint8Array(iv.length + browserCiphertext.length);
    browserCombined.set(iv); browserCombined.set(browserCiphertext, iv.length);
    const browserRecord = { ...record, encrypted_private_key: directChatBase64Url(browserCombined) };
    assert.deepEqual(await recoverAccountChatIdentity(browserRecord, master), identity);
    assert.deepEqual(await recoverAccountChatIdentity({ ...browserRecord, encrypted_private_key: Buffer.from(browserCombined).toString('base64') }, master), identity);
    await assert.rejects(recoverAccountChatIdentity(browserRecord, new Uint8Array(randomBytes(32))), /decrypt/);
  });
});
