/**
 * Unit tests for Project remote-access bridge primitives.
 *
 * Purpose: verify source-root bounds, default cache layout, deterministic
 * high-risk path policy, and capped rg search before CLI bridge wiring.
 * Security: uses injected rg output only; no shell commands or repository files
 * are read by these tests.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/remoteAccess.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { join } from "node:path";

import { classifyProjectFileRisk } from "../src/projectFileRisk.ts";
import { resolveRemoteCachePath, searchRemoteSource } from "../src/remoteAccess.ts";

describe("Project remote-access bridge primitives", () => {
  it("stores preview cache under ~/.openmates/remote-cache/<source-id> by default", () => {
    assert.equal(
      resolveRemoteCachePath("source-1", "/home/alice"),
      join("/home/alice", ".openmates", "remote-cache", "source-1"),
    );
  });

  it("classifies built-in and user-protected paths as high-risk", () => {
    assert.deepEqual(classifyProjectFileRisk(".env").reasons, ["secret_or_environment_file"]);
    assert.equal(classifyProjectFileRisk("src/App.svelte").isHighRisk, false);
    assert.deepEqual(
      classifyProjectFileRisk("src/components/BillingCard.svelte", ["src/components/**"]).reasons,
      ["user_protected_pattern"],
    );
  });

  it("runs rg inside the source root and filters capped safe matches", async () => {
    const seen: Array<{ args: string[]; cwd: string }> = [];
    const result = await searchRemoteSource({
      query: "Project",
      sourceRoot: "/workspace/repo",
      maxResults: 2,
      runRg: async (args, cwd) => {
        seen.push({ args, cwd });
        return [
          JSON.stringify({ type: "match", data: { path: { text: "src/App.svelte" }, line_number: 4, lines: { text: "Project UI" } } }),
          JSON.stringify({ type: "match", data: { path: { text: ".env" }, line_number: 1, lines: { text: "SECRET=1" } } }),
          JSON.stringify({ type: "match", data: { path: { text: "src/Second.svelte" }, line_number: 8, lines: { text: "Project card" } } }),
          JSON.stringify({ type: "match", data: { path: { text: "src/Third.svelte" }, line_number: 9, lines: { text: "Project row" } } }),
        ].join("\n");
      },
    });

    assert.equal(seen[0]?.cwd, "/workspace/repo");
    assert.deepEqual(seen[0]?.args, ["--json", "--line-number", "--", "Project", "."]);
    assert.deepEqual(result.matches.map((match) => match.path), ["src/App.svelte", "src/Second.svelte"]);
    assert.equal(result.omitted, 1);
    assert.equal(result.excluded, 1);
  });
});
