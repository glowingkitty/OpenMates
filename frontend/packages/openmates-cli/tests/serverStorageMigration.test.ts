// contract-test-file: infrastructure
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseStorageMigrationOutcome, parseStorageMigrationProgress, storageMigrationCommand,
} from "../src/serverStorageMigration.ts";

test("server migration status exposes bounded progress and retry reasons without archive selectors", () => {
  const result = parseStorageMigrationProgress({
    automatic: { status: "pending", reason: "client_compatibility_enforcement_pending", retry_seconds: 60,
      source_commit: "a".repeat(40), reader_receipt: "private", user_id: "private" },
    message_segments: { copying: 12, verified: 5, reader_active: 1, private_object_key: "private" },
    message_pages: { read_enabled: 3, pruned: 0 },
    version_rows: { copied: 4, reader_active: 2, pruned: -1, stale: 1.5 },
    rollout: { reader_receipt: "private" },
  });
  assert.deepEqual(result, {
    automatic: { status: "pending", reason: "client_compatibility_enforcement_pending", retry_seconds: 60, source_commit: "a".repeat(40) },
    message_segments: { copying: 12, verified: 5, reader_active: 1 },
    message_pages: { read_enabled: 3, pruned: 0 },
    version_rows: { copied: 4, reader_active: 2 },
  });
  assert.equal(JSON.stringify(result).includes("private"), false);
});

test("migration coordinator rejects arbitrary states, reasons and malformed counters", () => {
  assert.deepEqual(parseStorageMigrationOutcome(null), { status: "paused", reason: "migration_coordinator_response_invalid" });
  assert.deepEqual(parseStorageMigrationOutcome({ status: "invented", reason: "secret" }), { status: "paused", reason: "migration_coordinator_response_invalid" });
  assert.deepEqual(parseStorageMigrationOutcome({ status: "paused", reason: "private selector", source_commit: "other", retry_seconds: 999999 }), { status: "paused" });
  assert.deepEqual(parseStorageMigrationProgress({ automatic: { status: "paused" }, message_pages: { pruned: "2" }, version_rows: [] }), {
    automatic: { status: "paused" }, message_pages: {},
  });
});

test("updater and status invoke exact bounded coordinator operations inside API container", () => {
  const prefix = ["compose", "-f", "core.yml"];
  assert.deepEqual(storageMigrationCommand(prefix, "auto", "A".repeat(40)), [
    ...prefix, "exec", "-T", "-e", `BUILD_COMMIT_SHA=${"a".repeat(40)}`,
    "api", "python", "/app/scripts/storage_rollout.py", "auto",
  ]);
  assert.deepEqual(storageMigrationCommand(prefix, "status"), [
    ...prefix, "exec", "-T", "api", "python", "/app/scripts/storage_rollout.py", "status",
  ]);
  assert.throws(() => storageMigrationCommand(prefix, "auto", "bad-revision"), /source_revision_unavailable/);
  assert.deepEqual(prefix, ["compose", "-f", "core.yml"]);
});

test("runtime inventory renewal runs every minute within the three-minute lease", async () => {
  const { planRuntimeMonitoringServices } = await import("../src/serverPlanning.ts");
  const plan = planRuntimeMonitoringServices({ role: "core", installPath: "/srv/openmates", executablePath: "/usr/bin/openmates" });
  assert.match(plan.timer, /OnUnitActiveSec=1min/);
  assert.match(plan.unit, /server monitoring run --role core/);
  assert.equal(parseStorageMigrationProgress({ automatic: { status: "prune_enabled" },
    legacy_full_graph: { status: "paused", reason: "metadata_retention_policy_pending" } }).legacy_full_graph?.reason,
    "metadata_retention_policy_pending");
});


