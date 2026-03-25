// tests/registry.test.ts
/**
 * Unit tests for SecretRegistry — the in-memory secret store.
 */

import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { SecretRegistry } from "../src/registry.ts";

describe("SecretRegistry", () => {
  let registry: SecretRegistry;

  beforeEach(() => {
    registry = new SecretRegistry();
  });

  describe("add", () => {
    it("adds a secret and returns a suffix-based token", () => {
      const token = registry.add(
        "sk-proj-abc123def456ghi789",
        "OPENAI_API_KEY",
        "env",
        "OPENAI_KEY",
      );

      assert.equal(token, "[OPENAI_KEY_789]");
    });

    it("returns null for values shorter than minLength", () => {
      const token = registry.add("short", "SHORT_KEY", "env", "ENV_VAR");
      assert.equal(token, null);
    });

    it("returns existing token for duplicate values", () => {
      const token1 = registry.add(
        "sk-proj-abc123def456ghi789",
        "KEY_A",
        "env",
        "OPENAI_KEY",
      );
      const token2 = registry.add(
        "sk-proj-abc123def456ghi789",
        "KEY_B",
        "env",
        "OPENAI_KEY",
      );

      assert.equal(token1, token2);
    });

    it("generates unique tokens for different values with same suffix", () => {
      const token1 = registry.add(
        "value-ending-in-xyz",
        "KEY_A",
        "env",
        "ENV_VAR",
      );
      const token2 = registry.add(
        "other-ending-in-xyz",
        "KEY_B",
        "env",
        "ENV_VAR",
      );

      assert.ok(token1);
      assert.ok(token2);
      assert.notEqual(token1, token2);
    });
  });

  describe("addPersonalData", () => {
    it("adds personal data entry regardless of length", () => {
      registry.addPersonalData({
        id: "name-1",
        textToHide: "John",
        replaceWith: "[MY_NAME]",
      });

      assert.equal(registry.size, 1);
      const entry = registry.get("John");
      assert.ok(entry);
      assert.equal(entry!.token, "[MY_NAME]");
      assert.equal(entry!.type, "PERSONAL_DATA");
    });

    it("adds additional texts for address entries", () => {
      registry.addPersonalData({
        id: "addr-1",
        textToHide: "123 Main St",
        replaceWith: "[HOME_ADDRESS]",
        additionalTexts: ["Anytown, CA 90210"],
      });

      assert.equal(registry.size, 2);
      assert.ok(registry.get("123 Main St"));
      assert.ok(registry.get("Anytown, CA 90210"));
    });

    it("wraps placeholder in brackets if not already wrapped", () => {
      registry.addPersonalData({
        id: "name-1",
        textToHide: "Alice",
        replaceWith: "MY_FIRST_NAME",
      });

      const entry = registry.get("Alice");
      assert.equal(entry!.token, "[MY_FIRST_NAME]");
    });
  });

  describe("addFromProcessEnv", () => {
    it("picks up env vars matching secret patterns", () => {
      registry.addFromProcessEnv({
        OPENAI_API_KEY: "sk-test-1234567890abcdef",
        DATABASE_URL: "postgres://user:pass@host:5432/db",
        HOME: "/home/user",
        NODE_ENV: "development",
        SECRET_TOKEN: "my-super-secret-token-value",
      });

      // Should pick up OPENAI_API_KEY (matches _KEY), DATABASE_URL, SECRET_TOKEN
      // Should NOT pick up HOME or NODE_ENV
      assert.ok(registry.get("sk-test-1234567890abcdef"));
      assert.ok(registry.get("postgres://user:pass@host:5432/db"));
      assert.ok(registry.get("my-super-secret-token-value"));
      assert.ok(!registry.get("/home/user"));
      assert.ok(!registry.get("development"));
    });
  });

  describe("addFromEnvFile", () => {
    it("adds all values from env file vars", () => {
      registry.addFromEnvFile({
        API_KEY: "my-api-key-12345678",
        DB_PASSWORD: "supersecretpassword",
      });

      assert.equal(registry.size, 2);
      assert.ok(registry.get("my-api-key-12345678"));
      assert.ok(registry.get("supersecretpassword"));
    });
  });

  describe("findAll (Aho-Corasick)", () => {
    it("finds all known secrets in text", () => {
      registry.add(
        "sk-proj-abc123def456ghi789",
        "OPENAI_KEY",
        "env",
        "OPENAI_KEY",
      );
      registry.add(
        "postgres://admin:pass@db:5432/mydb",
        "DATABASE_URL",
        "env",
        "ENV_VAR",
      );

      const text =
        "Connect to postgres://admin:pass@db:5432/mydb with key sk-proj-abc123def456ghi789";
      const mappings = registry.findAll(text);

      assert.equal(mappings.length, 2);
    });

    it("returns empty for no matches", () => {
      registry.add("some-secret-value-xyz", "MY_KEY", "env", "ENV_VAR");

      const text = "No secrets in this text";
      const mappings = registry.findAll(text);

      assert.equal(mappings.length, 0);
    });

    it("handles case-insensitive personal data matching", () => {
      registry.addPersonalData({
        id: "name-1",
        textToHide: "Alice Smith",
        replaceWith: "[MY_NAME]",
      });

      const text = "Message from alice smith about a project";
      const mappings = registry.findAll(text);

      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].placeholder, "[MY_NAME]");
    });
  });

  describe("getByToken", () => {
    it("looks up entry by placeholder token", () => {
      registry.add("my-secret-value-abc", "MY_KEY", "env", "ENV_VAR");

      const entry = registry.getByToken("[MY_KEY_abc]");
      assert.ok(entry);
      assert.equal(entry!.value, "my-secret-value-abc");
    });

    it("returns undefined for unknown tokens", () => {
      const entry = registry.getByToken("[UNKNOWN_xyz]");
      assert.equal(entry, undefined);
    });
  });

  describe("clear", () => {
    it("removes all entries", () => {
      registry.add("secret-1-value-abc", "KEY_1", "env", "ENV_VAR");
      registry.add("secret-2-value-def", "KEY_2", "env", "ENV_VAR");

      assert.equal(registry.size, 2);

      registry.clear();
      assert.equal(registry.size, 0);
    });
  });
});
