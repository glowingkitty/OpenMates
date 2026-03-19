// tests/shareEncryption.test.ts
/**
 * Unit tests for share link encryption — verifying the CLI produces blobs
 * that match the web app's shareEncryption.ts and embedShareEncryption.ts.
 *
 * Since the algorithm is a pure Node.js port of the web app's browser crypto,
 * the key property tested is round-trip correctness: the same inputs always
 * produce blobs that decode back to the same key, regardless of the random IV.
 *
 * Run: node --test --experimental-strip-types tests/shareEncryption.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import {
  generateChatShareBlob,
  generateEmbedShareBlob,
  deriveWebOrigin,
  buildChatShareUrl,
  buildEmbedShareUrl,
} from "../src/shareEncryption.ts";

const crypto = webcrypto as unknown as Crypto;

// ── Helpers ─────────────────────────────────────────────────────────────

function randomKey(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(32));
}

/** Lightweight round-trip: decrypt the blob using the same algorithm */
async function decryptChatBlob(
  chatId: string,
  blob: string,
): Promise<{ chat_encryption_key: string; duration_seconds: number; pwd: number }> {
  // Mirrors decryptShareKeyBlob from shareEncryption.ts
  const enc = new TextEncoder();
  const dec = new TextDecoder();

  // Derive key from chatId (PBKDF2, same params)
  const material = await crypto.subtle.importKey(
    "raw", enc.encode(chatId), "PBKDF2", false, ["deriveKey"],
  );
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: enc.encode("openmates-share-v1"), iterations: 100000, hash: "SHA-256" },
    material, { name: "AES-GCM", length: 256 }, false, ["decrypt"],
  );

  // base64url decode
  let b64 = blob.replace(/-/g, "+").replace(/_/g, "/");
  while (b64.length % 4) b64 += "=";
  const combined = new Uint8Array(Buffer.from(b64, "base64"));

  const iv = combined.slice(0, 12);
  const ct = combined.slice(12);
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv },
    key,
    ct,
  );

  const params = new URLSearchParams(dec.decode(plaintext));
  return {
    chat_encryption_key: params.get("chat_encryption_key") ?? "",
    duration_seconds: parseInt(params.get("duration_seconds") ?? "0", 10),
    pwd: parseInt(params.get("pwd") ?? "0", 10),
  };
}

async function decryptEmbedBlob(
  embedId: string,
  blob: string,
): Promise<{ embed_encryption_key: string; duration_seconds: number; pwd: number }> {
  const enc = new TextEncoder();
  const dec = new TextDecoder();

  const material = await crypto.subtle.importKey(
    "raw", enc.encode(embedId), "PBKDF2", false, ["deriveKey"],
  );
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: enc.encode("openmates-share-v1"), iterations: 100000, hash: "SHA-256" },
    material, { name: "AES-GCM", length: 256 }, false, ["decrypt"],
  );

  let b64 = blob.replace(/-/g, "+").replace(/_/g, "/");
  while (b64.length % 4) b64 += "=";
  const combined = new Uint8Array(Buffer.from(b64, "base64"));

  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: combined.slice(0, 12) },
    key,
    combined.slice(12),
  );

  const params = new URLSearchParams(dec.decode(plaintext));
  return {
    embed_encryption_key: params.get("embed_encryption_key") ?? "",
    duration_seconds: parseInt(params.get("duration_seconds") ?? "0", 10),
    pwd: parseInt(params.get("pwd") ?? "0", 10),
  };
}

// ── Chat share blob ─────────────────────────────────────────────────────

