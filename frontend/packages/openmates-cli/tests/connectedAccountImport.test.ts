/**
 * Unit tests for connected account CLI import crypto helpers.
 *
 * These tests build real OMCA1 envelopes without network access, then verify
 * decryption and destination-account re-encryption. Plaintext token material
 * must only exist inside local test fixtures and decrypted helper results.
 *
 * Run: cd frontend/packages/openmates-cli && npm run test:unit:connected-account-import
 */

import { webcrypto } from "node:crypto";
import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  buildEncryptedConnectedAccountImportRow,
  decryptConnectedAccountCliTransferPayload,
  type ConnectedAccountCliTransferPayload,
} from "../src/connectedAccountImport.ts";
import { decryptWithAesGcmCombined } from "../src/crypto.ts";

const KDF_ITERATIONS = 100_000;

describe("connected account import helpers", () => {
  it("decrypts OMCA1 payloads and re-encrypts destination-owned rows", async () => {
    const payload: ConnectedAccountCliTransferPayload = {
      version: 1,
      provider_id: "google_calendar",
      app_id: "calendar",
      label: "Work Calendar",
      account_ref: "provider-account-ref",
      capabilities: ["read", "write"],
      runtime_modes: {
        read: "allow_automatically",
        write: "always_ask",
      },
      refresh_token_bundle: {
        refresh_token: "refresh-secret",
        scopes: ["https://www.googleapis.com/auth/calendar.events"],
      },
      created_at: "2026-06-21T00:00:00.000Z",
    };

    const encryptedPayload = await encryptOmca1PayloadForTest(payload, "test-passcode");
    assert.equal(encryptedPayload.includes("refresh-secret"), false);

    const decrypted = await decryptConnectedAccountCliTransferPayload(encryptedPayload, "test-passcode");
    assert.deepEqual(decrypted, payload);

    await assert.rejects(
      decryptConnectedAccountCliTransferPayload(encryptedPayload, "wrong-passcode"),
      /Could not decrypt connected account import payload/,
    );

    const masterKey = new Uint8Array(32).fill(7);
    const row = await buildEncryptedConnectedAccountImportRow({
      payload: decrypted,
      userId: "destination-user",
      masterKey,
    });

    const serializedRow = JSON.stringify(row);
    assert.equal(serializedRow.includes("refresh-secret"), false);
    assert.equal(serializedRow.includes("provider-account-ref"), false);
    assert.equal(serializedRow.includes("Work Calendar"), false);

    assert.equal(await decryptWithAesGcmCombined(row.encrypted_provider_type, masterKey), "google_calendar");
    assert.equal(await decryptWithAesGcmCombined(row.encrypted_account_label, masterKey), "Work Calendar");
    assert.deepEqual(
      JSON.parse((await decryptWithAesGcmCombined(row.encrypted_refresh_token_bundle, masterKey)) ?? "{}"),
      payload.refresh_token_bundle,
    );
    assert.deepEqual(
      JSON.parse((await decryptWithAesGcmCombined(row.encrypted_capabilities, masterKey)) ?? "[]"),
      ["read", "write"],
    );
  });
});

async function encryptOmca1PayloadForTest(
  payload: ConnectedAccountCliTransferPayload,
  passcode: string,
): Promise<string> {
  const salt = webcrypto.getRandomValues(new Uint8Array(16));
  const iv = webcrypto.getRandomValues(new Uint8Array(12));
  const keyMaterial = await webcrypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(passcode),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  const key = await webcrypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: toArrayBuffer(salt),
      iterations: KDF_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"],
  );
  const ciphertext = await webcrypto.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(iv) },
    key,
    new TextEncoder().encode(JSON.stringify(payload)),
  );
  const envelope = {
    version: 1,
    kdf: {
      name: "PBKDF2-SHA256",
      iterations: KDF_ITERATIONS,
      salt: base64UrlEncode(salt),
    },
    cipher: {
      name: "AES-256-GCM",
      iv: base64UrlEncode(iv),
      text: base64UrlEncode(new Uint8Array(ciphertext)),
    },
  };
  return `OMCA1.${base64UrlEncode(new TextEncoder().encode(JSON.stringify(envelope)))}`;
}

function base64UrlEncode(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function toArrayBuffer(input: Uint8Array): ArrayBuffer {
  const output = new ArrayBuffer(input.byteLength);
  new Uint8Array(output).set(input);
  return output;
}
