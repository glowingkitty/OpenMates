// tests/redact-restore.test.ts
/**
 * Unit tests for the redact/restore roundtrip — verifying that
 * text → redact → restore produces the original text.
 * Also tests the env file parser.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { SecretScanner } from "../src/scanner.ts";
import { parseEnvFile } from "../src/envParser.ts";
import { getSecretSuffix, generatePlaceholder } from "../src/patterns.ts";

describe("redact → restore roundtrip", () => {
  it("roundtrips text with mixed secrets and personal data", () => {
    const scanner = new SecretScanner();
    scanner.addFromEnvFile({
      OPENAI_API_KEY: "sk-proj-abc123def456ghi789",
      DATABASE_URL: "postgres://admin:p@ss@db:5432/mydb",
    });
    scanner.addPersonalData({
      id: "name-1",
      textToHide: "Marco",
      replaceWith: "[MY_NAME]",
    });

    const original =
      "Hi Marco, connect to postgres://admin:p@ss@db:5432/mydb using sk-proj-abc123def456ghi789";
    const { redacted, mappings } = scanner.redact(original);

    // Verify redaction
    assert.ok(!redacted.includes("Marco"));
    assert.ok(!redacted.includes("postgres://admin"));
    assert.ok(!redacted.includes("sk-proj-"));
    assert.ok(redacted.includes("[MY_NAME]"));

    // Verify restoration
    const restored = scanner.restore(redacted, mappings);
    assert.equal(restored, original);
  });

  it("roundtrips text with multiple occurrences of the same secret", () => {
    const scanner = new SecretScanner();
    scanner.addFromEnvFile({ API_KEY: "my-secret-key-value-abc123" });

    const original =
      "Use my-secret-key-value-abc123 here and my-secret-key-value-abc123 there";
    const { redacted, mappings } = scanner.redact(original);
    const restored = scanner.restore(redacted, mappings);

    assert.equal(restored, original);
  });

  it("preserves non-secret text exactly", () => {
    const scanner = new SecretScanner();
    scanner.addFromEnvFile({ KEY: "supersecretvalue" });

    const original = "   Spaces   and\ttabs\nand\nnewlines   ";
    const { redacted, mappings } = scanner.redact(original);
    const restored = scanner.restore(redacted, mappings);

    assert.equal(restored, original);
  });
});

describe("parseEnvFile", () => {
  it("parses simple KEY=value pairs", () => {
    const content = "FOO=bar\nBAZ=qux";
    const result = parseEnvFile(content);

    assert.equal(result["FOO"], "bar");
    assert.equal(result["BAZ"], "qux");
  });

  it("handles quoted values", () => {
    const content = `DB_URL="postgres://user:pass@host:5432/db"\nSECRET='my secret value'`;
    const result = parseEnvFile(content);

    assert.equal(result["DB_URL"], "postgres://user:pass@host:5432/db");
    assert.equal(result["SECRET"], "my secret value");
  });

  it("skips comments and empty lines", () => {
    const content = `# This is a comment\n\nFOO=bar\n# Another comment\nBAZ=qux`;
    const result = parseEnvFile(content);

    assert.equal(Object.keys(result).length, 2);
    assert.equal(result["FOO"], "bar");
    assert.equal(result["BAZ"], "qux");
  });

  it("handles export prefix", () => {
    const content = "export MY_KEY=my_value";
    const result = parseEnvFile(content);

    assert.equal(result["MY_KEY"], "my_value");
  });

  it("strips inline comments for unquoted values", () => {
    const content = "API_KEY=abc123 # my API key";
    const result = parseEnvFile(content);

    assert.equal(result["API_KEY"], "abc123");
  });

  it("preserves inline # in quoted values", () => {
    const content = 'PASSWORD="my#secret#pass"';
    const result = parseEnvFile(content);

    assert.equal(result["PASSWORD"], "my#secret#pass");
  });
});

describe("getSecretSuffix", () => {
  it("extracts last 3 characters by default", () => {
    assert.equal(getSecretSuffix("sk-proj-abc123def456ghi789"), "789");
  });

  it("strips trailing quotes and whitespace", () => {
    assert.equal(getSecretSuffix('"my-secret-key-abc"'), "abc");
    assert.equal(getSecretSuffix("my-secret-key-abc' "), "abc");
  });

  it("returns full string for values shorter than N", () => {
    assert.equal(getSecretSuffix("ab"), "ab");
    assert.equal(getSecretSuffix("a"), "a");
  });

  it("supports custom suffix length", () => {
    assert.equal(getSecretSuffix("sk-proj-abc123def456ghi789", 5), "hi789");
  });

  it("supports custom suffix length correctly", () => {
    assert.equal(getSecretSuffix("abcdefghij", 5), "fghij");
    assert.equal(getSecretSuffix("abcdefghij", 1), "j");
  });
});

describe("generatePlaceholder", () => {
  it("creates counter + suffix-based placeholder", () => {
    assert.equal(
      generatePlaceholder("OPENAI_KEY", "sk-proj-abc123def456ghi789"),
      "[OPENAI_KEY_1_789]",
    );
  });

  it("creates placeholder with custom suffix length", () => {
    assert.equal(
      generatePlaceholder("AWS_KEY", "AKIAIOSFODNN7EXAMPLE", 4),
      "[AWS_KEY_1_MPLE]",
    );
  });

  it("includes counter for disambiguation", () => {
    assert.equal(
      generatePlaceholder("EMAIL", "alice@example.com", 3, 1),
      "[EMAIL_1_com]",
    );
    assert.equal(
      generatePlaceholder("EMAIL", "bob@example.com", 3, 2),
      "[EMAIL_2_com]",
    );
  });
});
