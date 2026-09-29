/*
 * OpenMates CLI crypto utilities.
 *
 * Purpose: keep account and chat metadata crypto in one Node-safe module.
 * Architecture: pairs use the shared @repo/pairing-crypto PAKE module.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: account and chat keys remain client-side.
 * Tests: frontend/packages/openmates-cli/tests/crypto.test.ts
 */

import { webcrypto, createHash, createHmac } from "node:crypto";
import { argon2id } from "hash-wasm";
import nacl from "tweetnacl";

const cryptoApi = globalThis.crypto ?? webcrypto;
const SIGNUP_KDF_ITERATIONS = 100_000;
export const PASSWORD_KDF_V2 = Object.freeze({
  version: 2,
  algorithm: "argon2id",
  memoryKiB: 65_536,
  iterations: 3,
  parallelism: 1,
  hashLength: 32,
});
const AES_GCM_IV_LENGTH = 12;
const EMAIL_SALT_LENGTH = 16;
const MASTER_KEY_LENGTH = 32;
const NACL_NONCE_LENGTH = 24;

// New ciphertext format: [0x4F 0x4D][4-byte key fingerprint][IV][ciphertext]
// The web app's encryptWithChatKey() now prepends "OM" magic + fingerprint.
// We detect this header and skip it to find the actual IV.
const CIPHERTEXT_MAGIC_0 = 0x4f; // 'O'
const CIPHERTEXT_MAGIC_1 = 0x4d; // 'M'
const FINGERPRINT_LENGTH = 4;
const CIPHERTEXT_HEADER_LENGTH = 2 + FINGERPRINT_LENGTH; // 6 bytes
const API_KEY_PREFIX = "sk-api-";
const API_KEY_RANDOM_LENGTH = 32;
const API_KEY_CHARS = "ABCDEFGHIJKLMNPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz123456789";
const CHAT_RECOVERY_PROTOCOL_VERSION = 1;
const CHAT_RECOVERY_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024;
const CHAT_RECOVERY_KEY_BYTES = 32;
const CHAT_RECOVERY_NONCE_BYTES = 12;
const CHAT_RECOVERY_AAD_PREFIX = new TextEncoder().encode("OMCR1");
const CHAT_RECOVERY_UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function base64ToBytes(input: string): Uint8Array {
  return new Uint8Array(Buffer.from(input, "base64"));
}

export function bytesToBase64(input: Uint8Array): string {
  return Buffer.from(input).toString("base64");
}

export function bytesToBase64Url(input: Uint8Array): string {
  return Buffer.from(input).toString("base64url");
}

function toArrayBuffer(input: Uint8Array): ArrayBuffer {
  const output = new ArrayBuffer(input.byteLength);
  new Uint8Array(output).set(input);
  return output;
}

function base64UrlToBytes(input: string, field: string, expectedLength?: number): Uint8Array {
  if (!input || input.includes("=")) {
    throw new Error(`${field} must be non-empty unpadded base64url`);
  }
  const decoded = new Uint8Array(Buffer.from(input, "base64url"));
  if (bytesToBase64Url(decoded) !== input) {
    throw new Error(`${field} must be canonical base64url`);
  }
  if (expectedLength !== undefined && decoded.length !== expectedLength) {
    throw new Error(`${field} must decode to ${expectedLength} bytes`);
  }
  return decoded;
}

export async function deriveTeamInviteKey(input: {
  recipientEmail: string;
  inviteSecret: string;
  inviteId: string;
  teamId: string;
  origin: string;
}): Promise<Uint8Array> {
  const secretBytes = base64UrlToBytes(input.inviteSecret, "invite secret", 32);
  const salt = await sha256(new TextEncoder().encode("openmates:team-invite:v1"));
  const info = concatBytes(
    lengthPrefix(new TextEncoder().encode(input.recipientEmail.trim().toLowerCase())),
    lengthPrefix(new TextEncoder().encode(input.inviteId)),
    lengthPrefix(new TextEncoder().encode(input.teamId)),
    lengthPrefix(new TextEncoder().encode(input.origin.replace(/\/$/, ""))),
  );
  return hkdfSha256(secretBytes, salt, info);
}

function uint32(value: number, field: string): Uint8Array {
  if (!Number.isInteger(value) || value < 0 || value > 0xffffffff) {
    throw new Error(`${field} must be an unsigned 32-bit integer`);
  }
  const encoded = new Uint8Array(4);
  new DataView(encoded.buffer).setUint32(0, value, false);
  return encoded;
}

