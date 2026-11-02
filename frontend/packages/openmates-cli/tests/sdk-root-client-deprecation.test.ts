/** Root SDK OpenMatesClient: implicit CLI-login loading warns once (0.29.x). */
// contract-test-file: tooling
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

test("implicit stored-CLI-session loading emits one OPENMATES_SDK_CLI_SESSION DeprecationWarning", async () => {
  // Isolated, empty CLI state: no real login is read or written.
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "openmates-root-client-"));
  const previous = process.env.OPENMATES_STATE_DIR;
  process.env.OPENMATES_STATE_DIR = state;
  const warnings: Error[] = [];
  const listener = (warning: Error) => { warnings.push(warning); };
  process.on("warning", listener);
  try {
    // The root barrel re-exports exactly this class (checked below); importing
    // the module itself avoids loading the CLI command graph in a unit test.
    const sdk = await import("../src/sdkRootClient.ts");
    const barrel = fs.readFileSync(new URL("../src/index.ts", import.meta.url), "utf8");
    assert.match(barrel, /export \{ OpenMatesClient, SDK_CLI_SESSION_DEPRECATION_CODE \} from "\.\/sdkRootClient\.js";/);
    assert.doesNotMatch(barrel, /^\s*OpenMatesClient,\s*$/m);
    const { OpenMatesClient: CliClient } = await import("../src/client.ts");
    // Explicit opt-out never warns.
    new sdk.OpenMatesClient({ loadStoredSession: false, apiUrl: "https://api.example.invalid" });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(warnings.filter(w => (w as { code?: string }).code === sdk.SDK_CLI_SESSION_DEPRECATION_CODE).length, 0);
    // Implicit loading warns exactly once per process, via constructor or load().
    const first = new sdk.OpenMatesClient({ apiUrl: "https://api.example.invalid" });
    sdk.OpenMatesClient.load({ apiUrl: "https://api.example.invalid" });
    await new Promise(resolve => setImmediate(resolve));
    const emitted = warnings.filter(w => (w as { code?: string }).code === "OPENMATES_SDK_CLI_SESSION");
    assert.equal(emitted.length, 1);
    assert.equal(emitted[0].name, "DeprecationWarning");
    // The subclass keeps the full existing client API and identity.
    assert.ok(first instanceof CliClient);
    assert.equal(first.hasSession(), false);
  } finally {
    process.off("warning", listener);
    if (previous === undefined) delete process.env.OPENMATES_STATE_DIR; else process.env.OPENMATES_STATE_DIR = previous;
    fs.rmSync(state, { recursive: true, force: true });
  }
});
