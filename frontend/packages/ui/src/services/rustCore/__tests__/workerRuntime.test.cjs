// Focused coverage for the Rust core Worker dispatcher after the closure -> explicit
// state split (workerRuntime*.ts). Engineering test: lifecycle of admission/dispose.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { webcrypto } = require("node:crypto");
const ts = require("typescript");
const source = path.join(__dirname, "..");
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "openmates-worker-runtime-"));
for (const file of fs.readdirSync(source).filter((name) => name.endsWith(".ts") && !name.endsWith(".d.ts") && name !== "worker.entry.ts")) {
  fs.writeFileSync(path.join(directory, file.replace(/\.ts$/, ".js")), ts.transpileModule(fs.readFileSync(path.join(source, file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText);
}
process.on("exit", () => fs.rmSync(directory, { recursive: true, force: true }));
const protocol = require(path.join(directory, "protocol.js"));
const { installBrowserCoreWorker } = require(path.join(directory, "workerRuntime.js"));
const profile = { principal: "12345678-1234-1234-1234-123456789abc", encryptedEmail: Buffer.alloc(40, 1).toString("base64"), userEmailSalt: "fixture-salt" };
const status = { handle: "opaque-handle", principal: profile.principal, generation: 1, persistence: "memory_only" };
class Endpoint extends EventTarget {
  sent = [];
  postMessage(data) { this.sent.push(data); }
  receive(data) { this.dispatchEvent(new MessageEvent("message", { data })); }
}
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function key() { return webcrypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]); }

test("worker runtime modules stay below the 800-line source limit", () => {
  for (const name of ["workerRuntime", "workerRuntimeState", "workerRuntimeTypes", "workerDispatch", "workerOwnedCacheRead"]) {
    const lines = fs.readFileSync(path.join(source, name + ".ts"), "utf8").split("\n").length;
    assert.ok(lines < 800, `${name}.ts has ${lines} lines`);
  }
});

test("dispatcher awaits core admission under lock, emits status only, and forwards no native session", async () => {
  globalThis.DedicatedWorkerGlobalScope = class { static [Symbol.hasInstance](value) { return value === globalThis; } };
  try {
    const endpoint = new Endpoint(); let bytes; let lockHeld = false; let invalidated = 0;
    const rustStatus = () => ({ ...status, persisted: false, free() {} });
    const client = { admitted_status: rustStatus, status(handle, generation) { assert.equal(handle, status.handle); assert.equal(generation, 1); return rustStatus(); }, invalidate() { invalidated++; }, free() {} };
    const binding = {
      PreparedBrowserProfile: { from_bytes(principal, raw) { assert.equal(principal, profile.principal); bytes = raw; return { free() {} }; } },
      BrowserCoreClient: { async restore(api, app, session) { assert.equal(lockHeld, true); assert.equal(bytes.every((byte) => byte === 0), true); assert.deepEqual([api, app, session], ["https://api.example", "https://app.example", "fixture-session"]); return client; } },
    };
    const locks = { async request(name, options, callback) { lockHeld = true; try { return await callback(); } finally { lockHeld = false; } } };
    const dispose = installBrowserCoreWorker(endpoint, binding, { apiUrl: "https://api.example", appOrigin: "https://app.example", sessionId: "fixture-session" }, locks);
    endpoint.receive({ version: 1, id: 1, operation: "restore", key: await key(), profile, persistence: "memory_only" });
    for (let i = 0; i < 20 && endpoint.sent.length === 0; i++) await tick();
    assert.deepEqual(endpoint.sent, [{ version: 1, id: 1, ok: true, status }]);
    assert.equal(protocol.validResponse(endpoint.sent[0]), true);
    dispose(); assert.equal(invalidated, 1);
  } finally { delete globalThis.DedicatedWorkerGlobalScope; }
});

test("disposing during pending admission discards the returned client and emits no handle", async () => {
  globalThis.DedicatedWorkerGlobalScope = class { static [Symbol.hasInstance](value) { return value === globalThis; } };
  try {
    const endpoint = new Endpoint(); let release; let invalidated = 0; let freed = 0;
    const binding = {
      PreparedBrowserProfile: { from_bytes() { return { free() {} }; } },
      BrowserCoreClient: { restore() { return new Promise((resolve) => { release = resolve; }); } },
    };
    const locks = { async request(name, options, callback) { return callback(); } };
    const dispose = installBrowserCoreWorker(endpoint, binding, { apiUrl: "https://api.example", appOrigin: "https://app.example", sessionId: "fixture" }, locks);
    endpoint.receive({ version: 1, id: 1, operation: "restore", key: await key(), profile, persistence: "memory_only" });
    for (let i = 0; i < 20 && !release; i++) await tick();
    assert.equal(typeof release, "function"); dispose();
    release({ invalidate() { invalidated++; }, free() { freed++; }, admitted_status() { assert.fail("disposed status"); } });
    await tick(); assert.equal(invalidated, 1); assert.equal(freed, 1); assert.deepEqual(endpoint.sent, []);
  } finally { delete globalThis.DedicatedWorkerGlobalScope; }
});

test("failed core admission returns a finite error without private exception contents", async () => {
  globalThis.DedicatedWorkerGlobalScope = class { static [Symbol.hasInstance](value) { return value === globalThis; } };
  try {
    const endpoint = new Endpoint();
    const binding = {
      PreparedBrowserProfile: { from_bytes() { return { free() {} }; } },
      BrowserCoreClient: { async restore() { throw new Error("private-cookie-key-owner"); } },
    };
    const locks = { async request(name, options, callback) { return callback(); } };
    const dispose = installBrowserCoreWorker(endpoint, binding, { apiUrl: "https://api.example", appOrigin: "https://app.example", sessionId: "fixture" }, locks);
    endpoint.receive({ version: 1, id: 1, operation: "restore", key: await key(), profile, persistence: "persisted" });
    for (let i = 0; i < 20 && endpoint.sent.length === 0; i++) await tick();
    assert.deepEqual(endpoint.sent, [{ version: 1, id: 1, ok: false, error: "reauthentication_required" }]); dispose();
  } finally { delete globalThis.DedicatedWorkerGlobalScope; }
});
