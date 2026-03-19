// tests/fileEmbed.test.ts
/**
 * Unit tests for CLI file embed processing.
 *
 * Run: node --test --experimental-strip-types tests/fileEmbed.test.ts
 */

import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { writeFileSync, mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { processFiles, formatFilesForMessage } from "../src/fileEmbed.ts";
import { OutputRedactor } from "../src/outputRedactor.ts";

const testDir = join(tmpdir(), `openmates-test-${Date.now()}`);

describe("fileEmbed", () => {
  beforeEach(() => {
    mkdirSync(testDir, { recursive: true });
  });

  afterEach(() => {
    rmSync(testDir, { recursive: true, force: true });
  });

  describe("processFiles", () => {
    it("reads a normal text file", () => {
      const filePath = join(testDir, "hello.txt");
      writeFileSync(filePath, "Hello, world!");

      const result = processFiles([filePath], null);
      assert.equal(result.files.length, 1);
      assert.equal(result.errors.length, 0);
      assert.equal(result.blocked.length, 0);
      assert.equal(result.files[0].content, "Hello, world!");
      assert.equal(result.files[0].redacted, false);
    });

    it("reads a TypeScript file with correct language hint", () => {
      const filePath = join(testDir, "app.ts");
      writeFileSync(filePath, "const x: number = 42;");

      const result = processFiles([filePath], null);
      assert.equal(result.files[0].language, "typescript");
    });

    it("processes .env files with zero-knowledge mode", () => {
      const filePath = join(testDir, ".env");
      writeFileSync(
        filePath,
        'DATABASE_URL="postgres://admin:secretpass@db:5432/mydb"\nAPI_KEY=sk-proj-abc123def456ghi789\nEMPTY_VAR=\n# This is a comment',
      );

      const result = processFiles([filePath], null);
      assert.equal(result.files.length, 1);
      assert.equal(result.files[0].zeroKnowledge, true);
      assert.equal(result.files[0].redacted, true);
      // Should show variable names but not full values
      assert.ok(result.files[0].content.includes("DATABASE_URL:"));
      assert.ok(result.files[0].content.includes("API_KEY:"));
      assert.ok(!result.files[0].content.includes("postgres://admin:secretpass"));
      assert.ok(!result.files[0].content.includes("sk-proj-abc123def456ghi789"));
      // Should preserve comments
      assert.ok(result.files[0].content.includes("# This is a comment"));
    });

    it("processes .env.local files with zero-knowledge mode", () => {
      const filePath = join(testDir, ".env.local");
      writeFileSync(filePath, "SECRET=my-value-123456789");

      const result = processFiles([filePath], null);
      assert.equal(result.files[0].zeroKnowledge, true);
    });

    it("blocks .pem files", () => {
      const filePath = join(testDir, "server.pem");
      writeFileSync(filePath, "-----BEGIN CERTIFICATE-----");

      const result = processFiles([filePath], null);
      assert.equal(result.files.length, 0);
      assert.equal(result.blocked.length, 1);
      assert.ok(result.blocked[0].error.includes("private keys"));
    });

    it("blocks id_rsa files", () => {
      const filePath = join(testDir, "id_rsa");
      writeFileSync(filePath, "-----BEGIN RSA PRIVATE KEY-----");

      const result = processFiles([filePath], null);
      assert.equal(result.blocked.length, 1);
    });

    it("reports error for non-existent files", () => {
      const result = processFiles([join(testDir, "nonexistent.txt")], null);
      assert.equal(result.errors.length, 1);
      assert.ok(result.errors[0].error.includes("not found"));
    });

    it("reports error for directories", () => {
      const dirPath = join(testDir, "subdir");
      mkdirSync(dirPath);

      const result = processFiles([dirPath], null);
      assert.equal(result.errors.length, 1);
      assert.ok(result.errors[0].error.includes("directory"));
    });

    it("redacts secrets in files when redactor is provided", () => {
      const redactor = new OutputRedactor();
      redactor.initializeFromMemories([
        {
          id: "name-1",
          app_id: "privacy",
          item_type: "personal_data_entry",
          item_key_hash: "h",
          item_version: 1,
          created_at: 0,
          updated_at: 0,
          data: {
            type: "name",
            title: "Name",
            textToHide: "John Smith",
            replaceWith: "[MY_NAME]",
            enabled: true,
          },
        },
      ]);

      const filePath = join(testDir, "config.yml");
      writeFileSync(filePath, "author: John Smith\nversion: 1.0");

      const result = processFiles([filePath], redactor);
      assert.equal(result.files.length, 1);
      assert.equal(result.files[0].redacted, true);
      assert.ok(!result.files[0].content.includes("John Smith"));
      assert.ok(result.files[0].content.includes("[MY_NAME]"));
    });
  });

  describe("formatFilesForMessage", () => {
    it("formats files as code blocks", () => {
      const formatted = formatFilesForMessage([
        {
          path: "/tmp/app.ts",
          name: "app.ts",
          content: "const x = 42;",
          language: "typescript",
          redacted: false,
          zeroKnowledge: false,
        },
      ]);

      assert.ok(formatted.includes("```typescript"));
      assert.ok(formatted.includes("const x = 42;"));
      assert.ok(formatted.includes("[File: app.ts]"));
    });

    it("marks zero-knowledge files", () => {
      const formatted = formatFilesForMessage([
        {
          path: "/tmp/.env",
          name: ".env",
          content: "KEY: ***abc",
          language: "bash",
          redacted: true,
          zeroKnowledge: true,
        },
      ]);

      assert.ok(formatted.includes("zero-knowledge mode"));
    });

    it("marks redacted files", () => {
      const formatted = formatFilesForMessage([
        {
          path: "/tmp/config.ts",
          name: "config.ts",
          content: "[MY_NAME]",
          language: "typescript",
          redacted: true,
          zeroKnowledge: false,
        },
      ]);

      assert.ok(formatted.includes("secrets redacted"));
    });

    it("returns empty string for no files", () => {
      assert.equal(formatFilesForMessage([]), "");
    });
  });
});
