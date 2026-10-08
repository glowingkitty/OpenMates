import assert from "node:assert/strict";
import { before, after, describe, it } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  invalidateCachedTuiWorkspace,
  loadCachedTuiWorkspace,
  writeCachedTuiWorkspace,
  captureTuiWorkspaceOwner,
  readCachedTuiWorkspace,
} from "../src/tuiCachedWorkspaces.ts";
import { clearSession, saveSession, type OpenMatesSession } from "../src/storage.ts";

const stateDir = mkdtempSync(join(tmpdir(), "openmates-tui-cached-workspaces-"));
const priorStateDir = process.env.OPENMATES_STATE_DIR;
process.env.OPENMATES_STATE_DIR = stateDir;

const original: OpenMatesSession = {
  apiUrl: "https://api.example.test", sessionId: "session-one", wsToken: null, cookies: {},
  masterKeyExportedB64: Buffer.alloc(32, 11).toString("base64"), hashedEmail: "account-one",
  userEmailSalt: "salt", createdAt: Date.now(), authorizerDeviceName: null,
  autoLogoutMinutes: null, activeTeamId: null,
};
let live = { ...original };
const client = {
  apiUrl: original.apiUrl,
  hasSession: () => true,
  getSession: () => live,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const nextTick = () => new Promise<void>(resolve => setImmediate(resolve));

before(() => saveSession(original, { replace: true }));
after(() => {
  try { clearSession(); } finally {
    rmSync(stateDir, { recursive: true, force: true });
    if (priorStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = priorStateDir;
  }
});

describe("cached TUI workspace loading", () => {
  // contract-test: infrastructure
  it('rejects a delayed mutation write captured in a different team',async()=>{
    live={...original};saveSession(live,{replace:true});
    const owner=captureTuiWorkspaceOwner(client);
    live={...original,activeTeamId:'different-team'};saveSession(live,{replace:true});
    assert.equal(await writeCachedTuiWorkspace(client,'projects:old-mutation',['private old team'],owner),false);
    assert.equal(await readCachedTuiWorkspace(client,'projects:old-mutation'),null);
    live={...original};saveSession(live,{replace:true});
  });
  // contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,workflows.surface.semantic-parity,tasks.surface.semantic-parity,terminal-ui.offline.cache-first
  it("publishes an encrypted snapshot before the refresh resolves", async () => {
    const key = "projects:adapter-warm";
    assert.equal(await writeCachedTuiWorkspace(client, key, ["saved"]), true);
    const refresh = deferred<string[]>();
    const synced = deferred<void>();
    const shown: Array<[string[], string]> = [];
    const result = await loadCachedTuiWorkspace(client, key, () => refresh.promise,
      (value, source) => { shown.push([value, source]); if (source === "sync") synced.resolve(); });
    assert.deepEqual(result, ["saved"]);
    assert.deepEqual(shown, [[ ["saved"], "cache" ]]);
    refresh.resolve(["fresh"]);
    await synced.promise;
    assert.deepEqual(shown, [[ ["saved"], "cache" ], [ ["fresh"], "sync" ]]);
  });

  // contract-test: infrastructure
  it("retains a warm snapshot on refresh failure and reports the failure", async () => {
    const key = "workflows:adapter-error";
    await writeCachedTuiWorkspace(client, key, ["saved"]);
    const refresh = deferred<string[]>();
    const shown: string[] = [];
    const errors: boolean[] = [];
    assert.deepEqual(await loadCachedTuiWorkspace(client, key, () => refresh.promise,
      (value) => { shown.push(...value); }, (_error, hasCached) => { errors.push(hasCached); }), ["saved"]);
    refresh.reject(new Error("offline"));
    await nextTick();
    assert.deepEqual(shown, ["saved"]);
    assert.deepEqual(errors, [true]);
  });

  // contract-test: infrastructure
  it("lets the caller gate a changed route while sharing one network fetch", {timeout:2000}, async () => {
    const key = "tasks:adapter-route";
    const refresh = deferred<string[]>();
    const started = deferred<void>();
    let fetchCount = 0;
    let route = "tasks";
    const shown: string[] = [];
    const fetch = () => { fetchCount++; started.resolve(); return refresh.promise; };
    const publish = (value: string[]) => { if (route === "tasks") shown.push(...value); };
    const first = loadCachedTuiWorkspace(client, key, fetch, publish);
    const second = loadCachedTuiWorkspace(client, key, fetch, publish);
    await started.promise;
    assert.equal(fetchCount, 1);
    route = "projects";
    refresh.resolve(["stale-route"]);
    assert.deepEqual(await Promise.all([first, second]), [["stale-route"], ["stale-route"]]);
    assert.equal(fetchCount, 1);
    assert.deepEqual(shown, []);
  });

  // contract-test: infrastructure
  it("fences a changed owner/team before publishing or persisting", async () => {
    const key = "projects:adapter-identity";
    const refresh = deferred<string[]>();
    const shown: string[] = [];
    const pending = loadCachedTuiWorkspace(client, key, () => refresh.promise,
      value => { shown.push(...value); });
    await nextTick();
    live = { ...live, activeTeamId: "team-two" };
    saveSession(live);
    refresh.resolve(["old-team"]);
    assert.equal(await pending, null);
    assert.deepEqual(shown, []);
    live = { ...original };
    saveSession(live, { replace: true });
  });

  // contract-test: infrastructure
  it("invalidation fences an in-flight response and an authoritative write survives", async () => {
    const key = "tasks:adapter-mutation";
    const refresh = deferred<string[]>();
    const shown: string[] = [];
    const pending = loadCachedTuiWorkspace(client, key, () => refresh.promise,
      value => { shown.push(...value); });
    await nextTick();
    assert.equal(await invalidateCachedTuiWorkspace(client, key), true);
    assert.equal(await writeCachedTuiWorkspace(client, key, ["mutation"]), true);
    refresh.resolve(["stale-server"]);
    assert.equal(await pending, null);
    assert.deepEqual(shown, []);
    const fetched = deferred<string[]>();
    const result = await loadCachedTuiWorkspace(client, key, () => fetched.promise, () => {});
    assert.deepEqual(result, ["mutation"]);
    fetched.resolve(["later"]);
    await nextTick();
  });

  // contract-test: infrastructure
  it("does not read a personal snapshot for clients without session APIs", async () => {
    const key = "projects:adapter-warm";
    const mock = { apiUrl: original.apiUrl };
    const sources: string[] = [];
    assert.deepEqual(await loadCachedTuiWorkspace(mock, key, async () => ["mock"],
      (_value, source) => { sources.push(source); }), ["mock"]);
    assert.deepEqual(sources, ["sync"]);
    assert.equal(await writeCachedTuiWorkspace(mock, key, ["mock"]), false);
  });

  // contract-test: infrastructure
  it("keeps an API override away from the saved account snapshot", async () => {
    const key = "projects:adapter-warm";
    const override = { ...client, apiUrl: "https://other.example.test" };
    const sources: string[] = [];
    assert.deepEqual(await loadCachedTuiWorkspace(override, key, async () => ["other-api"],
      (_value, source) => { sources.push(source); }), ["other-api"]);
    assert.deepEqual(sources, ["sync"]);
    assert.equal(await writeCachedTuiWorkspace(override, key, ["other-api"]), false);
  });
});
