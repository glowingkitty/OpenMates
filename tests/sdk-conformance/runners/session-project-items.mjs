/** Actual NAPI SessionClient, one shared synthetic encrypted Project links peer. */
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
const { SessionClient, SessionClientError } = await import("../../../frontend/packages/openmates-cli/dist/sdk-entry.js");
const ROOT = fileURLToPath(new URL("../../../", import.meta.url)), CAPABILITY = "session.project-items.v1";
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const reject = (operation, code = "invalid_argument") => assert.rejects(operation, error => error instanceof SessionClientError && error.code === code && !error.message.includes("synthetic-private-server-diagnostic"));
async function runVector(suite, vector, fixturePath) {
  const peer = spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON ?? "python3", ["tests/sdk-conformance/session_project_items_server.py", "--fixture", fixturePath, "--vector", vector.id, "--identity", "npm"], { cwd: ROOT, stdio: ["ignore", "pipe", "ignore"] });
  const lines = createInterface({ input: peer.stdout }); let client;
  try {
    const ready = await Promise.race([new Promise((resolve,reject) => {
      lines.once("line", line => { try { resolve(JSON.parse(line)); } catch { reject(new Error("fixture readiness")); } });
      peer.once("error", () => reject(new Error("fixture unavailable"))); peer.once("exit", () => reject(new Error("fixture exited")));
    }), new Promise((_,reject) => setTimeout(() => reject(new Error("fixture startup timeout")),10000).unref())]);
    assert.match(ready.endpoint, /^http:\/\/127\.0\.0\.1:\d+$/);
    const status = async () => { const r = await fetch(ready.endpoint + "/__test/status"); assert.equal(r.status,200); return r.json(); };
    client = new SessionClient({ apiUrl: ready.endpoint, appUrl: ready.endpoint, privacy: { enhanced: false }, allowPrivateOperations: false });
    await client.importSession({ api_url: ready.endpoint, session_id: suite.account.session_id, cookies: { auth_refresh_token: suite.account.cookie }, ws_token: null, master_key: suite.account.master_key, hashed_email:"synthetic-email-hash",user_email_salt:"synthetic-salt",email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null });
    await client.setTeam(suite.team.team_id);
    const before = await client.exportSession({includeSecrets:true}), mode = vector.mode;
    const filters = vector.team ? {teamId:suite.team.team_id} : {personal:true}, id = suite.project_id;
    const unlink = {itemType:vector.item_type ?? "chat",targetId:suite.target_id,confirmed:true};
    if (mode === "projection") assert.deepEqual(await client.projects.items(id,filters),suite.expected);
    else if (["unlink","noop"].includes(mode)) assert.deepEqual(await client.projects.unlinkItem(id,unlink,filters),{project_id:id,target_id:suite.target_id,deleted:mode!=="noop",deleted_count:mode==="noop"?0:1});
    else if (mode === "confirmation") {
      for (const bad of [false,"true",1,null]) await reject(()=>client.projects.unlinkItem(id,{...unlink,confirmed:bad},filters));
      for (const patch of [{itemType:"upload"},{unexpected:true},{targetId:""},{target_id:"duplicate-alias"}]) await reject(()=>client.projects.unlinkItem(id,{...unlink,...patch},filters));
    } else if (mode === "scope") {
      await reject(()=>client.projects.items(id,{}));
      await reject(()=>client.projects.unlinkItem(id,unlink,{personal:true,teamId:suite.team.team_id}));
      await reject(()=>client.projects.items(id,{personal:true,unexpected:true}));
    } else if (mode === "tamper") await reject(()=>client.projects.items(id,filters),"forbidden");
    else if (["permission","receipt"].includes(mode)) await reject(()=>client.projects.unlinkItem(id,unlink,filters),mode==="permission"?"forbidden":"protocol");
    else if (mode === "cancel") {
      const first=client.projects.items(id,filters), firstChecked=reject(()=>first,"cancelled");
      for(let i=0;i<500 && !(await status()).blocked;i++) await pause(10);
      assert.equal((await status()).blocked,true);
      const queued=client.projects.unlinkItem(id,unlink,filters), checked=reject(()=>queued,"cancelled");
      await pause(30); client.cancel(); await fetch(ready.endpoint+"/__test/release");
      await firstChecked;await checked;
      assert.deepEqual(await client.projects.items(id,filters),suite.expected);
    } else assert.fail("unknown fixture mode");
    const report=await status();assert.equal(report.failure,null);
    assert.deepEqual(report.targets,suite.expected.items.map(item=>item.target_id));
    assert.equal(report.writes,["unlink","noop","receipt"].includes(mode)?1:0);
    assert.equal(report.deleted_links,mode==="unlink"?1:0);
    if (["confirmation","scope"].includes(mode)) assert.equal(report.requests,0);
    else {
      const after=await client.exportSession({includeSecrets:true});assert.ok(after.revision>before.revision);
      assert.equal(after.session.cookies.auth_refresh_token,report.cookie);
      assert.equal(report.requests,(vector.team?2:1)+(["unlink","noop","receipt","cancel"].includes(mode)?1:0),"no retry or underlying-object deletion");
    }
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
