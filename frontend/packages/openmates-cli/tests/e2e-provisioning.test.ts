// contract-test-file: infrastructure
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

describe("E2E TOTP rollover guard", () => {
  it("waits into the next period when a generated code has under two seconds left", async () => {
    const { waitForSafeE2ETotpWindow } = await import(new URL("../dist/cli.js", import.meta.url).href);
    let now = 42 * 30_000 + 29_972;
    const sleeps: number[] = [];
    await waitForSafeE2ETotpWindow(
      () => now,
      async (milliseconds) => {
        sleeps.push(milliseconds);
        now += milliseconds;
      },
    );
    assert.deepEqual(sleeps, [78]);
    assert.equal(Math.floor(now / 30_000), 43);
  });

  it("does not delay a code with two seconds or more left", async () => {
    const { waitForSafeE2ETotpWindow } = await import(new URL("../dist/cli.js", import.meta.url).href);
    const sleeps: number[] = [];
    for (const now of [42 * 30_000, 42 * 30_000 + 28_000]) {
      await waitForSafeE2ETotpWindow(() => now, async (milliseconds) => {
        sleeps.push(milliseconds);
      });
    }
    assert.deepEqual(sleeps, []);
  });
});

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

  it("allows the reserved auth-test slot range", () => {
    const output = runCli(["e2e", "--help"]);
    assert.ok(output.includes("--slot <14-20>"));
  });

  it("requires the secret-backed invite before provisioning", () => {
    assert.throws(
      () => runCli(["--api-url", "https://api.dev.openmates.org", "e2e", "provision-auth-accounts", "--slot", "14"]),
      /OPENMATES_CLI_SIGNUP_INVITE_CODE is required/,
    );
  });
});
