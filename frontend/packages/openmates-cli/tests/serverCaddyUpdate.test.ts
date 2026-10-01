// contract-test-file: tooling
import { it, after } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { applyCaddyPathUpdate, caddyHostOperation, mergeCaddyPaths, mergeCaddyRelease, officialUploadOrigins, readCaddyUpdateState, renderOfficialUploadCaddyTemplate, resolveCaddyProfile, validateOfficialUploadCaddy, verifyCaddyCoreRoutes, verifyCaddyUploadRoutes } from "../src/serverCaddyUpdate.ts";
import { caddyUpdatePlan } from "../src/server.ts";

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

// contract-test: supporting surface=cli assertions=server-management.host.preflight-caddy-continuous
it("keeps prod and dev upload routes scoped while preserving Origin gates and trusted environment headers", () => {
  const template = readFileSync(new URL("../../../../deployment/upload_server/Caddyfile", import.meta.url), "utf8");
  const deployed = renderOfficialUploadCaddyTemplate(template, "upload.example.test", "admin@example.test");
  const expectedOrigins = officialUploadOrigins(deployed);
  const currentUpload = deployed.replace("@upload_api path /v1/upload/*", "@upload_api path /v1/upload/* /operator/*");
  const targetUpload = deployed.replaceAll("@upload_api path /v1/upload/*", "@upload_api path /v1/upload/* /v1/upload/new/*");
  validateOfficialUploadCaddy(currentUpload);
  const merged = mergeCaddyPaths({ current: currentUpload, target: targetUpload, site: null, scopeAware: true });
  assert.deepEqual(Object.keys(merged.paths).filter(key => key.endsWith("/@upload_api")), ["@prod_origin/@upload_api", "@dev_origin/@upload_api"]);
  assert.match(merged.content, /@upload_api path \/v1\/upload\/\* \/v1\/upload\/new\/\* \/operator\/\*/);
  assert.equal((merged.content.match(/@upload_api path \/v1\/upload\/\* \/v1\/upload\/new\/\*/g) ?? []).length, 2);
  assert.equal((merged.content.match(/header_up X-Target-Env "prod"/g) ?? []).length, 2);
  assert.equal((merged.content.match(/header_up X-Target-Env "dev"/g) ?? []).length, 2);
  assert.match(merged.content, /@prod_origin expression \{header\.Origin\}/);
  assert.match(merged.content, /@dev_origin expression \{header\.Origin\}/);
  assert.throws(() => mergeCaddyPaths({ current: currentUpload, target: targetUpload, site: null }), /caddy_ambiguous_path_matcher/);
  assert.throws(() => validateOfficialUploadCaddy(currentUpload.replaceAll('header_up X-Target-Env "dev"', 'header_up X-Target-Env "prod"')), /structure_missing/);
  const devHeader = 'header_up X-Target-Env "dev"';
  const devParts = deployed.split(devHeader);
  assert.equal(devParts.length, 3);
  const headerOnlyInOptions = `${devParts[0]}${devHeader}\n\t\t\t\t\t${devHeader}${devParts[1]}${devParts[2]}`;
  assert.equal((headerOnlyInOptions.match(/header_up X-Target-Env "dev"/g) ?? []).length, 2);
  assert.throws(() => validateOfficialUploadCaddy(headerOnlyInOptions, expectedOrigins), /structure_missing/);
  for (const mutation of [
    'header_up +X-Target-Env "prod"',
    'header_up -x-target-env',
    'header_up -X-Target-*',
    'header_up -*',
    'header_up X-TARGET-ENV "^dev$" "prod"',
  ]) {
    const competing = deployed.replace(devHeader, `${devHeader}\n\t\t\t\t\t${mutation}`);
    assert.throws(() => validateOfficialUploadCaddy(competing, expectedOrigins), /structure_missing/, mutation);
  }
  const withOperatorProxy = deployed.replace(
    "\t}\n\n\t# Requests from the dev web app",
    "\t\thandle /operator/* {\n\t\t\treverse_proxy localhost:8000 {\n\t\t\t\theader_up   X-Target-Env   prod\n\t\t\t\theader_up X-Trace \"keep\"\n\t\t\t}\n\t\t}\n\t}\n\n\t# Requests from the dev web app",
  );
  assert.notEqual(withOperatorProxy, deployed);
  assert.doesNotThrow(() => validateOfficialUploadCaddy(withOperatorProxy, expectedOrigins));
  const swapped = deployed
    .replace(`@prod_origin expression {header.Origin} == "${expectedOrigins.prod}"`, `@prod_origin expression {header.Origin} == "${expectedOrigins.dev}"`)
    .replace(`@dev_origin expression {header.Origin} == "${expectedOrigins.dev}"`, `@dev_origin expression {header.Origin} == "${expectedOrigins.prod}"`);
  assert.throws(() => validateOfficialUploadCaddy(swapped, expectedOrigins), /origin_mismatch/);
  assert.throws(() => validateOfficialUploadCaddy(deployed.replace(`@dev_origin expression {header.Origin} == "${expectedOrigins.dev}"`, `@dev_origin expression {header.Origin} == "${expectedOrigins.prod}"`)), /origin_conflict/);
  assert.equal(resolveCaddyProfile("upload", "official-upload"), "official-upload");
  assert.equal(resolveCaddyProfile("upload", undefined, "official-upload"), "official-upload");
  assert.throws(() => resolveCaddyProfile("core", "official-upload"), /profile_unsupported/);
  assert.throws(() => resolveCaddyProfile("upload", "official-upload", "self-host"), /conflicts_with_baseline/);
});