function recoveryKeyVersion(value: number): Uint8Array {
  if (value === 0) {
    throw new Error("key_version must be greater than zero");
  }
  return uint32(value, "key_version");
}

function canonicalUuid(value: string, field: string): Uint8Array {
  if (!CHAT_RECOVERY_UUID_PATTERN.test(value)) {
    throw new Error(`${field} must be a canonical lowercase UUID`);
  }
  return new TextEncoder().encode(value);
}

function concatBytes(...values: Uint8Array[]): Uint8Array {
  const output = new Uint8Array(values.reduce((total, value) => total + value.length, 0));
  let offset = 0;
  for (const value of values) {
    output.set(value, offset);
    offset += value.length;
  }
  return output;
}

function lengthPrefix(value: Uint8Array): Uint8Array {
  return concatBytes(uint32(value.length, "length"), value);
}

async function sha256(input: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await cryptoApi.subtle.digest("SHA-256", toArrayBuffer(input)));
}

async function hkdfSha256(input: Uint8Array, salt: Uint8Array, info: Uint8Array): Promise<Uint8Array> {
  const key = await cryptoApi.subtle.importKey("raw", toArrayBuffer(input), "HKDF", false, ["deriveBits"]);
  const bits = await cryptoApi.subtle.deriveBits(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt: toArrayBuffer(salt),
      info: toArrayBuffer(info),
    },
    key,
    256,
  );
  return new Uint8Array(bits);
}

export interface ChatCompletionRecoveryIdentity {
  ownerId: string;
  chatId: string;
  turnId: string;
  jobId: string;
  assistantMessageId: string;
  keyVersion: number;
}

export interface ChatCompletionRecoveryEnvelope {
  v: number;
  epk: string;
  nonce: string;
  ciphertext: string;
}

export async function deriveChatCompletionRecoveryKeypair(
  chatKey: string,
  chatId: string,
  keyVersion: number,
): Promise<{ privateKey: string; publicKey: string }> {
  const rawChatKey = base64UrlToBytes(chatKey, "chat_key", CHAT_RECOVERY_KEY_BYTES);
  const salt = await sha256(new TextEncoder().encode("openmates:chat-recovery:v1"));
  const info = concatBytes(lengthPrefix(canonicalUuid(chatId, "chat_id")), recoveryKeyVersion(keyVersion));
  const privateKey = await hkdfSha256(rawChatKey, salt, info);
  return {
    privateKey: bytesToBase64Url(privateKey),
    publicKey: bytesToBase64Url(nacl.scalarMult.base(privateKey)),
  };
}

export function buildRecoveryAssociatedData(values: {
  owner_id: string;
  chat_id: string;
  turn_id: string;
  job_id: string;
  assistant_message_id: string;
  key_version: number;
}): string {
  const associatedData = concatBytes(
    CHAT_RECOVERY_AAD_PREFIX,
    lengthPrefix(canonicalUuid(values.owner_id, "owner_id")),
    lengthPrefix(canonicalUuid(values.chat_id, "chat_id")),
    lengthPrefix(canonicalUuid(values.turn_id, "turn_id")),
    lengthPrefix(canonicalUuid(values.job_id, "job_id")),
    lengthPrefix(canonicalUuid(values.assistant_message_id, "assistant_message_id")),
    recoveryKeyVersion(values.key_version),
  );
  return bytesToBase64Url(associatedData);
}

function recoveryAssociatedData(identity: ChatCompletionRecoveryIdentity): Uint8Array {
  return base64UrlToBytes(
    buildRecoveryAssociatedData({
      owner_id: identity.ownerId,
      chat_id: identity.chatId,
      turn_id: identity.turnId,
      job_id: identity.jobId,
      assistant_message_id: identity.assistantMessageId,
      key_version: identity.keyVersion,
    }),
    "associated_data",
  );
}

async function recoveryEnvelopeKey(sharedSecret: Uint8Array, associatedData: Uint8Array): Promise<Uint8Array> {
  if (sharedSecret.every((value) => value === 0)) {
    throw new Error("X25519 shared secret must not be all zero");
  }
  const salt = await sha256(new TextEncoder().encode("openmates:chat-recovery-envelope:v1"));
  return hkdfSha256(sharedSecret, salt, await sha256(associatedData));
}

