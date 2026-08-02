/*
 * End-to-end crypto for the Project remote-access live bridge.
 *
 * Project keys authenticate an ephemeral X25519 handshake between a requesting
 * first-party client and the source CLI. The backend relays public handshakes
 * and AES-GCM envelopes but cannot derive keys or inspect filesystem plaintext.
 *
 * Spec: docs/specs/cli-remote-access-live-bridge/spec.yml
 */

import { webcrypto } from "node:crypto";
import nacl from "tweetnacl";

const cryptoApi = globalThis.crypto ?? webcrypto;
const PROTOCOL_VERSION = 1;
const KEY_BYTES = 32;
const NONCE_BYTES = 12;
const MAX_PAYLOAD_BYTES = 200 * 1024;

export type RemoteAccessRole = "requester" | "source";
export type RemoteAccessDirection = "request" | "result";

export interface RemoteAccessCryptoIdentity {
  ownerId: string;
  projectId: string;
  sourceId: string;
  sourceSessionId: string;
  requestingClientId: string;
  keyEpoch: number;
}

export interface RemoteAccessHandshake {
  version: 1;
  role: RemoteAccessRole;
  publicKey: string;
  authenticationTag: string;
}

export interface RemoteAccessEnvelope {
  version: 1;
  nonce: string;
  ciphertext: string;
}

export class RemoteAccessReplayGuard {
  private readonly seen = new Set<string>();

  assertUnused(nonce: string): void {
    if (this.seen.has(nonce)) throw new Error("replayed remote-access envelope");
  }

  markUsed(nonce: string): void {
    this.seen.add(nonce);
  }
}

export async function createRemoteAccessHandshake(
  projectKey: Uint8Array,
  identity: RemoteAccessCryptoIdentity,
  role: RemoteAccessRole,
): Promise<{ privateKey: string; handshake: RemoteAccessHandshake }> {
  assertProjectKey(projectKey);
  validateIdentity(identity);
  const privateKey = cryptoApi.getRandomValues(new Uint8Array(KEY_BYTES));
  const publicKey = nacl.scalarMult.base(privateKey);
  const publicKeyText = toBase64Url(publicKey);
  return {
    privateKey: toBase64Url(privateKey),
    handshake: {
      version: PROTOCOL_VERSION,
      role,
      publicKey: publicKeyText,
      authenticationTag: await authenticateHandshake(projectKey, identity, role, publicKeyText),
    },
  };
}

export async function deriveRemoteAccessSessionKey(
  projectKey: Uint8Array,
  identity: RemoteAccessCryptoIdentity,
  localRole: RemoteAccessRole,
  localPrivateKey: string,
  localHandshake: RemoteAccessHandshake,
  remoteHandshake: RemoteAccessHandshake,
): Promise<Uint8Array> {
  assertProjectKey(projectKey);
  validateIdentity(identity);
  const remoteRole: RemoteAccessRole = localRole === "requester" ? "source" : "requester";
  if (localHandshake.role !== localRole || remoteHandshake.role !== remoteRole) {
    throw new Error("handshake authentication failed");
  }
  await verifyHandshake(projectKey, identity, localHandshake);
  await verifyHandshake(projectKey, identity, remoteHandshake);
  const privateKey = fromBase64Url(localPrivateKey, KEY_BYTES);
  const remotePublicKey = fromBase64Url(remoteHandshake.publicKey, KEY_BYTES);
  const sharedSecret = nacl.scalarMult(privateKey, remotePublicKey);
  if (sharedSecret.every((value) => value === 0)) throw new Error("handshake shared secret invalid");
  const requesterPublicKey = localRole === "requester" ? localHandshake.publicKey : remoteHandshake.publicKey;
  const sourcePublicKey = localRole === "source" ? localHandshake.publicKey : remoteHandshake.publicKey;
  return hkdf(
    sharedSecret,
    new TextEncoder().encode("openmates:project-remote-access:v1"),
    await digest(transcript(identity, requesterPublicKey, sourcePublicKey)),
  );
}

export async function sealRemoteAccessEnvelope(
  sessionKey: Uint8Array,
  identity: RemoteAccessCryptoIdentity,
  requestId: string,
  direction: RemoteAccessDirection,
  plaintext: Uint8Array,
): Promise<RemoteAccessEnvelope> {
  assertSessionKey(sessionKey);
  validateIdentity(identity);
  if (!requestId || plaintext.length > MAX_PAYLOAD_BYTES) throw new Error("invalid remote-access envelope payload");
  const nonce = cryptoApi.getRandomValues(new Uint8Array(NONCE_BYTES));
  const key = await cryptoApi.subtle.importKey("raw", arrayBuffer(sessionKey), "AES-GCM", false, ["encrypt"]);
  const ciphertext = await cryptoApi.subtle.encrypt(
    { name: "AES-GCM", iv: arrayBuffer(nonce), additionalData: arrayBuffer(envelopeAad(identity, requestId, direction)) },
    key,
    arrayBuffer(plaintext),
  );
  return { version: PROTOCOL_VERSION, nonce: toBase64Url(nonce), ciphertext: toBase64Url(new Uint8Array(ciphertext)) };
}

