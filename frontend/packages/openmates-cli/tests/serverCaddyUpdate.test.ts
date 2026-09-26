// contract-test-file: tooling
import { it, after } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { applyCaddyPathUpdate, caddyHostOperation, mergeCaddyPaths, mergeCaddyRelease, readCaddyUpdateState, verifyCaddyCoreRoutes } from "../src/serverCaddyUpdate.ts";

const directory = mkdtempSync(join(tmpdir(), "openmates-caddy-unit-"));
after(() => rmSync(directory, { recursive: true, force: true }));
const revision = "a".repeat(40);
const current = "api.example.test {\n  @actual {\n    path /v1/auth/* /custom/* # operator route\n    header Origin https://app.example.test\n  }\n  @public path /v1/auth/*\n  handle @actual {\n    reverse_proxy localhost:8000\n  }\n}\n";
const target = current.replaceAll("path /v1/auth/*", "path /v1/auth/* /v1/workflows /v1/workflows/*");

it("adopts workflow roots and subpaths without changing origins, TLS, custom routes, or other sites", () => {
  const unrelated = "other.example.test {\n  @public path /private\n  respond 403\n}\n";
  const result = mergeCaddyPaths({ current: current + unrelated, target, site: "api.example.test" });
  assert.match(result.content, /path \/v1\/auth\/\* \/v1\/workflows \/v1\/workflows\/\* \/custom\/\* # operator route/);
  assert.ok(result.content.endsWith(unrelated));
  assert.match(result.content, /header Origin https:\/\/app.example.test/);
  assert.equal(mergeCaddyPaths({ current: result.content, target, site: "api.example.test" }).content, result.content);
});

it("rehearses first adoption against the release's complete core matchers", () => {
  const release = readFileSync(new URL("../../../../deployment/prod_server/Caddyfile", import.meta.url), "utf8");
  const old = release.replaceAll(" /v1/workflows /v1/workflows/*", "");
  const result = mergeCaddyPaths({ current: old, target: release, site: "api.openmates.org" });
  assert.equal(result.content, release);
});

it("rejects missing and ambiguous managed matchers", () => {
  assert.throws(() => mergeCaddyPaths({ current: current.replace("@public path", "@custom path"), target, site: null }), /caddy_matcher_missing/);
  assert.throws(() => mergeCaddyPaths({ current: current + "@public path /another\n", target, site: null }), /caddy_ambiguous/);
});

it("merges complete future handler changes and removals while preserving independent operator edits", () => {
  const base = "email admin@example.test\n\n# host settings\n# one\n# two\n# three\n# four\n\nhandle /old {\n  respond 200\n}\n";
  const local = base.replace("admin@example.test", "operator@example.test");
  const next = base.replace("/old", "/new").replace("respond 200", "respond 204");
  assert.equal(mergeCaddyRelease(local, base, next), next.replace("admin@example.test", "operator@example.test"));
  assert.throws(() => mergeCaddyRelease(base.replace("respond 200", "respond 403"), base, next), /caddy_local_config_conflict/);
});

it("fails closed on corrupt or mismatched baseline state", () => {
  const path = join(directory, "bad-state.json");
  writeFileSync(path, "{}");
  assert.throws(() => readCaddyUpdateState(path, "/etc/caddy/Caddyfile", null), /caddy_update_state_invalid/);
});

async function withHostFixture(run: (configPath: string, trace: string) => Promise<void>) {
  const root = mkdtempSync(join(directory, "host-"));
  const configPath = join(root, "Caddyfile"), trace = join(root, "calls");
  writeFileSync(configPath, current, { mode: 0o640 });
  const caddy = join(root, "caddy"), systemctl = join(root, "systemctl");
  writeFileSync(caddy, `#!/bin/sh\nprintf 'validate\\n' >> '${trace}'\n! rg -q INVALID "$3"\n`);
  writeFileSync(systemctl, `#!/bin/sh\nprintf '%s\\n' "$1" >> '${trace}'\nif [ "$1" = reload ] && [ -f '${root}/fail-reload' ]; then rm '${root}/fail-reload'; exit 1; fi\n`);
  chmodSync(caddy, 0o700); chmodSync(systemctl, 0o700);
  const oldPath = process.env.PATH;
  process.env.PATH = `${root}:${oldPath}`;
  try { await run(configPath, trace); } finally { process.env.PATH = oldPath; }
}

// contract-test: supporting surface=cli assertions=server-management.update.safety-sequence,server-management.host.preflight-caddy-continuous
it("validates before changing files and records the revision only after public verification", async () => {
  await withHostFixture(async (configPath, trace) => {
    let checked = false;
    const result = await applyCaddyPathUpdate({ installPath: directory, role: "success", configPath, site: null, target, revision, verify: async () => { checked = true; assert.match(readFileSync(configPath, "utf8"), /\/v1\/workflows/); } });
    assert.equal(result.status, "updated"); assert.equal(checked, true);
    assert.equal(readFileSync(result.backupPath!, "utf8"), current);
    assert.equal(readCaddyUpdateState(join(directory, ".openmates/caddy/success.json"), configPath, null)?.revision, revision);
    assert.equal(readFileSync(trace, "utf8"), "validate\nreload\nis-active\n");
  });
});

it("keeps live configuration intact when validation fails", async () => {
  await withHostFixture(async (configPath, trace) => {
    await assert.rejects(applyCaddyPathUpdate({ installPath: directory, role: "invalid", configPath, site: null, target: target.replaceAll("/v1/workflows", "/v1/INVALID"), revision, verify: async () => assert.fail("verify must not run") }), /caddy_validation_failed/);
    assert.equal(readFileSync(configPath, "utf8"), current);
    assert.equal(readFileSync(trace, "utf8"), "validate\n");
  });
});

it("restores and reloads the old file when reload fails", async () => {
  await withHostFixture(async (configPath, trace) => {
    writeFileSync(join(configPath, "..", "fail-reload"), "fail once");
    await assert.rejects(applyCaddyPathUpdate({ installPath: directory, role: "reload", configPath, site: null, target, revision, verify: async () => assert.fail("verify must not run") }), /caddy_reload_failed/);
    assert.equal(readFileSync(configPath, "utf8"), current);
    assert.equal(readFileSync(trace, "utf8"), "validate\nreload\nreload\nis-active\n");
  });
});

it("rolls back failed public route checks without advancing the baseline", async () => {
  await withHostFixture(async (configPath) => {
    await assert.rejects(applyCaddyPathUpdate({ installPath: directory, role: "public-fail", configPath, site: null, target, revision, verify: async () => { throw new Error("connection aborted"); } }), /caddy_public_route_verification_failed/);
    assert.equal(readFileSync(configPath, "utf8"), current);
    assert.equal(existsSync(join(directory, ".openmates/caddy/public-fail.json")), false);
  });
});

it("refuses to overwrite concurrent host edits", async () => {
  await withHostFixture(async (configPath) => {
    const expectedHash = createHash("sha256").update(current).digest("hex");
    writeFileSync(configPath, current + "# changed\n");
    assert.throws(() => caddyHostOperation({ action: "apply", configPath, expectedHash, content: target }), /caddy_config_changed/);
    assert.equal(readFileSync(configPath, "utf8"), current + "# changed\n");
  });
});

it("checks credentialed workflow CORS and nested routes and never accepts an aborted fetch", async () => {
  const oldFetch = globalThis.fetch;
  const paths: string[] = [];
  globalThis.fetch = async (url, init) => {
    const path = new URL(String(url)).pathname; paths.push(path);
    if (path.endsWith("availability")) return Response.json({ disabled: [] });
    const headers = { "access-control-allow-origin": "https://app.example.test", "access-control-allow-credentials": "true" };
    return new Response(null, { status: init?.method === "OPTIONS" ? 200 : 401, headers });
  };
  try {
    await verifyCaddyCoreRoutes("https://api.example.test", "https://app.example.test");
    assert.equal(paths.length, 4); assert.ok(paths.at(-1)?.endsWith("/runs"));
    globalThis.fetch = async () => { throw new TypeError("Load failed"); };
    await assert.rejects(verifyCaddyCoreRoutes("https://api.example.test", "https://app.example.test"), /Load failed/);
  } finally { globalThis.fetch = oldFetch; }
});
