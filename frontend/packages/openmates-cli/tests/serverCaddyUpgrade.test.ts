// contract-test-file: tooling
import { it } from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execute = promisify(execFile);
const cli = fileURLToPath(new URL("../dist/cli.js", import.meta.url));
const version = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).version;
const revision = "b".repeat(40);
const probe = "/v1/embeds/chats/*/references/availability";
const template = `api.example.test {
  @actual {
    path /v1/auth/* ${probe}
    header Origin https://app.example.test
  }
  handle @actual {
    reverse_proxy localhost:8000
  }
}
`;
const current = template.replace(` ${probe}`, " /operator/*") + "operator.example.test {\n  respond 204\n}\n";

async function fixture(registered = true) {
  const root = mkdtempSync(join(tmpdir(), "openmates-caddy-upgrade-"));
  const install = join(root, "server with spaces");
  const state = join(root, "state");
  const bin = join(root, "bin");
  const config = join(root, "custom Caddyfile");
  const trace = join(root, "operations");
  const seen: string[] = [];
  const server = createServer((request, response) => {
    seen.push(`${request.method} ${request.url}`);
    if (request.method === "OPTIONS" && request.url?.endsWith("/references/availability")) {
      // Model the corrected route: a public wildcard would fail credentials.
      const live = readFileSync(config, "utf8");
      const delegatesToBackend = /\n\s*handle\s*\{\s*reverse_proxy localhost:8000/.test(live);
      response.setHeader("Access-Control-Allow-Origin", live.includes(probe) || delegatesToBackend ? request.headers.origin! : "*");
      response.setHeader("Access-Control-Allow-Credentials", "true");
      response.end();
    } else if (request.url === "/v1/features/availability") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ disabled: ["platform:workflows"] }));
    } else { response.writeHead(404).end(); }
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  mkdirSync(join(install, "backend", "core"), { recursive: true });
  mkdirSync(join(install, "frontend", "packages", "openmates-cli", "templates", "caddy", "core"), { recursive: true });
  mkdirSync(state);
  mkdirSync(bin);
  writeFileSync(join(install, "backend", "core", "docker-compose.yml"), "services: {}\n");
  writeFileSync(join(install, "frontend", "packages", "openmates-cli", "templates", "caddy", "core", "Caddyfile"), template);
  writeFileSync(join(install, ".env"), `DEPLOY_CORE_DOMAIN=http://127.0.0.1:${address.port}\nPRODUCTION_URL=https://app.example.test\n`);
  writeFileSync(config, current);
  if (registered) writeFileSync(join(state, "server.json"), JSON.stringify({ installPath: install, installMode: "source", composeProfile: "core", serverRole: "core", deploymentMode: "self_host" }));
  const executable = (name: string, content: string) => writeFileSync(join(bin, name), `#!/bin/sh\n${content}\n`, { mode: 0o755 });
  executable("git", `if [ "$1" = rev-parse ]; then echo ${revision}; else exit 1; fi`);
  executable("systemctl", 'if [ "$1" = show ]; then echo 0; else echo "systemctl $*" >> "$CADDY_TEST_TRACE"; if [ "$CADDY_TEST_REQUIRE_SUDO" = 1 ] && [ "$CADDY_TEST_PRIVILEGED" != 1 ]; then exit 1; fi; fi');
  executable("sudo", 'echo "sudo $*" >> "$CADDY_TEST_TRACE"\nif [ "$CADDY_TEST_SUDO_DENY" = 1 ]; then exit 1; fi\nif [ "$1" = -n ]; then shift; fi\nexport CADDY_TEST_PRIVILEGED=1\nexec "$@"');
  executable("caddy", 'echo "caddy $1" >> "$CADDY_TEST_TRACE"\nif [ "$CADDY_TEST_FAIL" = 1 ]; then exit 1; fi');
  executable("npm", 'echo "npm $*" >> "$CADDY_TEST_TRACE"');
  const run = async (args: string[], extra: Record<string, string> = {}) => execute(process.execPath, [cli, ...args], {
    cwd: install, timeout: 20_000, encoding: "utf8",
    env: { ...process.env, OPENMATES_STATE_DIR: state, OPENMATES_CLI_LATEST_VERSION: version, PATH: `${bin}:${process.env.PATH}`, CADDY_TEST_TRACE: trace, ...extra },
  });
  return { install, config, trace, seen, run,
    baseline: join(install, ".openmates", "caddy", "core.json"),
    cleanup: async () => {
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
      rmSync(root, { recursive: true, force: true });
    },
  };
}

