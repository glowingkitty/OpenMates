/** Client-to-client pairing v2. OPAQUE's server role lives only on the approving client. */
import { client, ready, server } from '@serenity-kit/opaque';

export const PAIR_PROTOCOL_VERSION = 2 as const;
export const PAIR_PIN_ALPHABET = 'ABCDEFGHJKLMNPQRTUVWXY3468';
const PIN_LENGTH = 6;
const KSF = { 'argon2id-custom': { memory: 8192, iterations: 3, parallelism: 1 } } as const;
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });
const BUNDLE_INFO = encoder.encode('openmates-pair-v2/bundle');
const BASE64URL = /^[A-Za-z0-9_-]+$/;
const HEX_256 = /^[0-9a-f]{64}$/;
const BUNDLE_KEYS = new Set(['protocol_version', 'master_key_exported', 'grant_secret', 'user_email_salt', 'hashed_email', 'user_id', 'account_context']);

// All inputs here are owned Uint8Arrays, never SharedArrayBuffer views. TS's broad
// Uint8Array default still includes SharedArrayBuffer, which WebCrypto disallows.
function ownedBuffer(bytes: Uint8Array): Uint8Array<ArrayBuffer> {
  return bytes as Uint8Array<ArrayBuffer>;
}

export interface PairContextFields {
  token: string;
  session_id: string;
  receiver_token_hash: string;
  authorizer_user_id: string;
  auto_logout_minutes: null | 30 | 60 | 240 | 480 | 1440;
}

export interface PairBundle {
  protocol_version: 2;
  master_key_exported: string;
  grant_secret: string;
  user_email_salt: string;
  hashed_email: string;
  user_id: string;
  /** Only non-secret account metadata needed to initialize the local account. */
  account_context?: Record<string, string>;
}

export interface EncryptedPairBundle {
  encrypted_bundle: string;
  iv: string;
}

function requireAscii(value: unknown, name: string, max = 128): string {
  if (typeof value !== 'string' || value.length < 1 || value.length > max || !/^[\x21-\x7e]+$/.test(value)) {
    throw new Error(`Invalid pairing ${name}`);
  }
  return value;
}

/** Exact wire-independent binding: UTF-8 JSON.stringify array, no object key-order dependency. */
export function createPairContext(fields: PairContextFields): string {
  const token = requireAscii(fields.token, 'token', 64);
  const sessionId = requireAscii(fields.session_id, 'session ID');
  const hash = requireAscii(fields.receiver_token_hash, 'receiver hash', 64);
  if (!HEX_256.test(hash)) throw new Error('Invalid pairing receiver hash');
  const userId = requireAscii(fields.authorizer_user_id, 'authorizer user ID');
  const minutes = fields.auto_logout_minutes;
  if (minutes !== null && ![30, 60, 240, 480, 1440].includes(minutes)) {
    throw new Error('Invalid pairing session lifetime');
  }
  return JSON.stringify(['openmates-pair', 2, token, sessionId, hash, userId, minutes]);
}

function validateContext(context: string): { text: string; bytes: Uint8Array; fields: PairContextFields } {
  if (typeof context !== 'string' || context.length > 512) throw new Error('Invalid pairing context');
  let parsed: unknown;
  try { parsed = JSON.parse(context); } catch { throw new Error('Invalid pairing context'); }
  if (!Array.isArray(parsed) || parsed.length !== 7 || parsed[0] !== 'openmates-pair' || parsed[1] !== 2) {
    throw new Error('Invalid pairing context');
  }
  const fields = {
    token: parsed[2], session_id: parsed[3], receiver_token_hash: parsed[4],
    authorizer_user_id: parsed[5], auto_logout_minutes: parsed[6],
  } as PairContextFields;
  if (createPairContext(fields) !== context) throw new Error('Noncanonical pairing context');
  return { text: context, bytes: encoder.encode(context), fields };
}

function identifiers(context: string) {
  return { client: `openmates-pair-v2/client/${context}`, server: `openmates-pair-v2/server/${context}` };
}

function randomBytes(size: number): Uint8Array {
  const bytes = new Uint8Array(size);
  crypto.getRandomValues(bytes);
  return bytes;
}

function base64url(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function decodeBase64url(value: string, maxBytes: number): Uint8Array {
  if (typeof value !== 'string' || value.length < 1 || value.length > Math.ceil(maxBytes * 4 / 3) + 2 || !BASE64URL.test(value)) {
    throw new Error('Invalid pairing encoding');
  }
  let bytes: Uint8Array;
  try {
    const binary = atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4));
    bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
  } catch { throw new Error('Invalid pairing encoding'); }
  if (bytes.length > maxBytes || base64url(bytes) !== value) throw new Error('Invalid pairing encoding');
  return bytes;
}

function validateMessage(message: string): string {
  decodeBase64url(message, 8192);
  return message;
}

