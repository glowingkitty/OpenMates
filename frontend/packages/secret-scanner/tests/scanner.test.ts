// tests/scanner.test.ts
/**
 * Unit tests for SecretScanner — the main redact/restore API.
 */

import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { SecretScanner } from "../src/scanner.ts";

describe("SecretScanner", () => {
  let scanner: SecretScanner;

  beforeEach(() => {
    scanner = new SecretScanner();
  });

  describe("pattern-based detection (vendor-specific API keys)", () => {
    it("detects OpenAI API keys with suffix-based placeholder", () => {
      const text = "My key is sk-proj-abc123def456ghi789";
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].type, "OPENAI_KEY");
      assert.equal(mappings[0].original, "sk-proj-abc123def456ghi789");
      assert.equal(mappings[0].placeholder, "[OPENAI_KEY_1_789]");
      assert.equal(redacted, "My key is [OPENAI_KEY_1_789]");
    });

    it("detects AWS access keys", () => {
      const text = "AWS key: AKIAIOSFODNN7EXAMPLE";
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].type, "AWS_ACCESS_KEY");
      assert.equal(mappings[0].placeholder, "[AWS_KEY_1_PLE]");
      assert.equal(redacted, "AWS key: [AWS_KEY_1_PLE]");
    });

    it("detects GitHub PATs", () => {
      const text = "Token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij";
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].type, "GITHUB_PAT");
      assert.ok(mappings[0].placeholder.startsWith("[GITHUB_TOKEN_"));
    });

    it("detects Stripe keys", () => {
      const text = "sk_test_AAAAAABBBBBBCCCCCCDDDDDDDD";
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].type, "STRIPE_KEY");
      assert.ok(mappings[0].placeholder.startsWith("[STRIPE_KEY_"));
    });

    it("detects JWT tokens", () => {
      const text =
        "Token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U";
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].type, "JWT");
      assert.ok(mappings[0].placeholder.startsWith("[JWT_TOKEN_"));
    });

    it("detects private keys", () => {
      const text = `-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA2a2rwplBQLz8EHt5sxxH
-----END RSA PRIVATE KEY-----`;
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].type, "PRIVATE_KEY");
      assert.ok(mappings[0].placeholder.startsWith("[PRIVATE_KEY_"));
    });

    it("detects generic secrets with assignment context", () => {
      const text = 'api_key="my_super_secret_key_value_123"';
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].type, "GENERIC_SECRET");
      assert.ok(mappings[0].placeholder.startsWith("[SECRET_"));
    });

    it("detects multiple secrets in one text", () => {
      const text =
        "OpenAI: sk-proj-abc123def456ghi789, AWS: AKIAIOSFODNN7EXAMPLE";
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 2);
      assert.ok(redacted.includes("[OPENAI_KEY_"));
      assert.ok(redacted.includes("[AWS_KEY_"));
      assert.ok(!redacted.includes("sk-proj-"));
      assert.ok(!redacted.includes("AKIAIOSFODNN7"));
    });
  });

  describe("registry-based detection", () => {
    it("detects known secret values from env file", () => {
      scanner.addFromEnvFile({
        DATABASE_URL: "postgres://admin:s3cretP@ss@db:5432/mydb",
      });

      const text =
        "Connect to postgres://admin:s3cretP@ss@db:5432/mydb for data";
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 1);
      assert.ok(redacted.includes("[DATABASE_URL_"));
      assert.ok(!redacted.includes("s3cretP@ss"));
    });

    it("registry matches take priority over pattern matches", () => {
      // Register an OpenAI key in the registry with a custom name
      scanner.addSecret(
        "sk-proj-abc123def456ghi789",
        "MY_CUSTOM_AI_KEY",
        "env",
        "ENV_VAR",
      );

      const text = "Key: sk-proj-abc123def456ghi789";
      const { redacted, mappings } = scanner.redact(text);

      // Should be detected by registry (ENV_VAR type), not pattern (OPENAI_KEY)
      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].type, "ENV_VAR");
      assert.ok(
        mappings[0].placeholder.includes("MY_CUSTOM_AI_KEY"),
        `Expected placeholder to contain MY_CUSTOM_AI_KEY, got: ${mappings[0].placeholder}`,
      );
    });

    it("skips values shorter than minSecretLength", () => {
      scanner.addFromEnvFile({ SHORT: "abc" });

      const text = "Value: abc";
      const { mappings } = scanner.redact(text);

      assert.equal(mappings.length, 0);
    });
  });

  describe("personal data detection", () => {
    it("detects personal data entries (case-insensitive)", () => {
      scanner.addPersonalData({
        id: "name-1",
        textToHide: "John Smith",
        replaceWith: "[MY_NAME]",
      });

      const text = "Hello, I'm john smith and this is my project";
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 1);
      assert.equal(mappings[0].placeholder, "[MY_NAME]");
      assert.ok(!redacted.toLowerCase().includes("john smith"));
      assert.ok(redacted.includes("[MY_NAME]"));
    });

    it("detects address entries with additional lines", () => {
      scanner.addPersonalData({
        id: "addr-1",
        textToHide: "123 Main Street",
        replaceWith: "[HOME_ADDRESS]",
        additionalTexts: ["Anytown, CA 90210"],
      });

      const text = "Ship to 123 Main Street, Anytown, CA 90210";
      const { redacted, mappings } = scanner.redact(text);

      assert.equal(mappings.length, 2);
      assert.ok(redacted.includes("[HOME_ADDRESS]"));
      assert.ok(!redacted.includes("123 Main Street"));
      assert.ok(!redacted.includes("Anytown, CA 90210"));
    });
  });

  describe("restore", () => {
    it("restores all placeholders to original values", () => {
      scanner.addFromEnvFile({
        OPENAI_API_KEY: "sk-proj-abc123def456ghi789",
      });
      scanner.addPersonalData({
        id: "name-1",
        textToHide: "John",
        replaceWith: "[MY_NAME]",
      });

      const original = "Hey John, your key is sk-proj-abc123def456ghi789";
      const { redacted, mappings } = scanner.redact(original);

      assert.ok(!redacted.includes("John"));
      assert.ok(!redacted.includes("sk-proj-"));

      const restored = scanner.restore(redacted, mappings);
      assert.equal(restored, original);
    });

    it("handles empty mappings gracefully", () => {
      const text = "No secrets here";
      const restored = scanner.restore(text, []);
      assert.equal(restored, text);
    });

    it("handles empty text gracefully", () => {
      const restored = scanner.restore("", [
        {
          placeholder: "[SECRET_abc]",
          original: "secret",
          type: "GENERIC_SECRET",
          source: "env",
        },
      ]);
      assert.equal(restored, "");
    });
  });

  describe("suffix collision handling", () => {
    it("disambiguates secrets with the same suffix", () => {
      // Two different secrets that end with the same 3 chars
      scanner.addSecret("first-secret-value-789", "KEY_A", "env", "ENV_VAR");
      scanner.addSecret("other-secret-value-789", "KEY_B", "env", "ENV_VAR");

      const entryA = scanner["registry"].get("first-secret-value-789");
      const entryB = scanner["registry"].get("other-secret-value-789");

      // Both should have tokens, but they must be different
      assert.ok(entryA);
      assert.ok(entryB);
      assert.notEqual(entryA!.token, entryB!.token);
    });
  });

  describe("edge cases", () => {
    it("handles empty text", () => {
      const { redacted, mappings } = scanner.redact("");
      assert.equal(redacted, "");
      assert.equal(mappings.length, 0);
    });

    it("handles text with no secrets", () => {
      const text = "Just a normal message with no sensitive data";
      const { redacted, mappings } = scanner.redact(text);
      assert.equal(redacted, text);
      assert.equal(mappings.length, 0);
    });

    it("handles text with only whitespace", () => {
      const { redacted, mappings } = scanner.redact("   \n\t  ");
      assert.equal(redacted, "   \n\t  ");
      assert.equal(mappings.length, 0);
    });
  });
});