test("installing monitoring refreshes an existing timer and replaces in-flight CLI execution", async () => {
  const { readFileSync } = await import("node:fs");
  const { runInNewContext } = await import("node:vm");
  const { join } = await import("node:path");
  const source = readFileSync(new URL("../src/server.ts", import.meta.url), "utf8");
  const start = source.indexOf("async function installRuntimeMonitoringServices(");
  const end = source.indexOf("\nasync function autoInstallRuntimeMonitoringServices", start);
  // Execute the installer against a simulated already-active systemd cohort.
  // This proves update behavior without touching host services or notification providers.
  const installer = source.slice(start, end)
    .replace("installPath: string, role: ServerRole", "installPath, role")
    .replace("): Promise<void>", ")")
    .replace(".filter((entry): entry is [string, string] =>", ".filter((entry) =>");
  const commands = [];
  const timerName = "openmates-core-runtime-monitor.timer";
  const serviceName = "openmates-core-runtime-monitor.service";
  const execute = runInNewContext(`(${installer})`, {
    process: { argv: ["node", "/installed/cli.js"] }, resolve: value => value, join,
    planRuntimeMonitoringServices: () => ({ timerName, serviceName, unit: "new CLI", timer: "one minute",
      watchdogServiceName: "watchdog.service", watchdogTimerName: "watchdog.timer",
      watchdogUnit: "watchdog", watchdogTimer: "watchdog timer" }),
    runtimeNotificationConfig: () => ({}), getInstallDeploymentMode: () => "self_host",
    loadConfigForInstallPath: () => ({}), planOperationalMonitoring: () => ({ scheduleEnabled: false, digestServiceName: "digest.service",
      digestTimerName: "digest.timer", watchdogServiceName: "reports-watchdog.service", watchdogTimerName: "reports-watchdog.timer" }),
    existsSync: () => false, writeFileSync: () => {},
    shellQuote: value => value, execSync: command => commands.push(command),
    execFileSync: (command, args) => commands.push([command, ...args].join(" ")),
  });
  await execute("/registered/install", "core");
  assert.ok(commands.includes(`systemctl restart ${timerName}`));
  assert.ok(commands.includes(`systemctl --no-block try-restart ${serviceName}`));
  assert.ok(commands.indexOf("systemctl daemon-reload") < commands.indexOf(`systemctl restart ${timerName}`));
});


test("first source start builds exact clean provenance before creating containers and fails closed otherwise", async () => {
  const { readFileSync } = await import("node:fs");
  const { runInNewContext } = await import("node:vm");
  const source = readFileSync(new URL("../src/server.ts", import.meta.url), "utf8");
  const helperStart = source.indexOf("function sourceBuildCommitSha(");
  const helperEnd = source.indexOf("\nasync function serverStart", helperStart);
  const helper = source.slice(helperStart, helperEnd)
    .replace("installPath: string", "installPath").replace("): string", ")");
  const start = source.indexOf("async function serverStart(");
  const end = source.indexOf("\nasync function", start + 10);
  const handler = source.slice(start, end)
    .replace("flags: Record<string, string | boolean>", "flags").replace("): Promise<void>", ")");
  for (const scenario of [
    { mode: "source", dirty: false, revision: "A".repeat(40), expected: "a".repeat(40) },
    { mode: "source", dirty: true, revision: "a".repeat(40), expected: "" },
    { mode: "source", dirty: false, revision: "unknown", expected: "" },
    { mode: "source", dirty: false, unavailable: true, revision: "a".repeat(40), expected: "" },
    { mode: "image", dirty: false, revision: "a".repeat(40), expected: null },
  ]) {
    const calls = [];
    const api = runInNewContext(`${helper}\n({ start: ${handler} })`, {
      requireDocker: () => {}, resolveServerPath: () => "/registered/install",
      ensureGitWorkDirEnv: () => {}, ensureRuntimeMetricsDirectory: () => {}, warnIfMissingLlmCredentials: () => {},
      loadConfigForInstallPath: () => ({ defaultServices: ["api", "core-worker"] }),
      getServerRole: () => "core", getInstallMode: () => scenario.mode, getInstallDeploymentMode: () => "self_host",
      lifecycleServiceSelection: () => ({ requested: true, services: ["api", "core-worker"] }),
      composeArgs: () => ["compose", "-f", "fixture.yml"], shouldPullImages: () => true,
      exec: command => {
        if (scenario.unavailable) throw new Error("Git unavailable");
        return command.includes("status") ? (scenario.dirty ? " M backend/code.py" : "") : scenario.revision;
      },
      runInteractive: async (executable, args, cwd) => { calls.push({ executable, args: Array.from(args), cwd }); return 0; },
      console: { error: () => {} }, printJson: () => {}, process: { exit: () => { throw new Error("Unexpected exit"); } },
    });
    await api.start({ json: true });
    const operation = calls.map(call => call.args[3]);
    assert.deepEqual(operation, scenario.mode === "source" ? ["build", "up"] : ["pull", "up"]);
    if (scenario.mode === "source") {
      assert.deepEqual(calls[0].args, ["compose", "-f", "fixture.yml", "build", "--build-arg",
        `BUILD_COMMIT_SHA=${scenario.expected}`, "api", "core-worker"]);
    }
    assert.ok(calls.every(call => call.cwd === "/registered/install"));
  }
});