export async function sealChatCompletionRecoveryPayload(
  plaintext: Uint8Array,
  options: ChatCompletionRecoveryIdentity & { recoveryPublicKey: string },
): Promise<ChatCompletionRecoveryEnvelope> {
  const unsafeOptions = options as typeof options & { ephemeralPrivateKey?: string; nonce?: string };
  if (unsafeOptions.ephemeralPrivateKey !== undefined || unsafeOptions.nonce !== undefined) {
    throw new Error("deterministic recovery sealing inputs are test-only");
  }
  return sealChatCompletionRecoveryPayloadWithInputs(
    plaintext,
    options,
    cryptoApi.getRandomValues(new Uint8Array(CHAT_RECOVERY_KEY_BYTES)),
    cryptoApi.getRandomValues(new Uint8Array(CHAT_RECOVERY_NONCE_BYTES)),
  );
}

export async function sealChatCompletionRecoveryPayloadForTest(
  plaintext: Uint8Array,
  options: ChatCompletionRecoveryIdentity & {
    recoveryPublicKey: string;
    ephemeralPrivateKey: string;
    nonce: string;
  },
): Promise<ChatCompletionRecoveryEnvelope> {
  return sealChatCompletionRecoveryPayloadWithInputs(
    plaintext,
    options,
    base64UrlToBytes(options.ephemeralPrivateKey, "ephemeral_private_key", CHAT_RECOVERY_KEY_BYTES),
    base64UrlToBytes(options.nonce, "nonce", CHAT_RECOVERY_NONCE_BYTES),
  );
}

async function sealChatCompletionRecoveryPayloadWithInputs(
  plaintext: Uint8Array,
  options: ChatCompletionRecoveryIdentity & { recoveryPublicKey: string },
  ephemeralPrivateKey: Uint8Array,
  nonce: Uint8Array,
): Promise<ChatCompletionRecoveryEnvelope> {
  if (plaintext.length > CHAT_RECOVERY_MAX_PAYLOAD_BYTES) {
    throw new Error(`plaintext must be no larger than ${CHAT_RECOVERY_MAX_PAYLOAD_BYTES}`);
  }
  const recoveryPublicKey = base64UrlToBytes(
    options.recoveryPublicKey,
    "recovery_public_key",
    CHAT_RECOVERY_KEY_BYTES,
  );
  const ephemeralPublicKey = nacl.scalarMult.base(ephemeralPrivateKey);
  const sharedSecret = nacl.scalarMult(ephemeralPrivateKey, recoveryPublicKey);
  const associatedData = recoveryAssociatedData(options);
  const envelopeKeyBytes = await recoveryEnvelopeKey(sharedSecret, associatedData);
  const envelopeKey = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(envelopeKeyBytes),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const ciphertext = new Uint8Array(await cryptoApi.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(nonce), additionalData: toArrayBuffer(associatedData) },
    envelopeKey,
    toArrayBuffer(plaintext),
  ));
  return {
    v: CHAT_RECOVERY_PROTOCOL_VERSION,
    epk: bytesToBase64Url(ephemeralPublicKey),
    nonce: bytesToBase64Url(nonce),
    ciphertext: bytesToBase64Url(ciphertext),
  };
}

export async function openChatCompletionRecoveryEnvelope(
  envelope: ChatCompletionRecoveryEnvelope,
  options: ChatCompletionRecoveryIdentity & { recoveryPrivateKey: string },
): Promise<Uint8Array> {
  if (
    !envelope
    || Object.keys(envelope).sort().join(",") !== "ciphertext,epk,nonce,v"
    || envelope.v !== CHAT_RECOVERY_PROTOCOL_VERSION
  ) {
    throw new Error("invalid recovery envelope fields or version");
  }
  const recoveryPrivateKey = base64UrlToBytes(
    options.recoveryPrivateKey,
    "recovery_private_key",
    CHAT_RECOVERY_KEY_BYTES,
  );
  const ephemeralPublicKey = base64UrlToBytes(envelope.epk, "epk", CHAT_RECOVERY_KEY_BYTES);
  const nonce = base64UrlToBytes(envelope.nonce, "nonce", CHAT_RECOVERY_NONCE_BYTES);
  const ciphertext = base64UrlToBytes(envelope.ciphertext, "ciphertext");
  if (ciphertext.length < 16 || ciphertext.length - 16 > CHAT_RECOVERY_MAX_PAYLOAD_BYTES) {
    throw new Error("ciphertext payload size is invalid");
  }
  const associatedData = recoveryAssociatedData(options);
  const sharedSecret = nacl.scalarMult(recoveryPrivateKey, ephemeralPublicKey);
  const envelopeKeyBytes = await recoveryEnvelopeKey(sharedSecret, associatedData);
  const envelopeKey = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(envelopeKeyBytes),
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );
  return new Uint8Array(await cryptoApi.subtle.decrypt(
    { name: "AES-GCM", iv: toArrayBuffer(nonce), additionalData: toArrayBuffer(associatedData) },
    envelopeKey,
    toArrayBuffer(ciphertext),
  ));
}

