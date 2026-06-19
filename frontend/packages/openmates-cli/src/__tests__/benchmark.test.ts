// frontend/packages/openmates-cli/src/__tests__/benchmark.test.ts
//
// Direct unit coverage for the model benchmark runner.
// The CLI command tests verify argument wiring, while this colocated test keeps
// the benchmark module itself covered by the repo's session test mapper.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createBenchmarkEmbedReferenceBlock, handleBenchmark } from "../benchmark.js";

describe("handleBenchmark", () => {
  it("expands comparison dry-runs without requiring a logged-in session", async () => {
    const originalWrite = process.stdout.write;
    let output = "";
    process.stdout.write = ((chunk: string | Uint8Array) => {
      output += chunk.toString();
      return true;
    }) as typeof process.stdout.write;

    try {
      await handleBenchmark(
        { hasSession: () => false } as never,
        "model",
        ["google/gemini-3.5-flash", "google/gemini-3-flash-preview"],
        { compare: true, suite: "quick", "dry-run": true, json: true },
      );
    } finally {
      process.stdout.write = originalWrite;
    }

    const result = JSON.parse(output) as {
      status: string;
      compare: boolean;
      targetModels: string[];
      summary: { total: number; skipped: number };
    };

    assert.equal(result.status, "planned");
    assert.equal(result.compare, true);
    assert.deepEqual(result.targetModels, ["google/gemini-3.5-flash", "google/gemini-3-flash-preview"]);
    assert.equal(result.summary.total, 10);
    assert.equal(result.summary.skipped, 10);
  });

  it("filters dry-runs to selected case ids", async () => {
    const originalWrite = process.stdout.write;
    let output = "";
    process.stdout.write = ((chunk: string | Uint8Array) => {
      output += chunk.toString();
      return true;
    }) as typeof process.stdout.write;

    try {
      await handleBenchmark(
        { hasSession: () => false } as never,
        "model",
        ["anthropic/claude-haiku-4-5-20251001"],
        { suite: "quick", case: "quick-image-brandenburger-tor", "dry-run": true, json: true },
      );
    } finally {
      process.stdout.write = originalWrite;
    }

    const result = JSON.parse(output) as { summary: { total: number; skipped: number } };

    assert.equal(result.summary.total, 1);
    assert.equal(result.summary.skipped, 1);
  });

  it("formats image benchmark attachments as backend-resolvable JSON embed refs", () => {
    const reference = createBenchmarkEmbedReferenceBlock("embed-123", "image");

    assert.match(reference, /^\n\n```json\n/);
    assert.match(reference, /```$/);
    assert.equal(reference.includes("[!](embed:"), false);
    assert.equal(reference.includes(JSON.stringify({ type: "image", embed_id: "embed-123" })), true);
  });
});