// contract-test: direct surface=cli assertions=server-management.host.preflight-caddy-continuous,server-management.update.safety-sequence
it("upgrade updates configured Caddy from the installed server release after the package update", async () => {
  const f = await fixture();
  try {
    const result = JSON.parse((await f.run(["upgrade", "--package-manager", "npm", "--caddy-config", f.config, "--json"], { OPENMATES_CLI_LATEST_VERSION: "99.0.0" })).stdout);
    assert.equal(result.status, "success");
    assert.equal(result.caddy.status, "updated");
    assert.equal(result.caddy.revision, revision);
    const live = readFileSync(f.config, "utf8");
    assert.match(live, /\/references\/availability \/operator\/\*/);
    assert.ok(live.endsWith("operator.example.test {\n  respond 204\n}\n"));
    assert.equal(JSON.parse(readFileSync(f.baseline, "utf8")).template, template);
    assert.equal(readFileSync(result.caddy.backupPath, "utf8"), current);
    const operations = readFileSync(f.trace, "utf8");
    assert.match(operations, /npm install -g openmates@99\.0\.0[\s\S]*caddy validate[\s\S]*systemctl reload caddy/);
    assert.deepEqual(f.seen, ["OPTIONS /v1/embeds/chats/00000000-0000-4000-8000-000000000000/references/availability", "GET /v1/features/availability"]);
    const again = JSON.parse((await f.run(["update", "--caddy-config", f.config, "--json"])).stdout);
    assert.equal(again.status, "up_to_date");
    assert.equal(again.caddy.status, "unchanged");
  } finally { await f.cleanup(); }
});

// contract-test: direct surface=cli assertions=server-management.host.preflight-caddy-continuous,server-management.update.safety-sequence
it("failed automatic Caddy updates preserve the file and print an executable Caddy-only retry", async () => {
  const f = await fixture();
  try {
    const args = ["upgrade", "--caddy-config", f.config];
    const result = JSON.parse((await f.run([...args, "--json"], { CADDY_TEST_FAIL: "1" })).stdout);
    assert.equal(result.caddy.status, "pending");
    assert.equal(result.caddy.reason, "caddy_validation_failed");
    assert.equal(result.caddy.retryCommand, `sudo -v && openmates server caddy update --path '${f.install}' --role 'core' --caddy-config '${f.config}'`);
    assert.equal(readFileSync(f.config, "utf8"), current);
    assert.equal(existsSync(f.baseline), false);
    const text = (await f.run(args, { CADDY_TEST_FAIL: "1" })).stdout;
    assert.match(text, /Caddy: pending\nRun: sudo -v && openmates server caddy update/);
    const retried = JSON.parse((await f.run(["server", "caddy", "update", "--path", f.install, "--role", "core", "--caddy-config", f.config, "--json"])).stdout);
    assert.equal(retried.caddy, undefined);
    assert.equal(retried.status, "updated");
    assert.equal(JSON.parse(readFileSync(f.baseline, "utf8")).revision, revision);
  } finally { await f.cleanup(); }
});

