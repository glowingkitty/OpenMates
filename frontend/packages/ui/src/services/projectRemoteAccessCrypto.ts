/*
 * Browser cryptography for the Project remote-access live bridge.
 *
 * The Project key authenticates ephemeral X25519 peer handshakes. Derived
 * AES-GCM session keys encrypt filesystem results end-to-end between the web
 * client and CLI; the backend receives only routing metadata and ciphertext.
 * Spec: docs/specs/cli-remote-access-live-bridge/spec.yml
 */

import nacl from "tweetnacl";

const PROTOCOL_VERSION = 1;
const KEY_BYTES = 32;
const NONCE_BYTES = 12;
const MAX_PAYLOAD_BYTES = 200 * 1024;

export type ProjectRemoteAccessRole = "requester" | "source";
export type ProjectRemoteAccessDirection = "request" | "result";

export interface ProjectRemoteAccessCryptoIdentity {
  ownerId: string;
  projectId: string;
  sourceId: string;
  sourceSessionId: string;
  requestingClientId: string;
  keyEpoch: number;
}

export interface ProjectRemoteAccessHandshake {
  version: 1;
  role: ProjectRemoteAccessRole;
  publicKey: string;
  authenticationTag: string;
}

export interface ProjectRemoteAccessEnvelope {
  version: 1;
  nonce: string;
  ciphertext: string;
}

export class ProjectRemoteAccessReplayGuard {
  private readonly seen = new Set<string>();

  assertUnused(nonce: string): void {
    if (this.seen.has(nonce)) throw new Error("replayed remote-access envelope");
  }

  markUsed(nonce: string): void {
    this.seen.add(nonce);
  }
}

export async function createProjectRemoteAccessHandshake(
  projectKey: Uint8Array,
  identity: ProjectRemoteAccessCryptoIdentity,
  role: ProjectRemoteAccessRole,
): Promise<{ privateKey: string; handshake: ProjectRemoteAccessHandshake }> {
  assertKey(projectKey, "Project");
  validateIdentity(identity);
  const privateKey = crypto.getRandomValues(new Uint8Array(KEY_BYTES));
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

export async function deriveProjectRemoteAccessSessionKey(
  projectKey: Uint8Array,
  identity: ProjectRemoteAccessCryptoIdentity,
  localRole: ProjectRemoteAccessRole,
  localPrivateKey: string,
  localHandshake: ProjectRemoteAccessHandshake,
  remoteHandshake: ProjectRemoteAccessHandshake,
): Promise<Uint8Array> {
  assertKey(projectKey, "Project");
  validateIdentity(identity);
  const remoteRole: ProjectRemoteAccessRole = localRole === "requester" ? "source" : "requester";
  if (localHandshake.role !== localRole || remoteHandshake.role !== remoteRole) {
    throw new Error("handshake authentication failed");
  }
  await verifyHandshake(projectKey, identity, localHandshake);
  await verifyHandshake(projectKey, identity, remoteHandshake);
  const sharedSecret = nacl.scalarMult(
    fromBase64Url(localPrivateKey, KEY_BYTES),
    fromBase64Url(remoteHandshake.publicKey, KEY_BYTES),
  );
  if (sharedSecret.every((value) => value === 0)) throw new Error("handshake shared secret invalid");
  const requesterPublicKey = localRole === "requester" ? localHandshake.publicKey : remoteHandshake.publicKey;
  const sourcePublicKey = localRole === "source" ? localHandshake.publicKey : remoteHandshake.publicKey;
  return hkdf(
    sharedSecret,
    new TextEncoder().encode("openmates:project-remote-access:v1"),
    await digest(transcript(identity, requesterPublicKey, sourcePublicKey)),
  );
}

export async function openProjectRemoteAccessEnvelope(
  sessionKey: Uint8Array,
  identity: ProjectRemoteAccessCryptoIdentity,
  requestId: string,
  direction: ProjectRemoteAccessDirection,
  envelope: ProjectRemoteAccessEnvelope,
  replayGuard: ProjectRemoteAccessReplayGuard,
): Promise<Uint8Array> {
  assertKey(sessionKey, "source-session");
  validateIdentity(identity);
  if (envelope.version !== PROTOCOL_VERSION || !requestId) throw new Error("invalid remote-access envelope");
  replayGuard.assertUnused(envelope.nonce);
  const nonce = fromBase64Url(envelope.nonce, NONCE_BYTES);
  const ciphertext = fromBase64Url(envelope.ciphertext);
  if (ciphertext.length > MAX_PAYLOAD_BYTES + 16) throw new Error("invalid remote-access envelope");
  try {
    const key = await crypto.subtle.importKey("raw", toArrayBuffer(sessionKey), "AES-GCM", false, ["decrypt"]);
    const plaintext = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: toArrayBuffer(nonce),
        additionalData: toArrayBuffer(envelopeAad(identity, requestId, direction)),
      },
      key,
      toArrayBuffer(ciphertext),
    );
    replayGuard.markUsed(envelope.nonce);
    return new Uint8Array(plaintext);
  } catch {
    throw new Error("envelope authentication failed");
  }
}