export function generateSalt(length = EMAIL_SALT_LENGTH): Uint8Array {
  return cryptoApi.getRandomValues(new Uint8Array(length));
}

export function generateSecureRecoveryKey(length = 24): string {
  const uppercaseChars = "ABCDEFGHJKLMNPQRSTUVWXYZ";
  const lowercaseChars = "abcdefghijkmnopqrstuvwxyz";
  const numberChars = "23456789";
  const specialChars = "#-=+_&%$";
  const allChars = uppercaseChars + lowercaseChars + numberChars + specialChars;
  const result: string[] = new Array(length);
  const requiredSets = [uppercaseChars, lowercaseChars, numberChars, specialChars];

  for (let index = 0; index < requiredSets.length && index < length; index += 1) {
    const chars = requiredSets[index];
    result[index] = chars.charAt(secureRandomIndex(chars.length));
  }

  for (let index = requiredSets.length; index < length; index += 1) {
    result[index] = allChars.charAt(secureRandomIndex(allChars.length));
  }

  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = secureRandomIndex(index + 1);
    [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
  }

  return result.join("");
}

function secureRandomIndex(upperBound: number): number {
  if (!Number.isInteger(upperBound) || upperBound <= 0 || upperBound > 256) {
    throw new RangeError("secure random upper bound must be between 1 and 256");
  }
  const maxUnbiasedValue = Math.floor(256 / upperBound) * upperBound;
  while (true) {
    const value = cryptoApi.getRandomValues(new Uint8Array(1))[0];
    if (value < maxUnbiasedValue) return value % upperBound;
  }
}

export async function hashEmail(email: string): Promise<string> {
  const hashBuffer = await cryptoApi.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(email),
  );
  return bytesToBase64(new Uint8Array(hashBuffer));
}

export async function hashKey(key: string, salt?: Uint8Array | null): Promise<string> {
  const keyBytes = new TextEncoder().encode(key);
  const dataToHash = salt
    ? new Uint8Array(keyBytes.length + salt.length)
    : keyBytes;
  if (salt) {
    dataToHash.set(keyBytes);
    dataToHash.set(salt, keyBytes.length);
  }
  const hashBuffer = await cryptoApi.subtle.digest("SHA-256", toArrayBuffer(dataToHash));
  return bytesToBase64(new Uint8Array(hashBuffer));
}

