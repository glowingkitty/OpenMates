/*
 * Connected account CLI import helpers.
 *
 * Purpose: decrypt passcode-protected OMCA1 payloads and build destination-owned
 * encrypted connected-account rows for the currently logged-in CLI account.
 * Architecture: mirrors browser OAuth finalization without persisting plaintext.
 * Security: passcodes are interactive-only; token material is accepted only from
 * decrypted OMCA1 ciphertext and immediately re-encrypted with the destination
 * account master key.
 * Spec: docs/specs/connected-account-cli-import/spec.yml
 */

import { createHash, randomUUID, webcrypto } from "node:crypto";

import {
  base64ToBytes,
  bytesToBase64,
  encryptWithAesGcmCombined,
} from "./crypto.js";

const TRANSFER_PREFIX = "OMCA1.";
const SUPPORTED_KDF_ITERATIONS = 100_000;

interface EncryptedTransferEnvelope {
  version: 1;
  kdf: {
    name: "PBKDF2-SHA256";
    iterations: number;
    salt: string;
  };
  cipher: {
    name: "AES-256-GCM";
    iv: string;
    text: string;
  };
}

export interface ConnectedAccountCliTransferPayload {
  version: 1;
  provider_id: string;
  app_id: string;
  label: string;
  account_ref?: string;
  capabilities: string[];
  runtime_modes: Record<string, string>;
  refresh_token_bundle: Record<string, unknown>;
  created_at: string;
}

export interface EncryptedConnectedAccountImportRow {
  id: string;
  hashed_user_id: string;
  encrypted_provider_type: string;
  provider_type_hash: string;
  encrypted_account_label: string;
  encrypted_refresh_token_bundle: string;
  encrypted_capabilities: string;
  encrypted_app_permissions: string;
  encrypted_account_directory_hint: string;
}

export async function decryptConnectedAccountCliTransferPayload(
  encryptedPayload: string,
  passcode: string,
): Promise<ConnectedAccountCliTransferPayload> {
  if (!encryptedPayload.startsWith(TRANSFER_PREFIX)) {
    throw new Error("Connected account import payload must start with OMCA1.");
  }
  if (!passcode.trim()) {
    throw new Error("A passcode is required to import a connected account.");
  }

  const envelope = parseEnvelope(encryptedPayload.slice(TRANSFER_PREFIX.length));
  if (
    envelope.version !== 1 ||
    envelope.kdf.name !== "PBKDF2-SHA256" ||
    envelope.kdf.iterations !== SUPPORTED_KDF_ITERATIONS ||
    envelope.cipher.name !== "AES-256-GCM"
  ) {
    throw new Error("Unsupported connected account import payload format.");
  }

  try {
    const key = await deriveTransferKey(passcode, base64UrlToBytes(envelope.kdf.salt), envelope.kdf.iterations);
    const plaintext = await webcrypto.subtle.decrypt(
      { name: "AES-GCM", iv: toArrayBuffer(base64UrlToBytes(envelope.cipher.iv)) },
      key,
      toArrayBuffer(base64UrlToBytes(envelope.cipher.text)),
    );
    return validateTransferPayload(JSON.parse(new TextDecoder().decode(plaintext)));
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("Unsupported")) {
      throw error;
    }
    throw new Error("Could not decrypt connected account import payload. Check the passcode and payload.");
  }
}

export async function buildEncryptedConnectedAccountImportRow(params: {
  payload: ConnectedAccountCliTransferPayload;
  userId: string;
  masterKey: Uint8Array;
}): Promise<EncryptedConnectedAccountImportRow> {
  const accountId = randomUUID();
  const providerId = params.payload.provider_id;
  const appId = normalizeAppId(params.payload.app_id || appIdForProvider(providerId));
  const capabilities = normalizeCapabilities(params.payload.capabilities);
  const allowedActions = actionsForCapabilities(capabilities);
  const scopes = Array.isArray(params.payload.refresh_token_bundle.scopes)
    ? params.payload.refresh_token_bundle.scopes.filter((item): item is string => typeof item === "string")
    : [];
  const label = params.payload.label.trim() || defaultProviderLabel(providerId);
  const accountRef = params.payload.account_ref?.trim() || accountId;

  return {
    id: accountId,
    hashed_user_id: sha256Hex(params.userId),
    encrypted_provider_type: await encryptJsonOrString(providerId, params.masterKey),
    provider_type_hash: sha256Hex(providerId),
    encrypted_account_label: await encryptJsonOrString(label, params.masterKey),
    encrypted_refresh_token_bundle: await encryptJsonOrString(params.payload.refresh_token_bundle, params.masterKey),
    encrypted_capabilities: await encryptJsonOrString(capabilities, params.masterKey),
    encrypted_app_permissions: await encryptJsonOrString(
      {
        app_id: appId,
        allowed_actions: allowedActions,
        scopes,
      },
      params.masterKey,
    ),
    encrypted_account_directory_hint: await encryptJsonOrString(
      {
        account_ref: accountRef,
        label,
        capabilities,
        runtime_modes: Object.keys(params.payload.runtime_modes).length
          ? params.payload.runtime_modes
          : runtimeModesForActions(allowedActions),
      },
      params.masterKey,
    ),
  };
}