async function authenticateHandshake(
  projectKey: Uint8Array,
  identity: ProjectRemoteAccessCryptoIdentity,
  role: ProjectRemoteAccessRole,
  publicKey: string,
): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    toArrayBuffer(projectKey),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const tag = await crypto.subtle.sign("HMAC", key, toArrayBuffer(handshakeAad(identity, role, publicKey)));
  return toBase64Url(new Uint8Array(tag));
}

async function verifyHandshake(
  projectKey: Uint8Array,
  identity: ProjectRemoteAccessCryptoIdentity,
  handshake: ProjectRemoteAccessHandshake,
): Promise<void> {
  if (handshake.version !== PROTOCOL_VERSION) throw new Error("handshake authentication failed");
  fromBase64Url(handshake.publicKey, KEY_BYTES);
  const expected = fromBase64Url(
    await authenticateHandshake(projectKey, identity, handshake.role, handshake.publicKey),
    KEY_BYTES,
  );
  const actual = fromBase64Url(handshake.authenticationTag, KEY_BYTES);
  if (!constantTimeEqual(actual, expected)) throw new Error("handshake authentication failed");
}

function handshakeAad(
  identity: ProjectRemoteAccessCryptoIdentity,
  role: ProjectRemoteAccessRole,
  publicKey: string,
): Uint8Array {
  return encode(["OMRA-HANDSHAKE-1", ...identityValues(identity), role, publicKey]);
}

function transcript(
  identity: ProjectRemoteAccessCryptoIdentity,
  requesterPublicKey: string,
  sourcePublicKey: string,
): Uint8Array {
  return encode(["OMRA-TRANSCRIPT-1", ...identityValues(identity), requesterPublicKey, sourcePublicKey]);
}

function envelopeAad(
  identity: ProjectRemoteAccessCryptoIdentity,
  requestId: string,
  direction: ProjectRemoteAccessDirection,
): Uint8Array {
  return encode(["OMRA-ENVELOPE-1", ...identityValues(identity), requestId, direction]);
}

function identityValues(identity: ProjectRemoteAccessCryptoIdentity): Array<string | number> {
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
  const key = await crypto.subtle.importKey("raw", toArrayBuffer(secret), "HKDF", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt: toArrayBuffer(salt), info: toArrayBuffer(info) },
    key,
    256,
  );
  return new Uint8Array(bits);
}

async function digest(value: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", toArrayBuffer(value)));
}

function validateIdentity(identity: ProjectRemoteAccessCryptoIdentity): void {
  const strings = [identity.ownerId, identity.projectId, identity.sourceId, identity.sourceSessionId, identity.requestingClientId];
  if (strings.some((value) => !value || value.length > 128) || !Number.isInteger(identity.keyEpoch) || identity.keyEpoch < 1) {
    throw new Error("invalid remote-access identity");
  }
}

function assertKey(value: Uint8Array, label: string): void {
  if (value.length !== KEY_BYTES) throw new Error(`${label} key must be 32 bytes`);
}

function toBase64Url(value: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < value.length; index += 1) binary += String.fromCharCode(value[index]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(value: string, expectedLength?: number): Uint8Array {
  if (!value || value.includes("=") || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error("invalid remote-access key or envelope field");
  }
  const standard = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat(-value.length & 3);
  let binary: string;
  try {
    binary = atob(standard);
  } catch {
    throw new Error("invalid remote-access key or envelope field");
  }
  const decoded = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  if (toBase64Url(decoded) !== value || (expectedLength !== undefined && decoded.length !== expectedLength)) {
    throw new Error("invalid remote-access key or envelope field");
  }
  return decoded;
}

function constantTimeEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

function toArrayBuffer(value: Uint8Array): ArrayBuffer {
  const output = new ArrayBuffer(value.byteLength);
  new Uint8Array(output).set(value);
  return output;
}
