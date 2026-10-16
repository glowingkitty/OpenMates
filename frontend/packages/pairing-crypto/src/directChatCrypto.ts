/**
 * Browser and Node wire format for Team direct-chat key envelopes.
 * A fresh ephemeral X25519 key and nonce wrap each immutable chat key.
 * The authenticated payload binds the Team, chat, recipient, and key ID.
 * Keys and wire fields use canonical base64url so both clients agree on bytes.
 * Keep this module free of Node imports for use by web and CLI clients.
 */
import nacl from 'tweetnacl';

const PREFIX = 'OMDM1.';
const MAX_ENVELOPE_LENGTH = 2048;
const MAX_PAYLOAD_BYTES = 768;
const BASE64URL = /^[A-Za-z0-9_-]+$/;
const KEY_ID = /^[0-9a-f]{64}$/;
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });

export interface DirectChatIdentity {
  teamId: string;
  chatId: string;
  recipientHash: string;
  keyId: string;
}

export interface DirectChatKeyPair {
  publicKey: string;
  privateKey: string;
  keyId: string;
}

function ownedBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.length);
  copy.set(bytes);
  return copy.buffer;
}

export function directChatBase64Url(bytes: Uint8Array): string {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

export function directChatBase64UrlBytes(value: string, length: number | undefined, field = 'key', maxLength = length ?? MAX_PAYLOAD_BYTES): Uint8Array {
  if (typeof value !== 'string' || value.length < 1 || value.length > Math.ceil(maxLength * 4 / 3) + 2 || !BASE64URL.test(value)) {
    throw new Error(`Invalid direct-chat ${field}`);
  }
  let decoded: Uint8Array;
  try {
    const binary = atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4));
    decoded = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch { throw new Error(`Invalid direct-chat ${field}`); }
  if ((length !== undefined && decoded.length !== length) || decoded.length > maxLength || directChatBase64Url(decoded) !== value) throw new Error(`Invalid direct-chat ${field}`);
  return decoded;
}

function boundedIdentity(identity: DirectChatIdentity): void {
  if (!identity || typeof identity !== 'object') throw new Error('Invalid direct-chat identity');
  for (const value of [identity.teamId, identity.chatId, identity.recipientHash]) {
    if (typeof value !== 'string' || value.length < 1 || value.length > 128 || !/^[A-Za-z0-9_-]+$/.test(value)) {
      throw new Error('Invalid direct-chat identity');
    }
  }
  if (!KEY_ID.test(identity.keyId)) throw new Error('Invalid direct-chat key ID');
}

function validNonzeroKey(value: Uint8Array, field: string): void {
  if (value.length !== 32 || value.every((byte) => byte === 0)) throw new Error(`Invalid direct-chat ${field}`);
}

function validatePublicKey(value: string): Uint8Array {
  const bytes = directChatBase64UrlBytes(value, 32, 'public key');
  validNonzeroKey(bytes, 'public key');
  // NaCl's curve implementation accepts small-order points; refuse those before boxing.
  const probe = nacl.scalarMult(new Uint8Array(32).fill(7), bytes);
  if (probe.every((byte) => byte === 0)) throw new Error('Invalid direct-chat public key');
  return bytes;
}

