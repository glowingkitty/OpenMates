// frontend/packages/openmates-cli/src/__tests__/benchmark.test.ts
//
// Direct unit coverage for the model benchmark runner.
// The CLI command tests verify argument wiring, while this colocated test keeps
// the benchmark module itself covered by the repo's session test mapper.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { handleBenchmark } from "../benchmark.js";

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
});
