import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadProgressiveCachedTuiWorkspace, readCachedTuiWorkspace, writeCachedTuiWorkspace } from "../src/tuiCachedWorkspaces.ts";
import { mergePartialTuiTasks } from "../src/tuiTaskList.ts";
import { clearSession, saveSession, type OpenMatesSession } from "../src/storage.ts";
import type { DecryptedUserTask } from "../src/tasksCli.ts";

const stateDir = mkdtempSync(join(tmpdir(), "openmates-progressive-tasks-"));
const priorStateDir = process.env.OPENMATES_STATE_DIR;
process.env.OPENMATES_STATE_DIR = stateDir;
const original: OpenMatesSession = {
  apiUrl: "https://api.example.test", sessionId: "tasks-session", wsToken: null, cookies: {},
  masterKeyExportedB64: Buffer.alloc(32, 21).toString("base64"), hashedEmail: "tasks-owner",
  userEmailSalt: "salt", createdAt: Date.now(), authorizerDeviceName: null,
  autoLogoutMinutes: null, activeTeamId: null,
};
let live = { ...original };
const client = { apiUrl: original.apiUrl, hasSession: () => true, getSession: () => live };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
before(() => saveSession(original, { replace: true }));
after(() => {
  try { clearSession(); } finally {
    rmSync(stateDir, { recursive: true, force: true });
    if (priorStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = priorStateDir;
  }
});

describe("progressive encrypted TUI task cache", () => {
  // contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity,terminal-ui.offline.cache-first
  it("publishes and saves the first batch while a later page is pending", async () => {
    const next = deferred<void>();
    const firstShown = deferred<void>();
    const shown: string[][] = [];
    const result = loadProgressiveCachedTuiWorkspace(client, "tasks:progress-first", async progress => {
      await progress(["first"], false);
      await next.promise;
      await progress(["first", "second"], true);
      return ["first", "second"];
    }, (tasks, source) => { if (source === "sync") { shown.push(tasks); firstShown.resolve(); } });
    await firstShown.promise;
    assert.deepEqual(shown, [["first"]]);
    assert.deepEqual(await readCachedTuiWorkspace<string[]>(client, "tasks:progress-first"), ["first"]);
    next.resolve();
    assert.deepEqual(await result, ["first", "second"]);
    assert.deepEqual(shown, [["first"], ["first", "second"]]);
  });

  // contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first,tasks.surface.semantic-parity
  it("keeps warm rows while newer partial pages arrive, then replaces them at completion", async () => {
    const key = "tasks:progress-warm";
    await writeCachedTuiWorkspace(client, key, ["saved-old", "saved-current"]);
    const gate = deferred<void>();
    const partialShown = deferred<void>();
    const fullShown = deferred<void>();
    const shown: string[][] = [];
    const result = await loadProgressiveCachedTuiWorkspace(client, key, async progress => {
      await progress(["fresh-current"], false);
      await gate.promise;
      await progress(["fresh-current", "fresh-next"], true);
      return ["fresh-current", "fresh-next"];
    }, (tasks, source, complete) => { shown.push(tasks); if (source === "sync") partialShown.resolve(); if (complete) fullShown.resolve(); }, undefined,
    (previous, page) => [...page, ...(previous ?? []).filter(value => !page.includes(value))]);
    assert.deepEqual(result, ["saved-old", "saved-current"]);
    await partialShown.promise;
    assert.deepEqual(shown[0], ["saved-old", "saved-current"]);
    assert.deepEqual(await readCachedTuiWorkspace<string[]>(client, key), ["fresh-current", "saved-old", "saved-current"]);
    gate.resolve();
    await fullShown.promise;
    assert.deepEqual(await readCachedTuiWorkspace<string[]>(client, key), ["fresh-current", "fresh-next"]);
  });

  // contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first
  it("retains a usable partial batch and reports a later-page failure", async () => {
    const errors: boolean[] = [];
    const shown: string[][] = [];
    const result = await loadProgressiveCachedTuiWorkspace(client, "tasks:progress-error", async progress => {
      await progress(["usable"], false);
      throw new Error("page two unavailable");
    }, tasks => { shown.push(tasks); }, (_error, hasUsable) => { errors.push(hasUsable); });
    assert.equal(result, null);
    assert.deepEqual(shown, [["usable"]]);
    assert.deepEqual(errors, [true]);
    assert.deepEqual(await readCachedTuiWorkspace<string[]>(client, "tasks:progress-error"), ["usable"]);
  });

  // contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first
  it("opens a saved list immediately when its refresh is offline", async () => {
    const key = "tasks:progress-offline";
    await writeCachedTuiWorkspace(client, key, ["saved"]);
    const failures: boolean[] = [];
    const shown: Array<[string[], string]> = [];
    assert.deepEqual(await loadProgressiveCachedTuiWorkspace(client, key,
      async () => { throw new Error("offline"); },
      (tasks, source) => { shown.push([tasks, source]); },
      (_error, hasUsable) => { failures.push(hasUsable); }), ["saved"]);
    await new Promise<void>(resolve => setImmediate(resolve));
    assert.deepEqual(shown, [[["saved"], "cache"]]);
    assert.deepEqual(failures, [true]);
    assert.deepEqual(await readCachedTuiWorkspace<string[]>(client, key), ["saved"]);
  });

  // contract-test: infrastructure
  it("rejects a delayed page after an owner switch", async () => {
    const gate = deferred<void>();
    const started = deferred<void>();
    const shown: string[][] = [];
    const pending = loadProgressiveCachedTuiWorkspace(client, "tasks:progress-owner", async progress => {
      started.resolve();
      await gate.promise;
      await progress(["private-old-team"], true);
      return ["private-old-team"];
    }, tasks => { shown.push(tasks); });
    await started.promise;
    live = { ...original, activeTeamId: "different-team" };
    saveSession(live, { replace: true });
    gate.resolve();
    assert.equal(await pending, null);
    assert.deepEqual(shown, []);
    assert.equal(await readCachedTuiWorkspace<string[]>(client, "tasks:progress-owner"), null);
    live = { ...original }; saveSession(live, { replace: true });
  });

  // contract-test: infrastructure
  it("does not overwrite an authoritative mutation with an in-flight page", async () => {
    const gate = deferred<void>();
    const started = deferred<void>();
    const pending = loadProgressiveCachedTuiWorkspace(client, "tasks:progress-mutation", async progress => {
      started.resolve(); await gate.promise;
      await progress(["stale"], true);
      return ["stale"];
    }, () => {});
    await started.promise;
    await writeCachedTuiWorkspace(client, "tasks:progress-mutation", ["mutated"]);
    gate.resolve();
    assert.equal(await pending, null);
    assert.deepEqual(await readCachedTuiWorkspace<string[]>(client, "tasks:progress-mutation"), ["mutated"]);
  });

  // contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
  it("merges fresh task identities without losing older warm rows", () => {
    const task = (taskId: string, title: string) => ({ taskId, title }) as DecryptedUserTask;
    assert.deepEqual(mergePartialTuiTasks([task("old", "old"), task("same", "stale")], [task("same", "fresh")])
      .map(item => [item.taskId, item.title]), [["same", "fresh"], ["old", "old"]]);
  });
});