export async function directChatKeyId(publicKey: string): Promise<string> {
  const bytes = validatePublicKey(publicKey);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', ownedBuffer(bytes)));
  return [...digest].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function generateIdentity(): Promise<DirectChatKeyPair> {
  const pair = nacl.box.keyPair();
  const publicKey = directChatBase64Url(pair.publicKey);
  return { publicKey, privateKey: directChatBase64Url(pair.secretKey), keyId: await directChatKeyId(publicKey) };
}

export async function sealDirectChatKey(
  rawKey: Uint8Array,
  identity: DirectChatIdentity,
  recipientPublicKey: string,
): Promise<string> {
  boundedIdentity(identity);
  validNonzeroKey(rawKey, 'chat key');
  const recipient = validatePublicKey(recipientPublicKey);
  if (identity.keyId !== await directChatKeyId(recipientPublicKey)) throw new Error('Direct-chat recipient key ID mismatch');
  const ephemeral = nacl.box.keyPair();
  const nonce = nacl.randomBytes(24);
  const payload = encoder.encode(JSON.stringify({
    v: 1, team_id: identity.teamId, chat_id: identity.chatId,
    recipient_hash: identity.recipientHash, key_id: identity.keyId,
    key: directChatBase64Url(rawKey),
  }));
  const ciphertext = nacl.box(payload, nonce, recipient, ephemeral.secretKey);
  const envelope = PREFIX + directChatBase64Url(encoder.encode(JSON.stringify({
    v: 1, ephemeral_public_key: directChatBase64Url(ephemeral.publicKey),
    nonce: directChatBase64Url(nonce), ciphertext: directChatBase64Url(ciphertext),
  })));
  ephemeral.secretKey.fill(0);
  if (envelope.length > MAX_ENVELOPE_LENGTH) throw new Error('Direct-chat envelope too large');
  return envelope;
}

export async function openDirectChatKey(
  envelope: string,
  expected: DirectChatIdentity,
  privateKey: string,
): Promise<Uint8Array> {
  boundedIdentity(expected);
  if (typeof envelope !== 'string' || !envelope.startsWith(PREFIX) || envelope.length > MAX_ENVELOPE_LENGTH) {
    throw new Error('Invalid direct-chat envelope');
  }
  const encoded = envelope.slice(PREFIX.length);
  const decoded = directChatBase64UrlBytes(encoded, undefined, 'envelope');
  // The encoded payload length is variable, so verify canonical encoding separately.
  if (decoded.length > MAX_PAYLOAD_BYTES) throw new Error('Direct-chat envelope too large');
  let parsed: unknown;
  try { parsed = JSON.parse(decoder.decode(decoded)); } catch { throw new Error('Invalid direct-chat envelope'); }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Invalid direct-chat envelope');
  const outer = parsed as Record<string, unknown>;
  if (Object.keys(outer).sort().join(',') !== 'ciphertext,ephemeral_public_key,nonce,v' || outer.v !== 1) {
    throw new Error('Invalid direct-chat envelope version or fields');
  }
  const sender = validatePublicKey(String(outer.ephemeral_public_key));
  const nonce = directChatBase64UrlBytes(String(outer.nonce), 24, 'nonce');
  const ciphertext = directChatBase64UrlBytes(String(outer.ciphertext), undefined, 'ciphertext', 512);
  if (ciphertext.length < 17) throw new Error('Invalid direct-chat ciphertext');
  const secret = directChatBase64UrlBytes(privateKey, 32, 'private key');
  validNonzeroKey(secret, 'private key');
  const ownPublic = directChatBase64Url(nacl.scalarMult.base(secret));
  if (await directChatKeyId(ownPublic) !== expected.keyId) throw new Error('Direct-chat private key ID mismatch');
  const plaintext = nacl.box.open(ciphertext, nonce, sender, secret);
  if (!plaintext) throw new Error('Direct-chat key authentication failed');
  let inner: unknown;
  try { inner = JSON.parse(decoder.decode(plaintext)); } catch { throw new Error('Invalid direct-chat key payload'); }
  if (!inner || typeof inner !== 'object' || Array.isArray(inner)) throw new Error('Invalid direct-chat key payload');
  const payload = inner as Record<string, unknown>;
  if (Object.keys(payload).sort().join(',') !== 'chat_id,key,key_id,recipient_hash,team_id,v' || payload.v !== 1 ||
    payload.team_id !== expected.teamId || payload.chat_id !== expected.chatId ||
    payload.recipient_hash !== expected.recipientHash || payload.key_id !== expected.keyId) {
    throw new Error('Direct-chat key binding mismatch');
  }
  const key = directChatBase64UrlBytes(String(payload.key), 32, 'chat key');
  validNonzeroKey(key, 'chat key');
  return key;
}
