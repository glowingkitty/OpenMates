/** Actual NAPI SessionClient, one shared synthetic cookie CRUD peer. */
import assert from "node:assert/strict";
import {savedStreamVector} from "./support/saved-stream.mjs";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
const { SessionClient, SessionClientError } = await import("../../../frontend/packages/openmates-cli/dist/sdk-entry.js");
const ROOT = fileURLToPath(new URL("../../../", import.meta.url)), CAPABILITY = "session.work-crud.v1";
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const camel = value => {
  if (Array.isArray(value)) return value.map(camel);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k,v]) => [k.replace(/_([a-z])/g, (_,c) => c.toUpperCase()),camel(v)]));
  return value;
};
const reject = (operation, code = "invalid_argument") => assert.rejects(operation, error => error instanceof SessionClientError && error.code === code && !error.message.includes("synthetic-private-server-diagnostic"));
async function runVector(suite, vector, fixturePath) {
  if (vector.mode.startsWith("saved_")) return savedStreamVector(suite,vector,fixturePath,SessionClient,SessionClientError);
  const peer = spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON ?? "python3", ["tests/sdk-conformance/session_work_server.py", "--fixture", fixturePath, "--vector", vector.id, "--identity", "npm"], { cwd: ROOT, stdio: ["ignore", "pipe", "ignore"] });
  const lines = createInterface({ input: peer.stdout }); let client;
  try {
    const ready = await Promise.race([new Promise((resolve,reject) => {
      lines.once("line", line => { try { resolve(JSON.parse(line)); } catch { reject(new Error("fixture readiness")); } });
      peer.once("error", () => reject(new Error("fixture unavailable"))); peer.once("exit", () => reject(new Error("fixture exited")));
    }), new Promise((_,reject) => setTimeout(() => reject(new Error("fixture startup timeout")),10000).unref())]);
    assert.match(ready.endpoint, /^http:\/\/127\.0\.0\.1:\d+$/);
    const status = async () => { const r = await fetch(ready.endpoint + "/__test/status"); assert.equal(r.status,200); return r.json(); };
    client = new SessionClient({ apiUrl: ready.endpoint, privacy: { enhanced: false }, allowPrivateOperations: false });
    await client.importSession({ api_url: ready.endpoint, session_id: suite.account.session_id, cookies: { auth_refresh_token: suite.account.cookie }, ws_token: null, master_key: suite.account.master_key, hashed_email:"synthetic-email-hash",user_email_salt:"synthetic-salt",email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null });
    await client.setTeam(suite.team.team_id);
    const before = await client.exportSession({includeSecrets:true}), mode = vector.mode;
    if (mode === "crud") {
      const family = vector.family, api = client[family], filters = vector.team ? {teamId:suite.team.team_id} : {personal:true};
      const result = await api.create(camel(suite.input[family]),filters);
      const key = family === "tasks" ? "task_id" : "project_id", name = family === "tasks" ? "title" : "name", id = result[key];
      assert.equal(result[name],suite.input[family][name]);
      const rows = await api.list(filters); assert.equal(rows.length,1); assert.equal(rows[0][key],id);
      assert.equal((await api.show(id,filters))[name],result[name]);
      const patch = { [name]:"Synthetic updated private text", ...(family === "tasks" ? {dueAt:null,status:"in_progress"} : {archived:true}) };
      const updated = await api.update(id,patch,filters); assert.equal(updated[name],patch[name]);
      if (family === "tasks") { assert.equal(updated.due_at,null); assert.equal(updated.status,"in_progress"); } else assert.equal(updated.archived,true);
      assert.equal((await api.delete(id,{confirmed:true},filters)).deleted,true);
      assert.deepEqual(await api.list(filters),[]);
    } else if (mode === "unknown") {
      await reject(() => client.tasks.create({title:"synthetic",model:"forbidden"},{personal:true}));
      await reject(() => client.projects.create({name:"synthetic",provider:"forbidden"},{personal:true}));
      await reject(() => client.tasks.create({title:"synthetic",dueAt:1,due_at:2},{personal:true}));
    } else if (mode === "confirmation") {
      for (const api of [client.tasks,client.projects]) await reject(() => api.delete("11111111-1111-4111-8111-111111111111",{confirmed:false},{personal:true}));
    } else if (mode === "scope") {
      await reject(() => client.tasks.list({}));
      await reject(() => client.projects.list({personal:true,teamId:suite.team.team_id}));
    } else if (mode === "policy") {
      await reject(() => client.tasks.create({title:"Synthetic private AI Task",assign:"openmates"},{personal:true}),"forbidden");
      await reject(() => client.projects.create({name:"Synthetic no write policy"},{personal:true}));
    } else if (mode === "close") {
      await client.close();
      await reject(() => client.tasks.list({personal:true}),"cancelled");
      await reject(() => client.projects.list({personal:true}),"cancelled");
    } else if (mode === "cancel") {
      assert.equal(vector.expected_first_error,"cancelled","canonical in-flight cancellation oracle");
      const first = client.tasks.list({personal:true});
      const firstChecked = reject(() => first,vector.expected_first_error);
      // Observe assertion failures immediately; awaiting the original check
      // below still propagates them after the canonical HTTP response settles.
      firstChecked.catch(() => {});
      for (let i=0;i<500 && !(await status()).blocked;i++) await pause(10);
      assert.equal((await status()).blocked,true);
      const queued = client.projects.list({personal:true}); const checked = reject(() => queued,"cancelled");
      checked.catch(() => {});
      await pause(30); client.cancel(); await fetch(ready.endpoint + "/__test/release");
      await firstChecked; await checked;
      assert.deepEqual(await client.projects.list({personal:true}),[]);
    } else assert.fail("unknown fixture mode");
    const report = await status(); assert.equal(report.failure,null);
    if (["crud","cancel"].includes(mode)) {
      const after = await client.exportSession({includeSecrets:true}); assert.ok(after.revision > before.revision);
      assert.equal(after.session.cookies.auth_refresh_token,report.cookie);
    }
    if (mode === "crud") {
      assert.equal(report.writes,3);
      for (const check of ["encrypted-private-fields","scope-bound-wrapper","fresh-object-key","versioned-encrypted-update","canonical-confirmed-delete","cookie-only-identity-and-rotation"]) assert.ok(report.checks.includes(check));
    } else if (mode === "cancel") { assert.equal(report.requests,2); assert.equal(report.writes,0); }
    else { assert.equal(report.requests,0); assert.equal(report.writes,0); }
    return {id:vector.id,status:"passed"};
  } finally {
    if (client) await client.close();
    lines.close(); if (peer.pid && peer.exitCode === null && peer.signalCode === null) { const stopped = new Promise(resolve => peer.once("exit",resolve)); peer.kill("SIGTERM"); await stopped; }
  }
}
const args = process.argv.slice(2), option = name => args[args.indexOf(name)+1];
assert.equal(option("--capability"),CAPABILITY);
const fixturePath = option("--fixture"), raw = readFileSync(fixturePath), suite = JSON.parse(raw).capabilities[CAPABILITY];
const results = []; for (const vector of suite.vectors) results.push(await runVector(suite,vector,fixturePath));
console.log(JSON.stringify({capability:CAPABILITY,language:"npm",status:"passed",fixtureSha256:createHash("sha256").update(raw).digest("hex"),results}));
