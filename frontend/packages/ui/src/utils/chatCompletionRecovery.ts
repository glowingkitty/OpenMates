/**
 * Browser-compatible chat completion recovery cryptography.
 *
 * Clients deterministically derive an X25519 recovery keypair from the local
 * chat key. Only the public key and authenticated sealed envelopes cross the
 * server boundary; private and plaintext material remain client-side.
 */

import nacl from "tweetnacl";

const PROTOCOL_VERSION = 1;
const MAX_PAYLOAD_BYTES = 16 * 1024 * 1024;
const KEY_BYTES = 32;
const NONCE_BYTES = 12;
const AAD_PREFIX = new TextEncoder().encode("OMCR1");
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

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

function toArrayBuffer(input: Uint8Array): ArrayBuffer {
  const output = new ArrayBuffer(input.byteLength);
  new Uint8Array(output).set(input);
  return output;
}

function encodeBase64Url(input: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < input.length; offset += chunkSize) {
    const chunk = input.subarray(offset, offset + chunkSize);
    for (let index = 0; index < chunk.length; index += 1) {
      binary += String.fromCharCode(chunk[index]);
    }
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decodeBase64Url(input: string, field: string, expectedLength?: number): Uint8Array {
  if (!input || input.includes("=") || !/^[A-Za-z0-9_-]+$/.test(input)) {
    throw new Error(`${field} must be non-empty unpadded base64url`);
  }
  const standard = input.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat(-input.length & 3);
  let binary: string;
  try {
    binary = atob(standard);
  } catch {
    throw new Error(`${field} must be canonical base64url`);
  }
  const decoded = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  if (encodeBase64Url(decoded) !== input) {
    throw new Error(`${field} must be canonical base64url`);
  }
  if (expectedLength !== undefined && decoded.length !== expectedLength) {
    throw new Error(`${field} must decode to ${expectedLength} bytes`);
  }
  return decoded;
}

function uint32(value: number, field: string): Uint8Array {
  if (!Number.isInteger(value) || value < 0 || value > 0xffffffff) {
    throw new Error(`${field} must be an unsigned 32-bit integer`);
  }
  const encoded = new Uint8Array(4);
  new DataView(encoded.buffer).setUint32(0, value, false);
  return encoded;
}

function canonicalUuid(value: string, field: string): Uint8Array {
  if (!UUID_PATTERN.test(value)) {
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
  return new Uint8Array(await crypto.subtle.digest("SHA-256", toArrayBuffer(input)));
}

async function hkdfSha256(input: Uint8Array, salt: Uint8Array, info: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", toArrayBuffer(input), "HKDF", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt: toArrayBuffer(salt),
      info: toArrayBuffer(info),
    },
    key,
    256,
  ));
}