export async function openRemoteAccessEnvelope(
  sessionKey: Uint8Array,
  identity: RemoteAccessCryptoIdentity,
  requestId: string,
  direction: RemoteAccessDirection,
  envelope: RemoteAccessEnvelope,
  replayGuard: RemoteAccessReplayGuard,
): Promise<Uint8Array> {
  assertSessionKey(sessionKey);
  validateIdentity(identity);
  if (envelope.version !== PROTOCOL_VERSION || !requestId) throw new Error("invalid remote-access envelope");
  replayGuard.assertUnused(envelope.nonce);
  const nonce = fromBase64Url(envelope.nonce, NONCE_BYTES);
  const ciphertext = fromBase64Url(envelope.ciphertext);
  if (ciphertext.length > MAX_PAYLOAD_BYTES + 16) throw new Error("invalid remote-access envelope");
  try {
    const key = await cryptoApi.subtle.importKey("raw", arrayBuffer(sessionKey), "AES-GCM", false, ["decrypt"]);
    const plaintext = await cryptoApi.subtle.decrypt(
      { name: "AES-GCM", iv: arrayBuffer(nonce), additionalData: arrayBuffer(envelopeAad(identity, requestId, direction)) },
      key,
      arrayBuffer(ciphertext),
    );
    replayGuard.markUsed(envelope.nonce);
    return new Uint8Array(plaintext);
  } catch {
    throw new Error("envelope authentication failed");
  }
}

async function authenticateHandshake(
  projectKey: Uint8Array,
  identity: RemoteAccessCryptoIdentity,
  role: RemoteAccessRole,
  publicKey: string,
): Promise<string> {
  const key = await cryptoApi.subtle.importKey("raw", arrayBuffer(projectKey), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const tag = await cryptoApi.subtle.sign("HMAC", key, arrayBuffer(handshakeAad(identity, role, publicKey)));
  return toBase64Url(new Uint8Array(tag));
}

async function verifyHandshake(
  projectKey: Uint8Array,
  identity: RemoteAccessCryptoIdentity,
  handshake: RemoteAccessHandshake,
): Promise<void> {
  if (handshake.version !== PROTOCOL_VERSION) throw new Error("handshake authentication failed");
  fromBase64Url(handshake.publicKey, KEY_BYTES);
  const expected = await authenticateHandshake(projectKey, identity, handshake.role, handshake.publicKey);
  const actualBytes = fromBase64Url(handshake.authenticationTag, KEY_BYTES);
  const expectedBytes = fromBase64Url(expected, KEY_BYTES);
  if (!constantTimeEqual(actualBytes, expectedBytes)) throw new Error("handshake authentication failed");
}

function handshakeAad(
  identity: RemoteAccessCryptoIdentity,
  role: RemoteAccessRole,
  publicKey: string,
): Uint8Array {
  return encode(["OMRA-HANDSHAKE-1", ...identityValues(identity), role, publicKey]);
}

function transcript(
  identity: RemoteAccessCryptoIdentity,
  requesterPublicKey: string,
  sourcePublicKey: string,
): Uint8Array {
  return encode(["OMRA-TRANSCRIPT-1", ...identityValues(identity), requesterPublicKey, sourcePublicKey]);
}

function envelopeAad(
  identity: RemoteAccessCryptoIdentity,
  requestId: string,
  direction: RemoteAccessDirection,
): Uint8Array {
  return encode(["OMRA-ENVELOPE-1", ...identityValues(identity), requestId, direction]);
}

function identityValues(identity: RemoteAccessCryptoIdentity): Array<string | number> {
  return [
    identity.ownerId,
    identity.projectId,
    identity.sourceId,
    identity.sourceSessionId,
    identity.requestingClientId,
    identity.keyEpoch,
  ];
}

function encode(values: Array<string | number>): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(values));
}

async function hkdf(secret: Uint8Array, salt: Uint8Array, info: Uint8Array): Promise<Uint8Array> {
  const key = await cryptoApi.subtle.importKey("raw", arrayBuffer(secret), "HKDF", false, ["deriveBits"]);
  const bits = await cryptoApi.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt: arrayBuffer(salt), info: arrayBuffer(info) },
    key,
    256,
  );
  return new Uint8Array(bits);
}

async function digest(value: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await cryptoApi.subtle.digest("SHA-256", arrayBuffer(value)));
}

function validateIdentity(identity: RemoteAccessCryptoIdentity): void {
  const strings = [identity.ownerId, identity.projectId, identity.sourceId, identity.sourceSessionId, identity.requestingClientId];
  if (strings.some((value) => !value || value.length > 128) || !Number.isInteger(identity.keyEpoch) || identity.keyEpoch < 1) {
    throw new Error("invalid remote-access identity");
  }
}

function assertProjectKey(value: Uint8Array): void {
  if (value.length !== KEY_BYTES) throw new Error("Project key must be 32 bytes");
}

function assertSessionKey(value: Uint8Array): void {
  if (value.length !== KEY_BYTES) throw new Error("source-session key must be 32 bytes");
}

function toBase64Url(value: Uint8Array): string {
  return Buffer.from(value).toString("base64url");
}

function fromBase64Url(value: string, expectedLength?: number): Uint8Array {
  if (!value || value.includes("=") || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error("invalid remote-access key or envelope field");
  }
  const decoded = new Uint8Array(Buffer.from(value, "base64url"));
  if (toBase64Url(decoded) !== value || (expectedLength !== undefined && decoded.length !== expectedLength)) {
    throw new Error("invalid remote-access key or envelope field");
  }
  return decoded;
}

function constantTimeEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index]! ^ right[index]!;
  return difference === 0;
}

function arrayBuffer(value: Uint8Array): ArrayBuffer {
  return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength) as ArrayBuffer;
}
