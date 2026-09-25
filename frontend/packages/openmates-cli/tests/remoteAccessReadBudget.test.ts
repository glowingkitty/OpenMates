// contract-test-file: infrastructure
/** Focused checks for browser-requested remote text bounds. */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  readRemoteAccessTextFile,
  remoteAccessReadLimits,
  serializeRemoteAccessSuccessResponse,
} from "../src/remoteAccess.ts";

describe("Project remote text request budget", () => {
  // contract-test: direct surface=sdks.npm assertions=projects.files.no-server-decryption-authority,projects.surface.semantic-parity
  it("returns ordinary files above the preview limit as complete bounded reads", () => {
    assert.deepEqual(remoteAccessReadLimits({ max_bytes: 180 * 1024, max_lines: 4_000 }), {
      maxBytes: 180 * 1024,
      maxLines: 4_000,
    });
    for (const invalid of [0, -1, 200 * 1024 + 1, 1.5, Number.POSITIVE_INFINITY, "1024"]) {
      assert.throws(() => remoteAccessReadLimits({ max_bytes: invalid }), /byte limit/);
    }

    const root = join(tmpdir(), `openmates-browser-read-budget-${Date.now()}`);
    mkdirSync(root, { recursive: true });
    const content = `${"x".repeat(64 * 1024)}end-marker`;
    writeFileSync(join(root, "large.ts"), content);
    try {
      const read = readRemoteAccessTextFile({
        sourceRoot: root,
        relativePath: "large.ts",
        ...remoteAccessReadLimits({ max_bytes: 180 * 1024, max_lines: 4_000 }),
      });
      assert.equal(read.content, content);
      assert.equal(read.truncated, false);
      assert.match(read.expected_base ?? "", /^[a-f0-9]{64}$/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  // contract-test: direct surface=sdks.npm assertions=projects.files.no-server-decryption-authority,projects.surface.semantic-parity
  it("trims escaped text to the exact serialized envelope budget and removes its write base", () => {
    const root = join(tmpdir(), `openmates-browser-escaped-budget-${Date.now()}`);
    mkdirSync(root, { recursive: true });
    const content = "\\".repeat(180 * 1024);
    writeFileSync(join(root, "escaped.txt"), content);
    try {
      const read = readRemoteAccessTextFile({
        sourceRoot: root,
        relativePath: "escaped.txt",
        ...remoteAccessReadLimits({ max_bytes: 180 * 1024, max_lines: 4_000 }),
      });
      assert.equal(read.truncated, false);
      const serialized = serializeRemoteAccessSuccessResponse(read);
      const response = JSON.parse(serialized) as { result: typeof read };
      assert.ok(new TextEncoder().encode(serialized).byteLength <= 200 * 1024);
      assert.ok(response.result.content.length < content.length);
      assert.equal(response.result.truncated, true);
      assert.equal(response.result.expected_base, null);
      assert.equal(response.result.sizeBytes, content.length);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