// contract-test: direct surface=cli assertions=server-management.host.preflight-caddy-continuous
it("upgrade dry runs and unregistered checkouts provide the follow-up without host mutations", async () => {
  const f = await fixture(false);
  try {
    const planned = JSON.parse((await f.run(["upgrade", "--path", f.install, "--caddy-config", f.config, "--dry-run", "--json"])).stdout);
    assert.equal(planned.caddy.status, "planned");
    assert.match(planned.caddy.retryCommand, /server caddy update/);
    const unregistered = JSON.parse((await f.run(["upgrade", "--caddy-config", f.config, "--json"])).stdout);
    assert.equal(unregistered.caddy.status, "pending");
    assert.equal(existsSync(f.trace), false);
    assert.equal(existsSync(f.baseline), false);
    assert.equal(readFileSync(f.config, "utf8"), current);
    assert.deepEqual(f.seen, []);
  } finally { await f.cleanup(); }
});

// contract-test: direct surface=cli assertions=server-management.host.preflight-caddy-continuous,server-management.update.safety-sequence
it("the retry authenticates a root-managed service even when its custom Caddyfile is user-writable", async () => {
  const f = await fixture();
  try {
    const failed = JSON.parse((await f.run(["upgrade", "--caddy-config", f.config, "--json"], { CADDY_TEST_REQUIRE_SUDO: "1", CADDY_TEST_SUDO_DENY: "1" })).stdout);
    assert.equal(failed.caddy.status, "pending");
    assert.match(failed.caddy.retryCommand, /^sudo -v && openmates server caddy update/);
    assert.equal(readFileSync(f.config, "utf8"), current);
    assert.equal(existsSync(f.baseline), false);
    const retried = JSON.parse((await f.run(["server", "caddy", "update", "--path", f.install, "--caddy-config", f.config, "--json"], { CADDY_TEST_REQUIRE_SUDO: "1" })).stdout);
    assert.equal(retried.status, "updated");
    assert.ok(readFileSync(f.config, "utf8").includes(probe));
    assert.match(readFileSync(f.trace, "utf8"), /sudo -n systemctl reload caddy/);
  } finally { await f.cleanup(); }
});

// contract-test: direct surface=cli assertions=server-management.host.preflight-caddy-continuous
it("Caddy-only update verifies the packaged self-host catchall without requiring cloud matchers", async () => {
  const f = await fixture();
  try {
    const minimal = readFileSync(new URL("../templates/caddy/core/Caddyfile", import.meta.url), "utf8");
    const installedTemplate = join(f.install, "frontend", "packages", "openmates-cli", "templates", "caddy", "core", "Caddyfile");
    writeFileSync(installedTemplate, minimal);
    writeFileSync(f.config, minimal + "\n# operator setting\n");
    const before = readFileSync(f.config, "utf8");
    const result = JSON.parse((await f.run(["server", "caddy", "update", "--caddy-config", f.config, "--json"])).stdout);
    assert.equal(result.status, "unchanged");
    assert.equal(readFileSync(f.config, "utf8"), before);
    assert.equal(JSON.parse(readFileSync(f.baseline, "utf8")).template, minimal);
    assert.equal(f.seen.length, 2);
  } finally { await f.cleanup(); }
});

// contract-test: direct surface=cli assertions=server-management.host.preflight-caddy-continuous
it("Caddy-only planning failures include the exact retry before any host mutation", async () => {
  const f = await fixture();
  try {
    const missing = join(f.install, "missing Caddyfile");
    await assert.rejects(f.run(["server", "caddy", "update", "--path", f.install, "--caddy-config", missing]), (error: Error & { stderr?: string }) => {
      assert.match(error.stderr ?? "", /caddy_explicit_config_missing/);
      assert.ok(error.stderr?.includes(`sudo -v && openmates server caddy update --path '${f.install}' --role 'core' --caddy-config '${missing}'`));
      return true;
    });
    assert.equal(existsSync(f.trace), false);
    assert.equal(readFileSync(f.config, "utf8"), current);
  } finally { await f.cleanup(); }
});
