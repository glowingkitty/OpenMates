/**
 * Unit tests for CLI E2E provisioning command guardrails.
 *
 * Run: cd frontend/packages/openmates-cli && npm run build && node --test tests/e2e-provisioning.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

function runCli(args: string[]): string {
  return execFileSync("node", ["dist/cli.js", ...args], {
    cwd: fileURLToPath(new URL("..", import.meta.url)),
    encoding: "utf-8",
    env: { ...process.env, TERM: "dumb" },
  });
}

describe("E2E provisioning command surface", () => {
  it("prints help without network access", () => {
    const output = runCli(["e2e", "--help"]);
    assert.ok(output.includes("E2E provisioning command"));
    assert.ok(output.includes("provision-auth-accounts"));
  });

  it("refuses production API URLs before creating artifacts", () => {
    assert.throws(
      () => runCli(["--api-url", "https://api.openmates.org", "e2e", "provision-auth-accounts", "--slot", "15", "--artifact", "/tmp/should-not-exist.env"]),
      /refuses production API URLs/,
    );
  });
});