describe("generateChatShareBlob", () => {
  it("produces a non-empty URL-safe base64 blob", async () => {
    const chatId = "550e8400-e29b-41d4-a716-446655440000";
    const chatKey = randomKey();
    const blob = await generateChatShareBlob(chatId, chatKey);
    assert.ok(blob.length > 0, "blob should not be empty");
    assert.ok(!blob.includes("+") && !blob.includes("/"), "should be URL-safe");
  });

  it("round-trips the chat key (no expiry, no password)", async () => {
    const chatId = "test-chat-id-round-trip";
    const chatKey = randomKey();
    const chatKeyB64 = Buffer.from(chatKey).toString("base64");

    const blob = await generateChatShareBlob(chatId, chatKey, 0);
    const decoded = await decryptChatBlob(chatId, blob);

    assert.equal(decoded.chat_encryption_key, chatKeyB64);
    assert.equal(decoded.duration_seconds, 0);
    assert.equal(decoded.pwd, 0);
  });

  it("embeds the correct expiry duration", async () => {
    const chatId = "expiry-test";
    const chatKey = randomKey();
    const blob = await generateChatShareBlob(chatId, chatKey, 86400); // 24h
    const decoded = await decryptChatBlob(chatId, blob);
    assert.equal(decoded.duration_seconds, 86400);
  });

  it("sets pwd=1 when password-protected", async () => {
    const chatId = "pwd-test";
    const chatKey = randomKey();
    const blob = await generateChatShareBlob(chatId, chatKey, 0, "secret");
    const decoded = await decryptChatBlob(chatId, blob);
    assert.equal(decoded.pwd, 1);
    // The stored key should be the password-encrypted form — NOT the raw base64 key
    assert.notEqual(decoded.chat_encryption_key, Buffer.from(chatKey).toString("base64"));
  });

  it("produces different blobs each call (random IV)", async () => {
    const chatId = "random-iv-test";
    const chatKey = randomKey();
    const blob1 = await generateChatShareBlob(chatId, chatKey);
    const blob2 = await generateChatShareBlob(chatId, chatKey);
    assert.notEqual(blob1, blob2, "random IV should produce different blobs");
  });
});

// ── Embed share blob ────────────────────────────────────────────────────

describe("generateEmbedShareBlob", () => {
  it("round-trips the embed key", async () => {
    const embedId = "embed-round-trip-test";
    const embedKey = randomKey();
    const embedKeyB64 = Buffer.from(embedKey).toString("base64");

    const blob = await generateEmbedShareBlob(embedId, embedKey, 0);
    const decoded = await decryptEmbedBlob(embedId, blob);

    assert.equal(decoded.embed_encryption_key, embedKeyB64);
    assert.equal(decoded.duration_seconds, 0);
    assert.equal(decoded.pwd, 0);
  });

  it("embeds expiry duration in the blob", async () => {
    const blob = await generateEmbedShareBlob("e-id", randomKey(), 604800);
    const decoded = await decryptEmbedBlob("e-id", blob);
    assert.equal(decoded.duration_seconds, 604800);
  });

  it("password-protects the embed key", async () => {
    const embedId = "embed-pwd";
    const embedKey = randomKey();
    const blob = await generateEmbedShareBlob(embedId, embedKey, 0, "mypass");
    const decoded = await decryptEmbedBlob(embedId, blob);
    assert.equal(decoded.pwd, 1);
    assert.notEqual(decoded.embed_encryption_key, Buffer.from(embedKey).toString("base64"));
  });
});

// ── URL helpers ─────────────────────────────────────────────────────────

describe("deriveWebOrigin", () => {
  it("strips api. prefix", () => {
    assert.equal(deriveWebOrigin("https://api.openmates.org"), "https://openmates.org");
  });

  it("handles dev subdomain", () => {
    assert.equal(deriveWebOrigin("https://api.dev.openmates.org"), "https://dev.openmates.org");
  });

  it("falls back gracefully on invalid URL", () => {
    assert.equal(deriveWebOrigin("not-a-url"), "https://openmates.org");
  });
});

describe("buildChatShareUrl / buildEmbedShareUrl", () => {
  it("builds chat share URL", () => {
    const url = buildChatShareUrl("https://openmates.org", "chat-123", "blobdata");
    assert.equal(url, "https://openmates.org/share/chat/chat-123#key=blobdata");
  });

  it("builds embed share URL", () => {
    const url = buildEmbedShareUrl("https://openmates.org", "embed-456", "blobdata");
    assert.equal(url, "https://openmates.org/share/embed/embed-456#key=blobdata");
  });
});