export async function deriveKeyFromPassword(password: string, salt: Uint8Array): Promise<Uint8Array> {
  const keyMaterial = await cryptoApi.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const derivedBits = await cryptoApi.subtle.deriveBits(
    {
      name: "PBKDF2",
      salt: toArrayBuffer(salt),
      iterations: SIGNUP_KDF_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    256,
  );
  return new Uint8Array(derivedBits);
}

/** Versioned password-only material; existing recovery and API-key wrappers stay on their legacy KDF. */
export async function derivePasswordMaterialV2(password: string, salt: Uint8Array): Promise<Uint8Array> {
  if (!password || salt.length < 16) throw new Error("Argon2id password derivation requires a password and at least 16 salt bytes");
  const output = await argon2id({
    password,
    salt,
    memorySize: PASSWORD_KDF_V2.memoryKiB,
    iterations: PASSWORD_KDF_V2.iterations,
    parallelism: PASSWORD_KDF_V2.parallelism,
    hashLength: PASSWORD_KDF_V2.hashLength,
    outputType: "binary",
  });
  if (!(output instanceof Uint8Array) || output.length !== PASSWORD_KDF_V2.hashLength) {
    throw new Error("Argon2id password derivation failed");
  }
  return output;
}

export async function derivePasswordKeysV2(password: string, userEmailSalt: Uint8Array): Promise<{ authKey: Uint8Array; wrapKey: Uint8Array }> {
  const material = await derivePasswordMaterialV2(password, userEmailSalt);
  const hkdfKey = await cryptoApi.subtle.importKey("raw", toArrayBuffer(material), "HKDF", false, ["deriveBits"]);
  const expand = async (label: string): Promise<Uint8Array> => new Uint8Array(await cryptoApi.subtle.deriveBits({
    name: "HKDF",
    hash: "SHA-256",
    salt: new Uint8Array(0),
    info: new TextEncoder().encode(label),
  }, hkdfKey, 256));
  try {
    return {
      authKey: await expand("openmates/password-v2/auth"),
      wrapKey: await expand("openmates/password-v2/wrap"),
    };
  } finally {
    material.fill(0);
  }
}

export function passwordProofV2(authKey: Uint8Array, nonceB64url: string, purpose: string): string {
  if (!/^[a-z0-9_]+$/.test(purpose)) throw new Error("Invalid password proof purpose");
  const nonce = base64UrlToBytes(nonceB64url, "password challenge nonce", 32);
  return createHmac("sha256", authKey)
    .update(Buffer.from(`openmates/password-v2/proof\0${purpose}\0`, "utf8"))
    .update(nonce)
    .digest("base64url");
}

/** Open a password wrapper after a verified login; missing version is legacy PBKDF2. */
export async function unwrapPasswordMasterKey(params: {
  password: string;
  credentialVersion?: number | null;
  encryptedMasterKeyB64: string;
  saltB64: string;
  keyIvB64: string;
}): Promise<Uint8Array | null> {
  let wrappingKeyBytes: Uint8Array | null = null;
  try {
    const salt = base64ToBytes(params.saltB64);
    if (params.credentialVersion === 2) {
      const keys = await derivePasswordKeysV2(params.password, salt);
      keys.authKey.fill(0);
      wrappingKeyBytes = keys.wrapKey;
    } else if (params.credentialVersion == null || params.credentialVersion === 1) {
      wrappingKeyBytes = await deriveKeyFromPassword(params.password, salt);
    } else {
      return null;
    }
    const wrappingKey = await cryptoApi.subtle.importKey(
      "raw", toArrayBuffer(wrappingKeyBytes), { name: "AES-GCM" }, false, ["decrypt"],
    );
    return new Uint8Array(await cryptoApi.subtle.decrypt(
      { name: "AES-GCM", iv: toArrayBuffer(base64ToBytes(params.keyIvB64)) },
      wrappingKey, toArrayBuffer(base64ToBytes(params.encryptedMasterKeyB64)),
    ));
  } catch {
    return null;
  } finally {
    wrappingKeyBytes?.fill(0);
  }
}

export async function encryptEmail(email: string, key: Uint8Array): Promise<string> {
  if (key.length !== MASTER_KEY_LENGTH) {
    throw new Error(`Email encryption key must be 32 bytes, got ${key.length}`);
  }
  const nonce = nacl.randomBytes(NACL_NONCE_LENGTH);
  const ciphertext = nacl.secretbox(new TextEncoder().encode(email), nonce, key);
  const combined = new Uint8Array(nonce.length + ciphertext.length);
  combined.set(nonce);
  combined.set(ciphertext, nonce.length);
  return bytesToBase64(combined);
}

async function encryptRawKeyWithAesGcm(rawKey: Uint8Array, wrappingKeyBytes: Uint8Array): Promise<{ wrapped: string; iv: string }> {
  const iv = cryptoApi.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH));
  const wrappingKey = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(wrappingKeyBytes),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const encrypted = await cryptoApi.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(iv) },
    wrappingKey,
    toArrayBuffer(rawKey),
  );
  return {
    wrapped: bytesToBase64(new Uint8Array(encrypted)),
    iv: bytesToBase64(iv),
  };
}

export interface SignupCryptoMaterial {
  hashedEmail: string;
  encryptedEmail: string;
  encryptedEmailWithMasterKey: string;
  userEmailSaltB64: string;
  emailEncryptionKeyB64: string;
  masterKeyB64: string;
  encryptedMasterKey: string;
  keyIv: string;
  saltB64: string;
  credentialVersion: 2;
  passwordAuthKey: string;
}

export interface PasswordMigrationMaterialV2 {
  oldLookupHash: string;
  passwordAuthKey: string;
  encryptedMasterKey: string;
  saltB64: string;
  keyIv: string;
}

/** Rewrap an already-unlocked account key before asking the server to atomically retire a legacy password. */
export async function createPasswordMigrationMaterialV2(
  password: string,
  masterKeyB64: string,
  userEmailSaltB64: string,
): Promise<PasswordMigrationMaterialV2> {
  const userEmailSalt = base64ToBytes(userEmailSaltB64);
  const { authKey, wrapKey } = await derivePasswordKeysV2(password, userEmailSalt);
  try {
    const wrapper = await encryptRawKeyWithAesGcm(base64ToBytes(masterKeyB64), wrapKey);
    return {
      oldLookupHash: await hashKey(password, userEmailSalt),
      passwordAuthKey: Buffer.from(authKey).toString("base64url"),
      encryptedMasterKey: wrapper.wrapped,
      saltB64: userEmailSaltB64,
      keyIv: wrapper.iv,
    };
  } finally {
    authKey.fill(0);
    wrapKey.fill(0);
  }
}

