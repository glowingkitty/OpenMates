import { webcrypto } from 'node:crypto';
import { beforeAll, describe, expect, it } from 'vitest';
import { hashEmail } from '../cryptoService';
import { decryptWithMasterKeyDirect, encryptWithMasterKeyDirect } from '../encryption/MetadataEncryptor';
import { resolvePairEmailEnvelope, type PairAccountCheck } from '../pairV2';

beforeAll(() => {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
  Object.defineProperty(globalThis, 'window', {
    value: { btoa: globalThis.btoa, atob: globalThis.atob }, configurable: true,
  });
});

const email = 'pair@example.test';

async function account(encryptedEmail: string | null): Promise<PairAccountCheck> {
  return { user_id: 'user-1', user_email_salt: 'server-salt',
    hashed_email: await hashEmail(email), encrypted_email_with_master_key: encryptedEmail };
}

describe('pairing account email envelope', () => {
  // contract-test: supporting surface=gui.web assertions=auth.pair-login.single-use-zk
  it('binds a legacy local email to the server hash before wrapping it for the receiver', async () => {
    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
    const envelope = await resolvePairEmailEnvelope(await account(null), key, email);
    expect(await decryptWithMasterKeyDirect(envelope, key)).toBe(email);
    await expect(resolvePairEmailEnvelope(await account(null), key, 'other@example.test'))
      .rejects.toThrow('Pairing master key mismatch');
  });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.single-use-zk
  it('fails closed when a present server envelope is invalid, even if local metadata matches', async () => {
    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
    const otherKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
    const wrongEnvelope = await encryptWithMasterKeyDirect(email, otherKey);
    expect(wrongEnvelope).not.toBeNull();
    await expect(resolvePairEmailEnvelope(await account(wrongEnvelope), key, email))
      .rejects.toThrow('Pairing master key mismatch');
  });
});
