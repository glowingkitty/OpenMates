/**
 * Root SDK OpenMatesClient is API-key only and never touches the CLI login.
 * A fake CLI login is planted in HOME/.openmates, OPENMATES_STATE_DIR and the
 * XDG dirs; the SDK must neither read those paths, spawn a keychain helper nor
 * send the planted cookie. Spec: surface.sdk sdk.library.explicit-headless.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import childProcess from "node:child_process";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import os from "node:os";
import path from "node:path";

const FAKE_COOKIE = "cli-login-cookie-must-never-leave-the-cli";
const requiredVectors = JSON.parse(fs.readFileSync(new URL("../../../../tests/sdk-conformance/fixtures/sdk-api-key-required.json", import.meta.url), "utf8")) as {
  code: string; message_contains: string; vectors: Array<{ id: string; api_key: string | null; expected_code: string | null }>;
};

function plantCliLogin(root: string): { home: string; state: string; cliPaths: string[] } {
  const home = path.join(root, "home");
  const state = path.join(root, "state");
  const cliPaths = [path.join(home, ".openmates"), state, path.join(root, "xdg-config"), path.join(root, "xdg-data")];
  for (const dir of cliPaths) {
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(path.join(dir, "session.json"), JSON.stringify({ cookies: { auth_refresh_token: FAKE_COOKIE }, ws_token: FAKE_COOKIE }));
  }
  return { home, state, cliPaths };
}

// contract-test: direct surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
test("root OpenMatesClient requires an explicit API key and never uses the CLI login", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "openmates-sdk-guard-"));
  const { home, state, cliPaths } = plantCliLogin(root);
  const saved = { ...process.env };
  const savedFs = { readFileSync: fs.readFileSync, existsSync: fs.existsSync, openSync: fs.openSync, readdirSync: fs.readdirSync, statSync: fs.statSync };
  const savedCp = { spawn: childProcess.spawn, spawnSync: childProcess.spawnSync, execFile: childProcess.execFile, execFileSync: childProcess.execFileSync };
  const savedFetch = globalThis.fetch;
  const touched: string[] = [];
  const spawned: string[] = [];
  const requests: Array<{ url: string; headers: Record<string, string> }> = [];
  try {
    Object.assign(process.env, {
      HOME: home, USERPROFILE: home, OPENMATES_STATE_DIR: state,
      XDG_CONFIG_HOME: path.join(root, "xdg-config"), XDG_DATA_HOME: path.join(root, "xdg-data"),
    });
    delete process.env.OPENMATES_API_KEY;
    const sdk = await import("../src/sdkRootClient.ts");
    const { OpenMatesConfigError } = await import("../src/sdk.ts");
    const barrel = fs.readFileSync(new URL("../src/index.ts", import.meta.url), "utf8");
    assert.match(barrel, /export \{ OpenMatesClient, OpenMatesApiKeyRequiredError, SDK_API_KEY_REQUIRED_CODE \} from "\.\/sdkRootClient\.js";/);

    // Record every filesystem path and child process from here on.
    const record = (name: keyof typeof savedFs) => (target: unknown, ...rest: unknown[]) => {
      touched.push(String(target));
      return (savedFs[name] as (...args: unknown[]) => unknown)(target, ...rest);
    };
    for (const name of Object.keys(savedFs) as Array<keyof typeof savedFs>) (fs as unknown as Record<string, unknown>)[name] = record(name);
    for (const name of Object.keys(savedCp)) {
      (childProcess as unknown as Record<string, unknown>)[name] = (command: unknown) => { spawned.push(String(command)); throw new Error("SDK must not spawn processes"); };
    }
    syncBuiltinESMExports();
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(input), headers: Object.fromEntries(new Headers(init?.headers).entries()) });
      return new Response(JSON.stringify({ id: "account" }), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch;

    for (const options of [undefined, {}, { apiKey: "" }, { apiKey: "  " }] as unknown[]) {
      assert.throws(() => new sdk.OpenMatesClient(options as never), (error: unknown) =>
        error instanceof sdk.OpenMatesApiKeyRequiredError && error instanceof OpenMatesConfigError
        && error.code === "OPENMATES_SDK_API_KEY_REQUIRED" && /Settings → Developers/.test(error.message));
      assert.throws(() => sdk.OpenMatesClient.load(options as never), sdk.OpenMatesApiKeyRequiredError);
    }
    // Shared cross-SDK vectors (Python and Rust read the same file); read before fs is recorded.
    assert.equal(requiredVectors.code, sdk.SDK_API_KEY_REQUIRED_CODE);
    for (const vector of requiredVectors.vectors) {
      const options = vector.api_key === null ? {} : { apiKey: vector.api_key, apiUrl: "https://api.example.invalid", deviceIdPath: path.join(root, "vectors", "device-id") };
      if (vector.expected_code === null) {
        assert.ok(new sdk.OpenMatesClient(options as never), vector.id);
        continue;
      }
      assert.throws(() => new sdk.OpenMatesClient(options as never), (error: unknown) =>
        error instanceof sdk.OpenMatesApiKeyRequiredError && error.code === vector.expected_code
        && error.message.includes(requiredVectors.message_contains), vector.id);
    }
    for (const legacy of [{ session: {} }, { loadStoredSession: true }, { apiKey: "sk-api-x", loadStoredSession: false }]) {
      assert.throws(() => new sdk.OpenMatesClient(legacy as never), sdk.OpenMatesApiKeyRequiredError);
    }

    const deviceIdPath = path.join(root, "sdk-only", "device-id");
    const client = new sdk.OpenMatesClient({ apiKey: "sk-api-guardtest", apiUrl: "https://api.example.invalid", deviceIdPath });
    await client.account.info();
    assert.equal(requests.length, 1);
    assert.equal(requests[0].headers.authorization, "Bearer sk-api-guardtest");
    assert.equal(requests[0].headers.cookie, undefined);
    assert.doesNotMatch(JSON.stringify(requests), new RegExp(FAKE_COOKIE));
    const cliTouched = touched.filter(entry => cliPaths.some(dir => entry === dir || entry.startsWith(dir + path.sep)));
    assert.deepEqual(cliTouched, [], "SDK accessed CLI credential/state locations");
    assert.deepEqual(spawned, [], "SDK spawned a keychain or CLI process");
  } finally {
    Object.assign(fs, savedFs);
    Object.assign(childProcess, savedCp);
    syncBuiltinESMExports();
    globalThis.fetch = savedFetch;
    for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
    Object.assign(process.env, saved);
    fs.rmSync(root, { recursive: true, force: true });
  }
});