function validatePin(pin: string): string {
  if (typeof pin !== 'string' || pin.length !== PIN_LENGTH || [...pin].some(char => !PAIR_PIN_ALPHABET.includes(char))) {
    throw new Error('Invalid pairing PIN');
  }
  return pin;
}

/** Unbiased rejection sampling from the existing human-readable PIN alphabet. */
export function generatePairPin(): string {
  const limit = Math.floor(256 / PAIR_PIN_ALPHABET.length) * PAIR_PIN_ALPHABET.length;
  let pin = '';
  while (pin.length < PIN_LENGTH) {
    for (const byte of randomBytes(16)) {
      if (byte < limit) pin += PAIR_PIN_ALPHABET[byte % PAIR_PIN_ALPHABET.length];
      if (pin.length === PIN_LENGTH) break;
    }
  }
  return pin;
}

export async function hashPairSecret(secret: string): Promise<string> {
  const bytes = decodeBase64url(secret, 32);
  if (bytes.length !== 32) throw new Error('Invalid pairing secret');
  try {
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', ownedBuffer(bytes)));
    return [...digest].map(byte => byte.toString(16).padStart(2, '0')).join('');
  } finally { bytes.fill(0); }
}

export async function generateReceiverCapability(): Promise<{ secret: string; hash: string }> {
  const bytes = randomBytes(32);
  const secret = base64url(bytes);
  bytes.fill(0);
  return { secret, hash: await hashPairSecret(secret) };
}

export async function generateGrantSecret(): Promise<{ secret: string; hash: string }> {
  return generateReceiverCapability();
}

async function deriveBundleKey(sessionKey: string, contextBytes: Uint8Array): Promise<CryptoKey> {
  const raw = decodeBase64url(sessionKey, 64);
  if (raw.length !== 64) throw new Error('Invalid pairing session key');
  try {
    const salt = await crypto.subtle.digest('SHA-256', ownedBuffer(contextBytes));
    const ikm = await crypto.subtle.importKey('raw', ownedBuffer(raw), 'HKDF', false, ['deriveKey']);
    return crypto.subtle.deriveKey(
      { name: 'HKDF', hash: 'SHA-256', salt, info: ownedBuffer(BUNDLE_INFO) },
      ikm, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'],
    );
  } finally { raw.fill(0); }
}

function validateBundle(bundle: PairBundle, expectedUserId: string): PairBundle {
  if (!bundle || typeof bundle !== 'object' || Object.keys(bundle).some(key => !BUNDLE_KEYS.has(key)) ||
    bundle.protocol_version !== 2 ||
    bundle.user_id !== expectedUserId || typeof bundle.master_key_exported !== 'string' ||
    !bundle.master_key_exported || typeof bundle.user_email_salt !== 'string' || !bundle.user_email_salt ||
    typeof bundle.hashed_email !== 'string' || !bundle.hashed_email ||
    typeof bundle.grant_secret !== 'string') {
    throw new Error('Invalid pairing bundle');
  }
  const grant = decodeBase64url(bundle.grant_secret, 32);
  if (grant.length !== 32) throw new Error('Invalid pairing grant secret');
  grant.fill(0);
  if (bundle.account_context !== undefined &&
    (typeof bundle.account_context !== 'object' || bundle.account_context === null || Array.isArray(bundle.account_context) ||
      Object.entries(bundle.account_context).some(([key, value]) => !/^[a-z_]{1,40}$/.test(key) || typeof value !== 'string' || value.length > 512))) {
    throw new Error('Invalid pairing account context');
  }
  return bundle;
}

export interface PairApprover {
  readonly pin: string;
  receiveRequest(ke1: string): Promise<string>;
  verifyFinish(ke3: string): Promise<void>;
  encryptBundle(bundle: PairBundle): Promise<EncryptedPairBundle>;
  abort(): void;
}

