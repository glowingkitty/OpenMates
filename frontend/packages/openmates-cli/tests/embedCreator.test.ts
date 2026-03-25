// tests/embedCreator.test.ts
/**
 * Unit tests for the embed creation and encryption pipeline.
 *
 * Run: node --test --experimental-strip-types tests/embedCreator.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import {
  generateEmbedKey,
  computeSHA256,
  toonEncodeContent,
  generateEmbedId,
  createEmbedReferenceBlock,
  encryptEmbed,
} from "../src/embedCreator.ts";
const cryptoApi = webcrypto as unknown as Crypto;

describe("embedCreator", () => {
  describe("generateEmbedKey", () => {
    it("generates a 32-byte key", () => {
      const key = generateEmbedKey();
      assert.equal(key.length, 32);
    });

    it("generates unique keys", () => {
      const key1 = generateEmbedKey();
      const key2 = generateEmbedKey();
      assert.notDeepEqual(key1, key2);
    });
  });

  describe("computeSHA256", () => {
    it("produces hex string", () => {
      const hash = computeSHA256("hello");
      assert.equal(hash.length, 64);
      assert.match(hash, /^[0-9a-f]+$/);
    });

    it("is deterministic", () => {
      assert.equal(computeSHA256("test"), computeSHA256("test"));
    });
  });

  describe("encryptEmbed key wrapping", () => {
    it("encrypted embed has valid base64 key wrappers", async () => {
      const masterKey = cryptoApi.getRandomValues(new Uint8Array(32));
      const encrypted = await encryptEmbed(
        {
          embedId: "wrap-test-id",
          type: "code-code",
          content: "test",
          textPreview: "test",
          status: "finished",
        },
        masterKey,
        null,
        "chat-id",
        "msg-id",
        "user-id",
      );

      assert.ok(encrypted);
      const keyWrapper = encrypted!.embed_keys[0];
      // Wrapped key should be a valid base64 string > 44 chars (12 IV + 32 key + 16 tag)
      assert.ok(keyWrapper.encrypted_embed_key.length > 44);
      // Should decode to valid base64
      const decoded = Buffer.from(keyWrapper.encrypted_embed_key, "base64");
      assert.ok(decoded.length >= 60); // IV(12) + key(32) + GCM tag(16) = 60
    });

    it("produces unique wrappers each time (random IV)", async () => {
      const masterKey = cryptoApi.getRandomValues(new Uint8Array(32));
      const e1 = await encryptEmbed(
        { embedId: "id-1", type: "t", content: "c", textPreview: "p", status: "finished" },
        masterKey, null, "chat", "msg", "user",
      );
      const e2 = await encryptEmbed(
        { embedId: "id-2", type: "t", content: "c", textPreview: "p", status: "finished" },
        masterKey, null, "chat", "msg", "user",
      );
      assert.ok(e1 && e2);
      assert.notEqual(
        e1!.embed_keys[0].encrypted_embed_key,
        e2!.embed_keys[0].encrypted_embed_key,
      );
    });
  });

  describe("toonEncodeContent", () => {
    it("encodes an object to a non-empty string", () => {
      const encoded = toonEncodeContent({
        type: "code",
        language: "typescript",
        code: "const x = 42;",
      });
      assert.ok(encoded.length > 0);
    });

    it("includes field values in encoded output", () => {
      const encoded = toonEncodeContent({
        type: "code",
        code: "hello world",
      });
      assert.ok(encoded.includes("hello world") || encoded.includes("code"));
    });
  });

  describe("generateEmbedId", () => {
    it("generates a UUID-like string", () => {
      const id = generateEmbedId();
      assert.match(id, /^[0-9a-f-]{36}$/);
    });

    it("generates unique IDs", () => {
      const ids = new Set(Array.from({ length: 10 }, () => generateEmbedId()));
      assert.equal(ids.size, 10);
    });
  });

  describe("createEmbedReferenceBlock", () => {
    it("creates a fenced JSON block", () => {
      const block = createEmbedReferenceBlock("code", "test-id-123");
      assert.ok(block.startsWith("```json\n"));
      assert.ok(block.endsWith("\n```"));
      assert.ok(block.includes('"type": "code"'));
      assert.ok(block.includes('"embed_id": "test-id-123"'));
    });
  });

  describe("encryptEmbed", () => {
    it("encrypts a prepared embed with all required fields", async () => {
      const masterKey = cryptoApi.getRandomValues(new Uint8Array(32));

      const encrypted = await encryptEmbed(
        {
          embedId: "test-embed-id",
          type: "code-code",
          content: toonEncodeContent({ type: "code", code: "x = 42" }),
          textPreview: "test.py (python, 1 lines)",
          status: "finished",
          filePath: "test.py",
          contentHash: computeSHA256("x = 42"),
          textLengthChars: 6,
        },
        masterKey,
        null, // no chat key
        "chat-id-123",
        "message-id-456",
        "user@example.com",
      );

      assert.ok(encrypted);
      assert.equal(encrypted!.embed_id, "test-embed-id");
      assert.equal(encrypted!.status, "finished");

      // All fields should be encrypted (base64 strings)
      assert.ok(encrypted!.encrypted_type.length > 10);
      assert.ok(encrypted!.encrypted_content.length > 10);
      assert.ok(encrypted!.encrypted_text_preview.length > 10);

      // Hashed IDs should be hex strings
      assert.match(encrypted!.hashed_chat_id, /^[0-9a-f]{64}$/);
      assert.match(encrypted!.hashed_message_id, /^[0-9a-f]{64}$/);
      assert.match(encrypted!.hashed_user_id, /^[0-9a-f]{64}$/);

      // Should have at least master key wrapper
      assert.ok(encrypted!.embed_keys.length >= 1);
      assert.equal(encrypted!.embed_keys[0].key_type, "master");

      // Timestamps should be Unix seconds
      assert.ok(encrypted!.created_at > 1_000_000_000);
      assert.ok(encrypted!.created_at < 100_000_000_000); // not milliseconds
    });

    it("includes chat key wrapper when chatKey is provided", async () => {
      const masterKey = cryptoApi.getRandomValues(new Uint8Array(32));
      const chatKey = cryptoApi.getRandomValues(new Uint8Array(32));

      const encrypted = await encryptEmbed(
        {
          embedId: "test-embed-2",
          type: "code-code",
          content: "test content",
          textPreview: "test",
          status: "finished",
        },
        masterKey,
        chatKey,
        "chat-id",
        "msg-id",
        "user-id",
      );

      assert.ok(encrypted);
      assert.equal(encrypted!.embed_keys.length, 2);
      assert.equal(encrypted!.embed_keys[0].key_type, "master");
      assert.equal(encrypted!.embed_keys[1].key_type, "chat");
    });
  });
});
