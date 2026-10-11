/**
 * CLI account identity backup for Team direct chats.
 * The private X25519 key is encrypted with the existing master-key AES-GCM
 * combined format, making the backup readable by web and CLI clients.
 * Public key IDs are verified before use; restored private keys must match.
 */
import { directChatBase64Url, directChatBase64UrlBytes, directChatKeyId, generateIdentity, type DirectChatKeyPair } from '@repo/pairing-crypto/direct-chat';
import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from './crypto.js';

export interface AccountChatEncryptionKey {
  version: 1;
  algorithm: 'x25519-xsalsa20poly1305';
  key_id: string;
  public_key: string;
  encrypted_private_key: string;
}

export interface PublicChatEncryptionKey {
  key_id: string;
  public_key: string;
}

export function validatePublicChatEncryptionKey(value: unknown): PublicChatEncryptionKey {
  const row = value as Partial<PublicChatEncryptionKey> | null;
  if (!row || typeof row.public_key !== 'string' || typeof row.key_id !== 'string' || !/^[0-9a-f]{64}$/.test(row.key_id)) {
    throw new Error('Invalid member chat encryption key');
  }
  directChatBase64UrlBytes(row.public_key, 32, 'public key');
  return { key_id: row.key_id, public_key: row.public_key };
}

export async function validatePublicChatEncryptionKeyId(value: unknown): Promise<PublicChatEncryptionKey> {
  const key = validatePublicChatEncryptionKey(value);
  if (await directChatKeyId(key.public_key) !== key.key_id) throw new Error('Member chat encryption key ID mismatch');
  return key;
}

export async function recoverAccountChatIdentity(record: AccountChatEncryptionKey, masterKey: Uint8Array): Promise<DirectChatKeyPair> {
  if (record.version !== 1 || record.algorithm !== 'x25519-xsalsa20poly1305') throw new Error('Unsupported account chat encryption key');
  const publicKey = await validatePublicChatEncryptionKeyId(record);
  if (typeof record.encrypted_private_key !== 'string' || record.encrypted_private_key.length > 2048) throw new Error('Invalid account chat private key backup');
  const encoded = record.encrypted_private_key;
  if (!/^[A-Za-z0-9+/_-]+={0,2}$/.test(encoded)) throw new Error('Invalid account chat private key backup');
  const privateKey = await decryptWithAesGcmCombined(Buffer.from(encoded, 'base64url').toString('base64'), masterKey);
  if (!privateKey) throw new Error('Could not decrypt account chat private key');
  const secret = directChatBase64UrlBytes(privateKey, 32, 'private key');
  if (secret.every(byte => byte === 0)) throw new Error('Invalid account chat private key');
  const nacl = (await import('tweetnacl')).default;
  if (directChatBase64Url(nacl.scalarMult.base(secret)) !== publicKey.public_key) throw new Error('Account chat key pair mismatch');
  return { publicKey: publicKey.public_key, privateKey, keyId: publicKey.key_id };
}

export async function createAccountChatIdentity(masterKey: Uint8Array): Promise<{ identity: DirectChatKeyPair; record: AccountChatEncryptionKey }> {
  const identity = await generateIdentity();
  const backup = await encryptWithAesGcmCombined(identity.privateKey, masterKey);
  return { identity, record: {
    version: 1, algorithm: 'x25519-xsalsa20poly1305', key_id: identity.keyId,
    public_key: identity.publicKey,
    encrypted_private_key: Buffer.from(backup, 'base64').toString('base64url'),
  } };
}
