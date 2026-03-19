// tests/outputRedactor.test.ts
/**
 * Unit tests for the CLI output redactor.
 *
 * Run: node --test --experimental-strip-types tests/outputRedactor.test.ts
 */

import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { OutputRedactor } from "../src/outputRedactor.ts";
import type { DecryptedMemoryEntry } from "../src/client.ts";

/** Create a mock personal data memory entry */
function makePersonalDataEntry(
  id: string,
  data: Record<string, unknown>,
): DecryptedMemoryEntry {
  return {
    id,
    app_id: "privacy",
    item_type: "personal_data_entry",
    item_key_hash: "mock-hash",
    item_version: 1,
    created_at: Date.now() / 1000,
    updated_at: Date.now() / 1000,
    data,
  };
}

describe("OutputRedactor", () => {
  let redactor: OutputRedactor;

  beforeEach(() => {
    redactor = new OutputRedactor();
  });

  describe("initializeFromMemories", () => {
    it("loads personal data entries from memory list", () => {
      const memories: DecryptedMemoryEntry[] = [
        makePersonalDataEntry("name-1", {
          type: "name",
          title: "My Name",
          textToHide: "John Smith",
          replaceWith: "[MY_NAME]",
          enabled: true,
        }),
      ];

      redactor.initializeFromMemories(memories);
      assert.equal(redactor.isInitialized, true);
      assert.ok(redactor.entryCount > 0);
    });

    it("skips disabled entries", () => {
      const memories: DecryptedMemoryEntry[] = [
        makePersonalDataEntry("name-1", {
          type: "name",
          title: "My Name",
          textToHide: "John Smith",
          replaceWith: "[MY_NAME]",
          enabled: false,
        }),
      ];

      redactor.initializeFromMemories(memories);
      assert.equal(redactor.isInitialized, true);
      assert.equal(redactor.entryCount, 0);
    });

    it("ignores non-privacy entries", () => {
      const memories: DecryptedMemoryEntry[] = [
        {
          id: "other-1",
          app_id: "code",
          item_type: "projects",
          item_key_hash: "hash",
          item_version: 1,
          created_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
          data: { title: "My Project" },
        },
      ];

      redactor.initializeFromMemories(memories);
      assert.equal(redactor.entryCount, 0);
    });

    it("loads address entries with additional lines", () => {
      const memories: DecryptedMemoryEntry[] = [
        makePersonalDataEntry("addr-1", {
          type: "address",
          title: "Home",
          textToHide: "123 Main St",
          replaceWith: "[HOME_ADDRESS]",
          enabled: true,
          addressLines: {
            street: "123 Main St",
            city: "Springfield",
            state: "IL",
            zip: "62704",
          },
        }),
      ];

      redactor.initializeFromMemories(memories);
      // Main text + address lines (non-empty ones)
      assert.ok(redactor.entryCount > 0);
    });
  });

  describe("redact", () => {
    it("redacts personal data from text", () => {
      redactor.initializeFromMemories([
        makePersonalDataEntry("name-1", {
          type: "name",
          title: "My Name",
          textToHide: "John Smith",
          replaceWith: "[MY_NAME]",
          enabled: true,
        }),
      ]);

      const result = redactor.redact("Hello John Smith, how are you?");
      assert.ok(!result.includes("John Smith"));
      assert.ok(result.includes("[MY_NAME]"));
    });

    it("returns text unchanged when not initialized", () => {
      const text = "Hello John Smith";
      assert.equal(redactor.redact(text), text);
    });

    it("detects API keys via pattern matching", () => {
      redactor.initializeFromMemories([]); // initialize with no personal data

      const text = "My key is sk-proj-abc123def456ghi789";
      const result = redactor.redact(text);
      assert.ok(!result.includes("sk-proj-abc123def456ghi789"));
      assert.ok(result.includes("[OPENAI_KEY_"));
    });
  });

  describe("redactWithMappings", () => {
    it("returns both redacted text and mappings", () => {
      redactor.initializeFromMemories([
        makePersonalDataEntry("name-1", {
          type: "name",
          title: "My Name",
          textToHide: "Alice",
          replaceWith: "[MY_NAME]",
          enabled: true,
        }),
      ]);

      const result = redactor.redactWithMappings("Hello Alice!");
      assert.ok(result.redacted.includes("[MY_NAME]"));
      assert.ok(result.mappings.length > 0);
      assert.equal(result.mappings[0].placeholder, "[MY_NAME]");
    });
  });

  describe("restore", () => {
    it("restores previously redacted text", () => {
      redactor.initializeFromMemories([
        makePersonalDataEntry("name-1", {
          type: "name",
          title: "My Name",
          textToHide: "Bob",
          replaceWith: "[MY_NAME]",
          enabled: true,
        }),
      ]);

      const original = "Hello Bob, welcome!";
      const redacted = redactor.redact(original);
      assert.ok(redacted.includes("[MY_NAME]"));

      const restored = redactor.restore(redacted);
      assert.equal(restored, original);
    });
  });
});