function parseEnvelope(encodedEnvelope: string): EncryptedTransferEnvelope {
  try {
    return JSON.parse(new TextDecoder().decode(base64UrlToBytes(encodedEnvelope))) as EncryptedTransferEnvelope;
  } catch {
    throw new Error("Connected account import payload is malformed.");
  }
}

function validateTransferPayload(value: unknown): ConnectedAccountCliTransferPayload {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Connected account import payload is malformed.");
  }
  const payload = value as Partial<ConnectedAccountCliTransferPayload>;
  if (payload.version !== 1) throw new Error("Unsupported connected account import payload format.");
  if (typeof payload.provider_id !== "string" || !payload.provider_id) throw new Error("Import payload is missing provider_id.");
  if (typeof payload.app_id !== "string" || !payload.app_id) throw new Error("Import payload is missing app_id.");
  if (typeof payload.label !== "string") throw new Error("Import payload is missing label.");
  if (!Array.isArray(payload.capabilities)) throw new Error("Import payload is missing capabilities.");
  if (!payload.runtime_modes || typeof payload.runtime_modes !== "object" || Array.isArray(payload.runtime_modes)) {
    throw new Error("Import payload is missing runtime_modes.");
  }
  if (
    !payload.refresh_token_bundle ||
    typeof payload.refresh_token_bundle !== "object" ||
    Array.isArray(payload.refresh_token_bundle) ||
    typeof payload.refresh_token_bundle.refresh_token !== "string" ||
    !payload.refresh_token_bundle.refresh_token
  ) {
    throw new Error("Import payload is missing refresh token material.");
  }
  return payload as ConnectedAccountCliTransferPayload;
}

async function deriveTransferKey(passcode: string, salt: Uint8Array, iterations: number): Promise<CryptoKey> {
  const keyMaterial = await webcrypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(passcode),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return webcrypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: toArrayBuffer(salt),
      iterations,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"],
  );
}

async function encryptJsonOrString(value: unknown, masterKey: Uint8Array): Promise<string> {
  const plaintext = typeof value === "string" ? value : JSON.stringify(value);
  return encryptWithAesGcmCombined(plaintext, masterKey);
}

function normalizeCapabilities(value: unknown): string[] {
  if (!Array.isArray(value)) return ["read"];
  const capabilities = value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  return capabilities.length ? Array.from(new Set(capabilities)) : ["read"];
}

function actionsForCapabilities(capabilities: string[]): string[] {
  const actions = new Set<string>();
  for (const capability of capabilities) {
    if (capability === "read") actions.add("read");
    if (capability === "write") {
      actions.add("write");
      actions.add("update");
    }
    if (capability === "delete") actions.add("delete");
  }
  return actions.size ? Array.from(actions) : ["read"];
}

function runtimeModesForActions(actions: string[]): Record<string, string> {
  return Object.fromEntries(actions.map((action) => [action, action === "read" ? "allow_automatically" : "always_ask"]));
}

function normalizeAppId(appId: string): string {
  return appId === "google_calendar" ? "calendar" : appId;
}

function appIdForProvider(providerId: string): string {
  return providerId === "google_calendar" ? "calendar" : providerId;
}

function defaultProviderLabel(providerId: string): string {
  return providerId === "google_calendar" ? "Google Calendar" : "Connected account";
}

function sha256Hex(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function base64UrlToBytes(value: string): Uint8Array {
  return base64ToBytes(value.replace(/-/g, "+").replace(/_/g, "/"));
}

function toArrayBuffer(input: Uint8Array): ArrayBuffer {
  const output = new ArrayBuffer(input.byteLength);
  new Uint8Array(output).set(input);
  return output;
}

export function encodeConnectedAccountCliTransferEnvelopeForTests(envelope: EncryptedTransferEnvelope): string {
  return `${TRANSFER_PREFIX}${bytesToBase64(new TextEncoder().encode(JSON.stringify(envelope)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "")}`;
}
