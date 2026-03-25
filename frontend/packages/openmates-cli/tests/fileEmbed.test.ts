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
import { processFiles, formatEmbedsForMessage } from "../src/fileEmbed.ts";
import { OutputRedactor } from "../src/outputRedactor.ts";

const testDir = join(tmpdir(), `openmates-test-${Date.now()}`);

describe("fileEmbed", () => {
  beforeEach(() => {
    mkdirSync(testDir, { recursive: true });
  });

  afterEach(() => {
    rmSync(testDir, { recursive: true, force: true });
  });

  describe("processFiles — code/text files", () => {
    it("creates a code-code embed for .ts files", () => {
      const filePath = join(testDir, "app.ts");
      writeFileSync(filePath, "const x: number = 42;");

      const result = processFiles([filePath], null);
      assert.equal(result.embeds.length, 1);
      assert.equal(result.errors.length, 0);
      assert.equal(result.blocked.length, 0);

      const embed = result.embeds[0];
      assert.equal(embed.embed.type, "code-code");
      assert.equal(embed.embed.status, "finished");
      assert.equal(embed.requiresUpload, false);
      assert.ok(embed.embed.content.length > 0);
      assert.ok(embed.referenceBlock.includes('"type": "code"'));
      assert.ok(embed.referenceBlock.includes(embed.embed.embedId));
    });

    it("detects language from extension", () => {
      const filePath = join(testDir, "script.py");
      writeFileSync(filePath, "print('hello')");

      const result = processFiles([filePath], null);
      assert.ok(result.embeds[0].embed.content.includes("python"));
    });

    it("processes .env files with zero-knowledge mode", () => {
      const filePath = join(testDir, ".env");
      writeFileSync(
        filePath,
        'DATABASE_URL="postgres://admin:secretpass@db:5432/mydb"\nAPI_KEY=sk-proj-abc123def456ghi789\n# Comment',
      );

      const result = processFiles([filePath], null);
      assert.equal(result.embeds.length, 1);
      assert.equal(result.embeds[0].zeroKnowledge, true);
      assert.equal(result.embeds[0].secretsRedacted, true);
      // Verify secrets are NOT in the TOON content
      assert.ok(!result.embeds[0].embed.content.includes("postgres://admin:secretpass"));
      assert.ok(!result.embeds[0].embed.content.includes("sk-proj-abc123def456ghi789"));
    });

    it("redacts secrets with redactor", () => {
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
      assert.equal(result.embeds.length, 1);
      assert.equal(result.embeds[0].secretsRedacted, true);
      assert.ok(!result.embeds[0].embed.content.includes("John Smith"));
      assert.ok(result.embeds[0].embed.content.includes("[MY_NAME]"));
    });
  });

  describe("processFiles — images", () => {
    it("creates an image embed that requires upload", () => {
      const filePath = join(testDir, "photo.jpg");
      writeFileSync(filePath, Buffer.from([0xff, 0xd8, 0xff, 0xe0])); // JPEG header

      const result = processFiles([filePath], null);
      assert.equal(result.embeds.length, 1);
      assert.equal(result.embeds[0].embed.type, "image");
      assert.equal(result.embeds[0].requiresUpload, true);
      assert.equal(result.embeds[0].localPath, filePath);
    });

    it("supports various image extensions", () => {
      for (const ext of ["png", "webp", "gif", "svg"]) {
        const filePath = join(testDir, `test.${ext}`);
        writeFileSync(filePath, "fake image data");

        const result = processFiles([filePath], null);
        assert.equal(result.embeds.length, 1, `Failed for .${ext}`);
        assert.equal(result.embeds[0].requiresUpload, true);
      }
    });
  });

  describe("processFiles — PDFs", () => {
    it("creates a PDF embed that requires upload", () => {
      const filePath = join(testDir, "document.pdf");
      writeFileSync(filePath, "%PDF-1.4 fake content");

      const result = processFiles([filePath], null);
      assert.equal(result.embeds.length, 1);
      assert.equal(result.embeds[0].embed.type, "pdf");
      assert.equal(result.embeds[0].embed.status, "processing");
      assert.equal(result.embeds[0].requiresUpload, true);
    });
  });

  describe("processFiles — blocked files", () => {
    it("blocks .pem files", () => {
      const filePath = join(testDir, "server.pem");
      writeFileSync(filePath, "-----BEGIN CERTIFICATE-----");

      const result = processFiles([filePath], null);
      assert.equal(result.embeds.length, 0);
      assert.equal(result.blocked.length, 1);
    });

    it("blocks SSH key files", () => {
      const filePath = join(testDir, "id_rsa");
      writeFileSync(filePath, "-----BEGIN RSA PRIVATE KEY-----");

      const result = processFiles([filePath], null);
      assert.equal(result.blocked.length, 1);
    });
  });

  describe("processFiles — errors", () => {
    it("reports error for non-existent files", () => {
      const result = processFiles([join(testDir, "nope.txt")], null);
      assert.equal(result.errors.length, 1);
      assert.ok(result.errors[0].error.includes("not found"));
    });

    it("reports error for directories", () => {
      const dirPath = join(testDir, "subdir");
      mkdirSync(dirPath);
      const result = processFiles([dirPath], null);
      assert.equal(result.errors.length, 1);
    });

    it("reports error for unsupported file types", () => {
      const filePath = join(testDir, "archive.zip");
      writeFileSync(filePath, "PK fake zip");
      const result = processFiles([filePath], null);
      assert.equal(result.errors.length, 1);
      assert.ok(result.errors[0].error.includes("Unsupported"));
    });
  });

  describe("formatEmbedsForMessage", () => {
    it("formats embed references as JSON blocks", () => {
      const formatted = formatEmbedsForMessage([
        {
          embed: {
            embedId: "test-uuid-123",
            type: "code-code",
            content: "toon-data",
            textPreview: "app.ts",
            status: "finished",
          },
          referenceBlock: '```json\n{\n  "type": "code",\n  "embed_id": "test-uuid-123"\n}\n```',
          displayName: "app.ts",
          secretsRedacted: false,
          zeroKnowledge: false,
          requiresUpload: false,
        },
      ]);

      assert.ok(formatted.includes("```json"));
      assert.ok(formatted.includes("test-uuid-123"));
    });

    it("returns empty string for no embeds", () => {
      assert.equal(formatEmbedsForMessage([]), "");
    });
  });
});
