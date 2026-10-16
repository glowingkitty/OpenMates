import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createTuiStartup, type TuiStartupServices } from "../src/tuiStartup.ts";
import { createInitialTuiState, renderTuiFrame } from "../src/tuiRenderer.ts";
import { checkTuiUpdate, deferTuiUpdate, buildSelfUpdatePlan, installTuiUpdate, checkSelfUpdateStatus, runSelfUpdate } from "../src/selfUpdate.ts";
import { cells, stripAnsi } from "../src/tuiText.ts";

const offer = () => ({ plan: buildSelfUpdatePlan({ channel: "dev" }), latestVersion: "99.0.0-alpha.1" });
function fixture(privacy: boolean, update: boolean) {
  const state = createInitialTuiState(); state.signedIn = true; state.input = "An unsent draft";
  const calls: string[] = [];
  let closed = false;
  const services: TuiStartupServices = {
    privacyOffer: async () => { calls.push("privacy-check"); return privacy; },
    privacyInstall: async () => { calls.push("privacy-install"); },
    updateCheck: async () => { calls.push("update-check"); return update ? offer() : null; },
    updateInstall: async () => { calls.push("update-install"); },
    updateSkip: () => { calls.push("update-skip"); },
  };
  const startup = createTuiStartup({ state, services, render: () => {}, closed: () => closed,
    ready: () => calls.push("workspace"), updated: () => calls.push("restart") });
  return { state, services, startup, calls, close: () => { closed = true; } };
}

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity,cli.surface.semantic-parity
test("startup admits the workspace only after privacy and update choices, preserving the draft", async () => {
  const f = fixture(true, true);
  await f.startup.start();
  assert.deepEqual(f.calls, ["privacy-check"]);
  assert.equal(f.state.startup?.kind, "privacy");
  const frame = renderTuiFrame(f.state, 73, 24);
  assert.match(frame, /Use enhanced offline personal data detection/);
  assert.doesNotMatch(frame, /DAILY INSPIRATION|Ask anything|An unsent draft/);
  await f.startup.handleKey("x", { name: "x" });
  assert.equal(f.state.input, "An unsent draft");
  await f.startup.handleKey("", { name: "f7" });
  assert.equal(f.state.startup?.kind, "update");
  assert.doesNotMatch(renderTuiFrame(f.state, 73, 24), /DAILY INSPIRATION|Ask anything/);
  await f.startup.handleKey("", { name: "return" });
  assert.deepEqual(f.calls, ["privacy-check", "update-check", "update-skip", "workspace"]);
  assert.equal(f.state.startup, null);
  assert.equal(f.state.input, "An unsent draft");
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity,cli.surface.semantic-parity
test("seen privacy and no update bypass gates, while unseen privacy is offered before login", async () => {
  const f = fixture(false, false); await f.startup.start();
  assert.deepEqual(f.calls, ["privacy-check", "update-check", "workspace"]);
  const guest = fixture(true, false); guest.state.signedIn = false;
  await guest.startup.start(); assert.deepEqual(guest.calls, ["privacy-check"]);
  assert.equal(guest.state.startup?.kind, "privacy");
  await guest.startup.handleKey("", { name: "f7" });
  assert.deepEqual(guest.calls, ["privacy-check", "update-check", "workspace"]);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity,cli.surface.semantic-parity
test("privacy install finishes before checking the update, and repeated keys cannot install twice", async () => {
  const f = fixture(true, true);
  let complete!: () => void;
  f.services.privacyInstall = () => new Promise<void>(resolve => { f.calls.push("privacy-install"); complete = resolve; });
  await f.startup.start();
  const installing = f.startup.handleKey("", { name: "f6" });
  await f.startup.handleKey("", { name: "f6" });
  await f.startup.handleKey("", { name: "f7" });
  assert.deepEqual(f.calls, ["privacy-check", "privacy-install"]);
  complete(); await installing;
  assert.equal(f.state.startup?.kind, "update");
  await f.startup.handleKey("", { name: "f6" });
  assert.deepEqual(f.calls, ["privacy-check", "privacy-install", "update-check", "update-install", "restart"]);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity,cli.surface.semantic-parity
test("failed installation keeps the fullscreen choice usable for retry or skip", async () => {
  for (const kind of ["privacy", "update"] as const) {
    const f = fixture(kind === "privacy", true);
    f.services[kind === "privacy" ? "privacyInstall" : "updateInstall"] = async () => { throw new Error("Installation failed"); };
    await f.startup.start(); await f.startup.handleKey("", { name: "f6" });
    assert.equal(f.state.startup?.kind, kind);
    assert.equal(f.state.startup?.busy, false);
    assert.equal(f.state.startup?.status, "Installation failed");
    assert.ok(!f.calls.includes("workspace"));
    await f.startup.handleKey("", { name: "f7" });
    if (kind === "privacy") await f.startup.handleKey("", { name: "f7" });
    assert.ok(f.calls.includes("workspace"));
  }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("closing during a slow update check cannot reopen the workspace", async () => {
  const f = fixture(false, true);
  let complete!: () => void;
  f.services.updateCheck = () => new Promise(resolve => { complete = () => resolve(offer()); });
  const pending = f.startup.start();
  await new Promise(resolve => setImmediate(resolve));
  f.close(); complete(); await pending;
  assert.ok(!f.calls.includes("workspace"));
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity,cli.surface.semantic-parity
test("fullscreen startup frames retain terminal geometry and visible choices on narrow screens", () => {
  for (const kind of ["privacy", "update", "checking"] as const) for (const width of [1, 24, 73, 120]) for (const height of [1, 12, 24]) {
    const state = createInitialTuiState(); state.sidebarOpen = true;
    state.startup = { kind, busy: false, selected: 1, status: null, update: kind === "update" ? offer() : null };
    const rows = stripAnsi(renderTuiFrame(state, width, height, { colorMode: "truecolor" })).split("\n");
    assert.equal(rows.length, height); assert.ok(rows.every(row => cells(row) === width));
    assert.doesNotMatch(rows.join("\n"), /DAILY INSPIRATION|Ask anything/);
  }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("update skip persists for exactly 24 hours and a failed check keeps startup usable", async () => {
  const directory = mkdtempSync(join(tmpdir(), "tui-update-reminder-"));
  const prior = { directory: process.env.OPENMATES_UPDATE_DIR, latest: process.env.OPENMATES_CLI_LATEST_VERSION };
  try {
    process.env.OPENMATES_UPDATE_DIR = directory; process.env.OPENMATES_CLI_LATEST_VERSION = "99.0.0-alpha.1";
    const now = 1_800_000_000_000;
    assert.equal((await checkTuiUpdate(now))?.latestVersion, "99.0.0-alpha.1");
    deferTuiUpdate(now);
    assert.deepEqual(JSON.parse(readFileSync(join(directory, "tui-update-reminder.json"), "utf8")), { nextPromptAt: now + 86_400_000 });
    assert.equal(await checkTuiUpdate(now + 86_399_999), null);
    assert.equal((await checkTuiUpdate(now + 86_400_000))?.latestVersion, "99.0.0-alpha.1");
    process.env.OPENMATES_CLI_LATEST_VERSION = "invalid-version";
    assert.equal(await checkTuiUpdate(now + 86_400_000), null);
  } finally {
    if (prior.directory === undefined) delete process.env.OPENMATES_UPDATE_DIR; else process.env.OPENMATES_UPDATE_DIR = prior.directory;
    if (prior.latest === undefined) delete process.env.OPENMATES_CLI_LATEST_VERSION; else process.env.OPENMATES_CLI_LATEST_VERSION = prior.latest;
    rmSync(directory, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("npm checks and both update paths refresh metadata for a newly published version", { skip: process.platform === "win32" }, async () => {
  // This POSIX executable simulates the stale npm metadata observed on the dev host.
  const directory = mkdtempSync(join(tmpdir(), "tui-fresh-npm-"));
  const keys = ["PATH", "OPENMATES_UPDATE_DIR", "OPENMATES_CLI_LATEST_VERSION", "npm_config_user_agent", "npm_config_prefer_online", "OPENMATES_TEST_UPDATE_LOG"];
  const previous = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  const marker = join(directory, "installs.txt");
  try {
    writeFileSync(join(directory, "npm"), "#!" + process.execPath + "\n" + [
      'const fs=require("node:fs");',
      'const args=process.argv.slice(2);',
      'if(args[0]==="view"){if(!args.includes("--prefer-online"))process.exit(31);console.log("99.0.0");}',
      'else if(args[0]==="install"){if(process.env.npm_config_prefer_online!=="true"){console.error("ETARGET: cached metadata lacks the new version");process.exit(32);}fs.appendFileSync(process.env.OPENMATES_TEST_UPDATE_LOG,"installed\\n");}',
      'else process.exit(33);',
    ].join("\n"), {mode: 0o755});
    process.env.PATH = directory + ":" + previous.PATH;
    process.env.OPENMATES_UPDATE_DIR = directory;
    process.env.OPENMATES_TEST_UPDATE_LOG = marker;
    process.env.npm_config_user_agent = "npm/test";
    process.env.npm_config_prefer_online = "false";
    delete process.env.OPENMATES_CLI_LATEST_VERSION;
    const offer = await checkTuiUpdate();
    assert.equal(offer?.latestVersion, "99.0.0");
    assert.ok(offer);
    await installTuiUpdate(offer);
    const plan = buildSelfUpdatePlan({channel: "dev", version: "99.0.0", "package-manager": "npm"});
    assert.equal(checkSelfUpdateStatus(buildSelfUpdatePlan({channel: "dev", "package-manager": "npm"})).latestVersion, "99.0.0");
    runSelfUpdate(plan);
    assert.equal(readFileSync(marker, "utf8"), "installed\ninstalled\n");
  } finally {
    for (const key of keys) if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key];
    rmSync(directory, {recursive: true, force: true});
  }
});