export async function createSignupCryptoMaterial(email: string, password: string): Promise<SignupCryptoMaterial> {
  const normalizedEmail = email.trim().toLowerCase();
  const emailSalt = generateSalt(EMAIL_SALT_LENGTH);
  const masterKey = generateSalt(MASTER_KEY_LENGTH);
  const emailEncryptionKeyB64 = await deriveEmailEncryptionKeyB64(normalizedEmail, bytesToBase64(emailSalt));
  const emailEncryptionKey = base64ToBytes(emailEncryptionKeyB64);
  const { authKey, wrapKey } = await derivePasswordKeysV2(password, emailSalt);
  const encryptedMasterKey = await encryptRawKeyWithAesGcm(masterKey, wrapKey);
  const passwordAuthKey = Buffer.from(authKey).toString("base64url");
  authKey.fill(0);
  wrapKey.fill(0);

  return {
    hashedEmail: await hashEmail(normalizedEmail),
    encryptedEmail: await encryptEmail(normalizedEmail, emailEncryptionKey),
    encryptedEmailWithMasterKey: await encryptWithAesGcmCombined(normalizedEmail, masterKey),
    userEmailSaltB64: bytesToBase64(emailSalt),
    emailEncryptionKeyB64,
    masterKeyB64: bytesToBase64(masterKey),
    encryptedMasterKey: encryptedMasterKey.wrapped,
    keyIv: encryptedMasterKey.iv,
    saltB64: bytesToBase64(emailSalt),
    credentialVersion: 2,
    passwordAuthKey,
  };
}

export interface RecoveryKeyMaterial {
  recoveryKey: string;
  lookupHash: string;
  wrappedMasterKey: string;
  keyIv: string;
  saltB64: string;
}

export async function createRecoveryKeyMaterial(masterKeyB64: string, userEmailSaltB64: string): Promise<RecoveryKeyMaterial> {
  const recoveryKey = generateSecureRecoveryKey();
  const userEmailSalt = base64ToBytes(userEmailSaltB64);
  const wrappingSalt = generateSalt(EMAIL_SALT_LENGTH);
  const wrappingKey = await deriveKeyFromPassword(recoveryKey, wrappingSalt);
  const encryptedMasterKey = await encryptRawKeyWithAesGcm(base64ToBytes(masterKeyB64), wrappingKey);

  return {
    recoveryKey,
    lookupHash: await hashKey(recoveryKey, userEmailSalt),
    wrappedMasterKey: encryptedMasterKey.wrapped,
    keyIv: encryptedMasterKey.iv,
    saltB64: bytesToBase64(wrappingSalt),
  };
}

export interface ApiKeyCryptoMaterial {
  apiKey: string;
  apiKeyHash: string;
  encryptedName: string;
  encryptedKeyPrefix: string;
  encryptedMasterKey: string;
  keyIv: string;
  saltB64: string;
}

/** The displayed setup credential contains two independent random secrets. */
export function splitApiKeyCredential(value: string): { bearer: string; decryptionSecret: string | null } {
  const [bearer, decryptionSecret, extra] = value.split(".");
  if (extra || (decryptionSecret !== undefined && !decryptionSecret)) {
    throw new Error("Invalid API key setup credential");
  }
  return { bearer, decryptionSecret: decryptionSecret ?? null };
}

function generateApiKey(): string {
  let result = API_KEY_PREFIX;
  const maxUnbiasedValue = Math.floor(256 / API_KEY_CHARS.length) * API_KEY_CHARS.length;
  while (result.length < API_KEY_PREFIX.length + API_KEY_RANDOM_LENGTH) {
    const randomValues = cryptoApi.getRandomValues(new Uint8Array(API_KEY_RANDOM_LENGTH));
    for (const value of randomValues) {
      if (value >= maxUnbiasedValue) continue;
      result += API_KEY_CHARS.charAt(value % API_KEY_CHARS.length);
      if (result.length >= API_KEY_PREFIX.length + API_KEY_RANDOM_LENGTH) break;
    }
  }
  return result;
}

function sha256Hex(input: string): string {
  return createHash("sha256").update(input).digest("hex");
}

