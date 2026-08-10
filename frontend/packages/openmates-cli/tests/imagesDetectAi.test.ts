// contract-test-file: tooling
/**
 * Images AI detection CLI unit tests.
 *
 * Purpose: keep the terminal-only Images detect-ai wrapper, summary helpers,
 * and user-guide command reference aligned without expanding the legacy CLI
 * test contract metadata backlog.
 * Run: cd frontend/packages/openmates-cli && npm run build && node --test tests/imagesDetectAi.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { buildImagesAiDetectionSummary, classifyImagesAiDetection } from "../dist/cli.js";

const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));
const REPO_ROOT = fileURLToPath(new URL("../../../..", import.meta.url));

function runCli(args: string[]): string {
  return execFileSync("node", ["dist/cli.js", ...args], {
    cwd: PACKAGE_ROOT,
    encoding: "utf-8",
    env: { ...process.env, TERM: "dumb" },
    timeout: 15_000,
  });
}

describe("apps images detect-ai command", () => {
  it("classifies Sightengine AI-generated probabilities", () => {
    assert.equal(classifyImagesAiDetection(0.99), "likely_ai_generated");
    assert.equal(classifyImagesAiDetection(0.7), "possibly_ai_generated");
    assert.equal(classifyImagesAiDetection(0.41), "possibly_ai_generated");
    assert.equal(classifyImagesAiDetection(0.4), "likely_not_ai_generated");
    assert.equal(classifyImagesAiDetection(null), "unavailable");
  });

  it("builds a reusable summary from the upload AI detection metadata", () => {
    const summary = buildImagesAiDetectionSummary({
      embed_id: "embed-1",
      filename: "image.png",
      content_type: "image/png",
      content_hash: "hash",
      files: {},
      s3_base_url: "https://usercontent.example.invalid",
      aes_key: "key",
      aes_nonce: "nonce",
      vault_wrapped_aes_key: "vault:v1:wrapped",
      malware_scan: "clean",
      deduplicated: false,
      ai_detection: {
        ai_generated: 0.99,
        provider: "sightengine",
        status: "success",
        error: null,
      },
    }, "/tmp/image.png");

    assert.equal(summary.ai_generated, 0.99);
    assert.equal(summary.provider, "sightengine");
    assert.equal(summary.classification, "likely_ai_generated");
    assert.equal(summary.label, "Likely AI-generated");
    assert.equal(summary.stored, true);
  });

  it("lists the typed command in apps help and docs", () => {
    const output = runCli(["apps", "--help"]);
    const docs = readFileSync(`${REPO_ROOT}/docs/user-guide/cli/apps-and-skills.md`, "utf-8");
    assert.match(output, /openmates apps images detect-ai --file \.\/image\.png/);
    assert.match(docs, /openmates apps images detect-ai --file \.\/image\.png/);
  });
});
