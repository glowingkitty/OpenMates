import assert from "node:assert/strict";
import { describe, it, before, after } from "node:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import lockfile from "proper-lockfile";

import { createTuiWorkspaceCache, TUI_WORKSPACE_CACHE_FILE } from "../src/tuiWorkspaceCache.ts";
import { clearSession, loadSession, purgeLocalPrivateData, saveSession, type OpenMatesSession } from "../src/storage.ts";

const stateDir = mkdtempSync(join(tmpdir(), "openmates-tui-workspace-cache-"));
const priorStateDir = process.env.OPENMATES_STATE_DIR;
process.env.OPENMATES_STATE_DIR = stateDir;

const session: OpenMatesSession = {
  apiUrl: "https://api.example.test",
  sessionId: "session-one",
  wsToken: null,
  cookies: {},
  masterKeyExportedB64: Buffer.alloc(32, 7).toString("base64"),
  hashedEmail: "account-one",
  userEmailSalt: "salt",
  createdAt: Date.now(),
  authorizerDeviceName: null,
  autoLogoutMinutes: null,
  activeTeamId: null,
};

before(() => saveSession({ ...session }, { replace: true }));
after(() => {
  try { clearSession(); } finally {
    rmSync(stateDir, { recursive: true, force: true });
    if (priorStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = priorStateDir;
  }
});

describe("encrypted TUI workspace snapshots", () => {
  // contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,workflows.surface.semantic-parity,tasks.surface.semantic-parity
  it("reopens Projects, Workflows, and Tasks offline, preserving binary project keys", async () => {
    const cache = createTuiWorkspaceCache(loadSession()!);
    const projectKey = new Uint8Array([0, 1, 127, 255]);
    assert.equal(await cache.set("projects:list", [{ id: "project-1", name: "secret-project", key: projectKey }]), true);
    assert.equal(await cache.set("workflows:graph:one", { nodes: [{ name: "secret-workflow" }], runs: ["run-1"] }), true);
    assert.equal(await cache.set("tasks:project:one", [{ title: "secret-task" }]), true);

    const reopened = createTuiWorkspaceCache(loadSession()!);
    assert.deepEqual(await reopened.get("projects:list"), [{ id: "project-1", name: "secret-project", key: projectKey }]);
    assert.deepEqual(await reopened.get("workflows:graph:one"), { nodes: [{ name: "secret-workflow" }], runs: ["run-1"] });
    assert.deepEqual(await reopened.get("tasks:project:one"), [{ title: "secret-task" }]);

    const file = join(stateDir, TUI_WORKSPACE_CACHE_FILE);
    const disk = readFileSync(file, "utf8");
    for (const secret of ["secret-project", "secret-workflow", "secret-task", "projects:list"]) {
      assert.equal(disk.includes(secret), false);
    }
    assert.equal(statSync(file).mode & 0o777, 0o600);
    assert.equal(statSync(stateDir).mode & 0o777, 0o700);
  });

  // contract-test: infrastructure
  it("keeps a same-account snapshot across credential and login renewal", async () => {
    const original = loadSession()!;
    const cache = createTuiWorkspaceCache(original);
    assert.equal(await cache.set("projects:renewal", { name: "saved-project" }), true);

    const refreshed = { ...original, sessionId: "renewed-auth-session", cookies: { auth_refresh_token: "rotated" } };
    saveSession(refreshed, { replace: true });
    assert.equal(cache.isCurrent(), true);
    assert.deepEqual(await cache.get("projects:renewal"), { name: "saved-project" });

    const renewedLogin = { ...refreshed, sessionId: "new-login-session", createdAt: original.createdAt + 1_000 };
    saveSession(renewedLogin, { replace: true });
    assert.equal(cache.isCurrent(), false);
    assert.equal(await cache.set("projects:late", { name: "stale" }), false);
    assert.deepEqual(await createTuiWorkspaceCache(loadSession()!).get("projects:renewal"), { name: "saved-project" });
    saveSession({ ...session }, { replace: true });
  });

  // contract-test: infrastructure
  it("fences account, API, and team changes and purges on logout", async () => {
    const original = createTuiWorkspaceCache(loadSession()!);
    assert.equal(await original.set("tasks:list", ["account-one"]), true);
    for (const changed of [
      { activeTeamId: "team-two" },
      { apiUrl: "https://other.example.test" },
      { hashedEmail: "account-two", sessionId: "session-two" },
    ]) {
      const next = { ...session, ...changed };
      saveSession(next, { replace: true });
      assert.equal(original.isCurrent(), false);
      assert.equal(await original.get("tasks:list"), null);
      assert.equal(await original.set("tasks:list", ["late"]), false);
      assert.equal(await createTuiWorkspaceCache(loadSession()!).get("tasks:list"), null);
    }
    purgeLocalPrivateData();
    assert.equal(existsSync(join(stateDir, TUI_WORKSPACE_CACHE_FILE)), false);
    saveSession({ ...session }, { replace: true });
  });

  // contract-test: infrastructure
  it("rejects a delayed write after a live team switch", async () => {
    let live = loadSession()!;
    const cache = createTuiWorkspaceCache(live, () => live);
    const file = join(stateDir, TUI_WORKSPACE_CACHE_FILE);
    const release = await lockfile.lock(`${file}.write`, { realpath: false });
    try {
      const pending = cache.set("projects:detail", { title: "late-secret" });
      live = { ...live, activeTeamId: "team-switched" };
      saveSession(live);
      await release();
      assert.equal(await pending, false);
      assert.equal(existsSync(file) && readFileSync(file, "utf8").includes("late-secret"), false);
    } finally {
      // The lock may have been released above.
      await release().catch(() => {});
      saveSession({ ...session }, { replace: true });
    }
  });

  // contract-test: infrastructure
  it("treats corruption as a miss, recovers on write, and enforces entry bounds", async () => {
    const cache = createTuiWorkspaceCache(loadSession()!);
    const file = join(stateDir, TUI_WORKSPACE_CACHE_FILE);
    writeFileSync(file, "{broken", { mode: 0o600 });
    assert.equal(await cache.get("projects:list"), null);
    assert.equal(await cache.set("projects:list", ["restored"]), true);
    assert.deepEqual(await cache.get("projects:list"), ["restored"]);
    assert.equal(await cache.set("projects:oversize", "x".repeat(4 * 1024 * 1024)), false);
    assert.equal(await cache.get("projects:oversize"), null);
    assert.equal(await cache.invalidate("projects:list"), true);
    assert.equal(await cache.get("projects:list"), null);
  });
});