export async function createApiKeyCryptoMaterial(
  name: string,
  masterKeyB64: string,
): Promise<ApiKeyCryptoMaterial> {
  const masterKey = base64ToBytes(masterKeyB64);
  const bearer = generateApiKey();
  const decryptionSecret = generateApiKey().slice(API_KEY_PREFIX.length);
  const apiKey = `${bearer}.${decryptionSecret}`;
  const keyPrefix = `${bearer.slice(0, 12)}...`;
  const wrappingSalt = generateSalt(EMAIL_SALT_LENGTH);
  const wrappingKey = await deriveKeyFromPassword(decryptionSecret, wrappingSalt);
  const encryptedMasterKey = await encryptRawKeyWithAesGcm(masterKey, wrappingKey);

  return {
    apiKey,
    apiKeyHash: sha256Hex(bearer),
    encryptedName: await encryptWithAesGcmCombined(name.trim(), masterKey),
    encryptedKeyPrefix: await encryptWithAesGcmCombined(keyPrefix, masterKey),
    encryptedMasterKey: encryptedMasterKey.wrapped,
    keyIv: encryptedMasterKey.iv,
    saltB64: bytesToBase64(wrappingSalt),
  };
}

export async function unwrapApiKeyMasterKey(params: {
  apiKey: string;
  encryptedMasterKeyB64: string;
  saltB64: string;
  keyIvB64: string;
}): Promise<Uint8Array | null> {
  try {
    const { decryptionSecret } = splitApiKeyCredential(params.apiKey);
    // Old ciphertext may still be opened offline. The server separately rejects
    // legacy bearers for new API requests and requires replacement.
    const wrappingKeyBytes = await deriveKeyFromPassword(decryptionSecret ?? params.apiKey, base64ToBytes(params.saltB64));
    const wrappingKey = await cryptoApi.subtle.importKey(
      "raw",
      toArrayBuffer(wrappingKeyBytes),
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );
    const decrypted = await cryptoApi.subtle.decrypt(
      { name: "AES-GCM", iv: toArrayBuffer(base64ToBytes(params.keyIvB64)) },
      wrappingKey,
      toArrayBuffer(base64ToBytes(params.encryptedMasterKeyB64)),
    );
    return new Uint8Array(decrypted);
  } catch {
    return null;
  }
}

export async function decryptWithAesGcmCombined(
  encryptedWithIvB64: string,
  rawKeyBytes: Uint8Array,
  associatedData?: string,
): Promise<string | null> {
  try {
    const combined = base64ToBytes(encryptedWithIvB64);
    if (combined.length <= AES_GCM_IV_LENGTH) {
      return null;
    }

    // Detect new "OM" format: [magic 2B][fingerprint 4B][IV 12B][ciphertext]
    let offset = 0;
    if (
      combined.length > CIPHERTEXT_HEADER_LENGTH + AES_GCM_IV_LENGTH &&
      combined[0] === CIPHERTEXT_MAGIC_0 &&
      combined[1] === CIPHERTEXT_MAGIC_1
    ) {
      offset = CIPHERTEXT_HEADER_LENGTH;
    }

    const iv = combined.slice(offset, offset + AES_GCM_IV_LENGTH);
    const ciphertext = combined.slice(offset + AES_GCM_IV_LENGTH);
    const key = await cryptoApi.subtle.importKey(
      "raw",
      toArrayBuffer(rawKeyBytes),
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );
    const decrypted = await cryptoApi.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: toArrayBuffer(iv),
        ...(associatedData ? { additionalData: toArrayBuffer(new TextEncoder().encode(associatedData)) } : {}),
      },
      key,
      toArrayBuffer(ciphertext),
    );
    return new TextDecoder().decode(decrypted);
  } catch {
    return null;
  }
}

export async function deriveEmailEncryptionKeyB64(
  email: string,
  emailSaltB64: string,
): Promise<string> {
  const encoder = new TextEncoder();
  const emailBytes = encoder.encode(email);
  const saltBytes = base64ToBytes(emailSaltB64);
  const combined = new Uint8Array(emailBytes.length + saltBytes.length);
  combined.set(emailBytes);
  combined.set(saltBytes, emailBytes.length);
  const hashBuffer = await cryptoApi.subtle.digest("SHA-256", toArrayBuffer(combined));
  return bytesToBase64(new Uint8Array(hashBuffer));
}

/**
 * Decrypt AES-GCM-combined data and return the raw decrypted bytes.
 *
 * Mirrors the browser's `decryptChatKeyWithMasterKey()` from cryptoService.ts.
 * This MUST be used for decrypting binary payloads (e.g. chat keys) where the
 * result is raw bytes, NOT a UTF-8 string. Using TextDecoder on binary data
 * corrupts it.
 */