// contract-test: supporting surface=cli assertions=server-management.host.preflight-caddy-continuous
it("proves both trusted upload preflights and denies an unknown Origin before accepting Caddy", async () => {
  const origins = { prod: "https://openmates.org", dev: "https://app.dev.openmates.org" };
  const seen: string[] = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const path = new URL(String(url)).pathname;
    if (path === "/health") return new Response(null, { status: 200 });
    const origin = new Headers(init?.headers).get("origin") ?? "";
    seen.push(origin);
    if (origin === origins.prod || origin === origins.dev) {
      return new Response(null, { status: 200, headers: { "access-control-allow-origin": origin, "access-control-allow-credentials": "true", "access-control-allow-methods": "POST, OPTIONS" } });
    }
    throw new TypeError("Caddy aborted unknown Origin");
  };
  await verifyCaddyUploadRoutes("https://upload.example.test", origins, fetcher as typeof fetch);
  assert.deepEqual(seen, [origins.prod, origins.dev, "https://openmates-route-probe.invalid"]);
  const allowedUnknown = async (url: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const origin = new Headers(init?.headers).get("origin") ?? "";
    if (new URL(String(url)).pathname === "/health") return new Response(null, { status: 200 });
    return new Response(null, { status: 200, headers: { "access-control-allow-origin": origin, "access-control-allow-credentials": "true", "access-control-allow-methods": "POST, OPTIONS" } });
  };
  await assert.rejects(verifyCaddyUploadRoutes("https://upload.example.test", origins, allowedUnknown as typeof fetch), /caddy_upload_unknown_origin_allowed/);
  const failedUnknown = async (url: string | URL | Request, init?: RequestInit): Promise<Response> => {
    if (new URL(String(url)).pathname === "/health") return new Response(null, { status: 200 });
    const origin = new Headers(init?.headers).get("origin") ?? "";
    if (origin === "https://openmates-route-probe.invalid") return new Response(null, { status: 500 });
    return new Response(null, { status: 200, headers: { "access-control-allow-origin": origin, "access-control-allow-credentials": "true", "access-control-allow-methods": "POST, OPTIONS" } });
  };
  await assert.rejects(verifyCaddyUploadRoutes("https://upload.example.test", origins, failedUnknown as typeof fetch), /caddy_upload_unknown_origin_allowed/);
  const missingDev = async (url: string | URL | Request, init?: RequestInit): Promise<Response> => {
    if (new URL(String(url)).pathname === "/health") return new Response(null, { status: 200 });
    const origin = new Headers(init?.headers).get("origin") ?? "";
    return new Response(null, { status: origin === origins.dev ? 403 : 200, headers: { "access-control-allow-origin": origin, "access-control-allow-credentials": "true", "access-control-allow-methods": "POST, OPTIONS" } });
  };
  await assert.rejects(verifyCaddyUploadRoutes("https://upload.example.test", origins, missingDev as typeof fetch), /caddy_upload_dev_preflight_failed/);
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

async function withHostFixture(run: (configPath: string, trace: string) => Promise<void>, initial = current) {
  const root = mkdtempSync(join(directory, "host-"));
  const configPath = join(root, "Caddyfile"), trace = join(root, "calls");
  writeFileSync(configPath, initial, { mode: 0o640 });
  const caddy = join(root, "caddy"), systemctl = join(root, "systemctl");
  writeFileSync(caddy, `#!${process.execPath}\nconst fs = require('node:fs');\nfs.appendFileSync(${JSON.stringify(trace)}, 'validate\\n');\nprocess.exit(fs.readFileSync(process.argv[4], 'utf8').includes('INVALID') ? 1 : 0);\n`);
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

// contract-test: supporting surface=cli assertions=server-management.update.safety-sequence,server-management.host.preflight-caddy-continuous
it("adopts a dual-origin upload Caddyfile through the atomic host transaction and persists its profile", async () => {
  const template = readFileSync(new URL("../../../../deployment/upload_server/Caddyfile", import.meta.url), "utf8");
  const deployed = renderOfficialUploadCaddyTemplate(template, "upload.example.test", "admin@example.test");
  const targetUpload = deployed.replaceAll("@upload_api path /v1/upload/*", "@upload_api path /v1/upload/* /v1/upload/new/*");
  await withHostFixture(async (configPath, trace) => {
    assert.throws(() => caddyUpdatePlan(directory, "upload", null, { "caddy-config": configPath }), /caddy_profile_required_official_upload/);
    assert.equal(caddyUpdatePlan(directory, "upload", null, { "caddy-config": configPath, "caddy-profile": "official-upload" }).profile, "official-upload");
    const result = await applyCaddyPathUpdate({ installPath: directory, role: "upload", configPath, site: null, target: targetUpload, revision, profile: "official-upload", verify: async () => {
      const live = readFileSync(configPath, "utf8");
      validateOfficialUploadCaddy(live);
      assert.match(live, /\/v1\/upload\/new\/\*/);
    } });
    assert.equal(result.status, "updated");
    assert.equal(readCaddyUpdateState(join(directory, ".openmates/caddy/upload.json"), configPath, null)?.profile, "official-upload");
    assert.equal(caddyUpdatePlan(directory, "upload", null, { "caddy-config": configPath }).profile, "official-upload");
    assert.equal(readFileSync(trace, "utf8"), "validate\nreload\nis-active\n");
  }, deployed);
});

// contract-test: supporting surface=cli assertions=server-management.update.safety-sequence,server-management.host.preflight-caddy-continuous
it("rolls back upload Caddy changes and withholds profile state when unknown Origin is accepted", async () => {
  const template = readFileSync(new URL("../../../../deployment/upload_server/Caddyfile", import.meta.url), "utf8");
  const deployed = renderOfficialUploadCaddyTemplate(template, "upload.example.test", "admin@example.test");
  const targetUpload = deployed.replaceAll("@upload_api path /v1/upload/*", "@upload_api path /v1/upload/* /v1/upload/new/*");
  const origins = officialUploadOrigins(deployed);
  await withHostFixture(async (configPath) => {
    const fetcher = async (url: string | URL | Request, init?: RequestInit): Promise<Response> => {
      if (new URL(String(url)).pathname === "/health") return new Response(null, { status: 200 });
      const origin = new Headers(init?.headers).get("origin") ?? "";
      return new Response(null, { status: 200, headers: { "access-control-allow-origin": origin, "access-control-allow-credentials": "true", "access-control-allow-methods": "POST, OPTIONS" } });
    };
    await assert.rejects(applyCaddyPathUpdate({
      installPath: directory, role: "upload-denied", configPath, site: null, target: targetUpload, revision, profile: "official-upload",
      verify: () => verifyCaddyUploadRoutes("https://upload.example.test", origins, fetcher as typeof fetch),
    }), /caddy_upload_unknown_origin_allowed/);
    assert.equal(readFileSync(configPath, "utf8"), deployed);
    assert.equal(existsSync(join(directory, ".openmates/caddy/upload-denied.json")), false);
  }, deployed);
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