export async function createPairApprover(context: string): Promise<PairApprover> {
  const binding = validateContext(context);
  await ready;
  let pin: string | undefined = generatePairPin();
  const ids = identifiers(binding.text);
  let setup: string | undefined;
  let record: string | undefined;
  let serverState: string | undefined;
  let key: CryptoKey | undefined;
  let aborted = false;
  let stage: 'ready' | 'await-finish' | 'verified' | 'used' | 'aborted' = 'ready';
  const assertActive = () => { if (aborted) throw new Error('Pairing exchange aborted'); };
  const abort = () => {
    aborted = true;
    setup = record = serverState = undefined;
    pin = undefined;
    key = undefined;
    stage = 'aborted';
  };
  try {
    setup = server.createSetup();
    const registration = client.startRegistration({ password: pin });
    const response = server.createRegistrationResponse({
      serverSetup: setup, userIdentifier: binding.text, registrationRequest: registration.registrationRequest,
    });
    record = client.finishRegistration({
      clientRegistrationState: registration.clientRegistrationState,
      registrationResponse: response.registrationResponse, password: pin, identifiers: ids, keyStretching: KSF,
    }).registrationRecord;
  } catch (error) { abort(); throw error; }
  return {
    get pin() {
      if (!pin) throw new Error('Pairing exchange closed');
      return pin;
    },
    async receiveRequest(ke1) {
      if (stage !== 'ready') throw new Error('Pairing exchange already used');
      stage = 'await-finish';
      try {
        const message = validateMessage(ke1);
        const result = server.startLogin({
          serverSetup: setup!, registrationRecord: record!, startLoginRequest: message,
          userIdentifier: binding.text, identifiers: ids,
        });
        serverState = result.serverLoginState;
        setup = record = undefined;
        return result.loginResponse;
      } catch (error) { abort(); throw error; }
    },
    async verifyFinish(ke3) {
      if (stage !== 'await-finish' || !serverState) throw new Error('Pairing exchange out of order');
      stage = 'used';
      try {
        const result = server.finishLogin({
          serverLoginState: serverState, finishLoginRequest: validateMessage(ke3), identifiers: ids,
        });
        serverState = undefined;
        const derived = await deriveBundleKey(result.sessionKey, binding.bytes);
        assertActive();
        key = derived;
        stage = 'verified';
      } catch (error) { abort(); throw error; }
    },
    async encryptBundle(bundle) {
      if (stage !== 'verified' || !key) throw new Error('Pairing proof not verified');
      stage = 'used';
      try {
        validateBundle(bundle, binding.fields.authorizer_user_id);
        const iv = randomBytes(12);
        const plaintext = encoder.encode(JSON.stringify(bundle));
        try {
          const ciphertext = await crypto.subtle.encrypt(
            { name: 'AES-GCM', iv: ownedBuffer(iv), additionalData: ownedBuffer(binding.bytes), tagLength: 128 }, key, ownedBuffer(plaintext),
          );
          assertActive();
          return { encrypted_bundle: base64url(new Uint8Array(ciphertext)), iv: base64url(iv) };
        } finally { plaintext.fill(0); iv.fill(0); abort(); }
      } catch (error) { abort(); throw error; }
    },
    abort,
  };
}

export interface PairReceiver {
  readonly request: string;
  receiveResponse(ke2: string): Promise<string>;
  decryptBundle(encryptedBundle: string, iv: string): Promise<PairBundle>;
  abort(): void;
}

export async function createPairReceiver(context: string, pin: string): Promise<PairReceiver> {
  const binding = validateContext(context);
  let password: string | undefined = validatePin(pin);
  await ready;
  const ids = identifiers(binding.text);
  const started = client.startLogin({ password });
  let clientState: string | undefined = started.clientLoginState;
  let key: CryptoKey | undefined;
  let aborted = false;
  let stage: 'ready' | 'await-bundle' | 'used' | 'aborted' = 'ready';
  const assertActive = () => { if (aborted) throw new Error('Pairing exchange aborted'); };
  const abort = () => { aborted = true; clientState = undefined; password = undefined; key = undefined; stage = 'aborted'; };
  return {
    request: started.startLoginRequest,
    async receiveResponse(ke2) {
      if (stage !== 'ready' || !clientState) throw new Error('Pairing exchange already used');
      stage = 'used';
      try {
        const result = client.finishLogin({
          clientLoginState: clientState, loginResponse: validateMessage(ke2), password: password!,
          identifiers: ids, keyStretching: KSF,
        });
        clientState = undefined;
        password = undefined;
        if (!result) throw new Error('Pairing authentication failed');
        const derived = await deriveBundleKey(result.sessionKey, binding.bytes);
        assertActive();
        key = derived;
        stage = 'await-bundle';
        return result.finishLoginRequest;
      } catch (error) { abort(); throw error; }
    },
    async decryptBundle(encryptedBundle, iv) {
      if (stage !== 'await-bundle' || !key) throw new Error('Pairing bundle out of order');
      stage = 'used';
      try {
        const nonce = decodeBase64url(iv, 12);
        if (nonce.length !== 12) throw new Error('Invalid pairing IV');
        const ciphertext = decodeBase64url(encryptedBundle, 65536);
        const plaintext = new Uint8Array(await crypto.subtle.decrypt(
          { name: 'AES-GCM', iv: ownedBuffer(nonce), additionalData: ownedBuffer(binding.bytes), tagLength: 128 }, key, ownedBuffer(ciphertext),
        ));
        try {
          assertActive();
          return validateBundle(JSON.parse(decoder.decode(plaintext)), binding.fields.authorizer_user_id);
        }
        finally { nonce.fill(0); ciphertext.fill(0); plaintext.fill(0); }
      } catch (error) { abort(); throw error; }
      finally { abort(); }
    },
    abort,
  };
}