export async function decryptBytesWithAesGcm(
  encryptedWithIvB64: string,
  rawKeyBytes: Uint8Array,
): Promise<Uint8Array | null> {
  try {
    const combined = base64ToBytes(encryptedWithIvB64);
    if (combined.length <= AES_GCM_IV_LENGTH) {
      return null;
    }

    // Detect new "OM" format: [magic 2B][fingerprint 4B][IV 12B][ciphertext]
    let offset = 0;
    if (
      combined.length > CIPHERTEXT_HEADER_LENGTH + AES_GCM_IV_LENGTH &&
      combined[0] === CIPHERTEXT_MAGIC_0 &&
      combined[1] === CIPHERTEXT_MAGIC_1
    ) {
      offset = CIPHERTEXT_HEADER_LENGTH;
    }

    const iv = combined.slice(offset, offset + AES_GCM_IV_LENGTH);
    const ciphertext = combined.slice(offset + AES_GCM_IV_LENGTH);
    const key = await cryptoApi.subtle.importKey(
      "raw",
      toArrayBuffer(rawKeyBytes),
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );
    const decrypted = await cryptoApi.subtle.decrypt(
      { name: "AES-GCM", iv: toArrayBuffer(iv) },
      key,
      toArrayBuffer(ciphertext),
    );
    return new Uint8Array(decrypted);
  } catch {
    return null;
  }
}

/**
 * Derive an embed-specific AES key deterministically from the chat key.
 *
 * Mirrors the browser's deriveEmbedKeyFromChatKey() contract so CLI-created
 * embed version rows stay decryptable across updates and devices.
 */
export async function deriveEmbedKeyFromChatKey(
  chatKey: Uint8Array,
  embedId: string,
): Promise<Uint8Array> {
  const hkdfKey = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(new Uint8Array(chatKey)),
    "HKDF",
    false,
    ["deriveBits"],
  );
  const salt = new TextEncoder().encode("openmates-embed-key-v1");
  const info = new TextEncoder().encode(embedId);
  const derivedBits = await cryptoApi.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt: toArrayBuffer(salt), info: toArrayBuffer(info) },
    hkdfKey,
    256,
  );
  return new Uint8Array(derivedBits);
}

/**
 * Encrypt raw bytes with AES-256-GCM and return base64(IV || ciphertext).
 *
 * Mirrors cryptoService.ts encryptChatKeyWithMasterKey() — used for wrapping
 * a 32-byte chat key with the master key. MUST use this (not the string
 * variant) because the input is binary, not UTF-8.
 */
export async function encryptBytesWithAesGcm(
  data: Uint8Array,
  rawKeyBytes: Uint8Array,
): Promise<string> {
  const iv = cryptoApi.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH));
  const key = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(rawKeyBytes),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const encrypted = await cryptoApi.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(iv) },
    key,
    toArrayBuffer(data),
  );
  const cipherBytes = new Uint8Array(encrypted);
  const combined = new Uint8Array(iv.length + cipherBytes.length);
  combined.set(iv);
  combined.set(cipherBytes, iv.length);
  return bytesToBase64(combined);
}

export async function encryptWithAesGcmCombined(
  plaintext: string,
  rawKeyBytes: Uint8Array,
  associatedData?: string,
): Promise<string> {
  const iv = cryptoApi.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH));
  const key = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(rawKeyBytes),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const encrypted = await cryptoApi.subtle.encrypt(
    {
      name: "AES-GCM",
      iv: toArrayBuffer(iv),
      ...(associatedData ? { additionalData: toArrayBuffer(new TextEncoder().encode(associatedData)) } : {}),
    },
    key,
    new TextEncoder().encode(plaintext),
  );
  const cipherBytes = new Uint8Array(encrypted);
  const combined = new Uint8Array(iv.length + cipherBytes.length);
  combined.set(iv);
  combined.set(cipherBytes, iv.length);
  return bytesToBase64(combined);
}

/**
 * Hash an item key for zero-knowledge storage in Directus.
 *
 * Mirrors the browser's appSettingsMemoriesStore behaviour:
 *   SHA-256(`${appId}-${itemKey}-${timestamp}`).slice(0, 32) hex chars.
 *
 * The cleartext key is stored INSIDE the encrypted payload (_original_item_key)
 * so the CLI/browser can recover it on decrypt without the server ever seeing it.
 *
 * @param appId   - App identifier (e.g. "code")
 * @param itemKey - Human-readable key (e.g. "preferred_technologies")
 * @returns First 32 hex characters of SHA-256 hash
 */
export function hashItemKey(appId: string, itemKey: string): string {
  const raw = `${appId}-${itemKey}-${Date.now()}`;
  return createHash("sha256").update(raw).digest("hex").slice(0, 32);
}