export async function deriveChatCompletionRecoveryKeypair(
  chatKey: string,
  chatId: string,
  keyVersion: number,
): Promise<{ privateKey: string; publicKey: string }> {
  const rawChatKey = decodeBase64Url(chatKey, "chat_key", KEY_BYTES);
  const salt = await sha256(new TextEncoder().encode("openmates:chat-recovery:v1"));
  const info = concatBytes(lengthPrefix(canonicalUuid(chatId, "chat_id")), uint32(keyVersion, "key_version"));
  const privateKey = await hkdfSha256(rawChatKey, salt, info);
  return {
    privateKey: encodeBase64Url(privateKey),
    publicKey: encodeBase64Url(nacl.scalarMult.base(privateKey)),
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
  return encodeBase64Url(concatBytes(
    AAD_PREFIX,
    lengthPrefix(canonicalUuid(values.owner_id, "owner_id")),
    lengthPrefix(canonicalUuid(values.chat_id, "chat_id")),
    lengthPrefix(canonicalUuid(values.turn_id, "turn_id")),
    lengthPrefix(canonicalUuid(values.job_id, "job_id")),
    lengthPrefix(canonicalUuid(values.assistant_message_id, "assistant_message_id")),
    uint32(values.key_version, "key_version"),
  ));
}

function associatedData(identity: ChatCompletionRecoveryIdentity): Uint8Array {
  return decodeBase64Url(buildRecoveryAssociatedData({
    owner_id: identity.ownerId,
    chat_id: identity.chatId,
    turn_id: identity.turnId,
    job_id: identity.jobId,
    assistant_message_id: identity.assistantMessageId,
    key_version: identity.keyVersion,
  }), "associated_data");
}

async function envelopeKey(sharedSecret: Uint8Array, aad: Uint8Array): Promise<Uint8Array> {
  if (sharedSecret.every((value) => value === 0)) {
    throw new Error("X25519 shared secret must not be all zero");
  }
  const salt = await sha256(new TextEncoder().encode("openmates:chat-recovery-envelope:v1"));
  return hkdfSha256(sharedSecret, salt, await sha256(aad));
}

export async function sealChatCompletionRecoveryPayload(
  plaintext: Uint8Array,
  options: ChatCompletionRecoveryIdentity & {
    recoveryPublicKey: string;
    ephemeralPrivateKey?: string;
    nonce?: string;
  },
): Promise<ChatCompletionRecoveryEnvelope> {
  if (plaintext.length > MAX_PAYLOAD_BYTES) {
    throw new Error(`plaintext must be no larger than ${MAX_PAYLOAD_BYTES}`);
  }
  const recoveryPublicKey = decodeBase64Url(options.recoveryPublicKey, "recovery_public_key", KEY_BYTES);
  const ephemeralPrivateKey = options.ephemeralPrivateKey
    ? decodeBase64Url(options.ephemeralPrivateKey, "ephemeral_private_key", KEY_BYTES)
    : crypto.getRandomValues(new Uint8Array(KEY_BYTES));
  const nonce = options.nonce
    ? decodeBase64Url(options.nonce, "nonce", NONCE_BYTES)
    : crypto.getRandomValues(new Uint8Array(NONCE_BYTES));
  const ephemeralPublicKey = nacl.scalarMult.base(ephemeralPrivateKey);
  const aad = associatedData(options);
  const key = await crypto.subtle.importKey(
    "raw",
    toArrayBuffer(await envelopeKey(nacl.scalarMult(ephemeralPrivateKey, recoveryPublicKey), aad)),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(nonce), additionalData: toArrayBuffer(aad) },
    key,
    toArrayBuffer(plaintext),
  ));
  return {
    v: PROTOCOL_VERSION,
    epk: encodeBase64Url(ephemeralPublicKey),
    nonce: encodeBase64Url(nonce),
    ciphertext: encodeBase64Url(ciphertext),
  };
}

export async function openChatCompletionRecoveryEnvelope(
  envelope: ChatCompletionRecoveryEnvelope,
  options: ChatCompletionRecoveryIdentity & { recoveryPrivateKey: string },
): Promise<Uint8Array> {
  if (Object.keys(envelope).sort().join(",") !== "ciphertext,epk,nonce,v" || envelope.v !== PROTOCOL_VERSION) {
    throw new Error("invalid recovery envelope fields or version");
  }
  const recoveryPrivateKey = decodeBase64Url(options.recoveryPrivateKey, "recovery_private_key", KEY_BYTES);
  const ephemeralPublicKey = decodeBase64Url(envelope.epk, "epk", KEY_BYTES);
  const nonce = decodeBase64Url(envelope.nonce, "nonce", NONCE_BYTES);
  const ciphertext = decodeBase64Url(envelope.ciphertext, "ciphertext");
  if (ciphertext.length < 16 || ciphertext.length - 16 > MAX_PAYLOAD_BYTES) {
    throw new Error("ciphertext payload size is invalid");
  }
  const aad = associatedData(options);
  const key = await crypto.subtle.importKey(
    "raw",
    toArrayBuffer(await envelopeKey(nacl.scalarMult(recoveryPrivateKey, ephemeralPublicKey), aad)),
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );
  return new Uint8Array(await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: toArrayBuffer(nonce), additionalData: toArrayBuffer(aad) },
    key,
    toArrayBuffer(ciphertext),
  ));
}
