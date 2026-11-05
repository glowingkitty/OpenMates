/** Actual NAPI Plans/Workflows with the shared synthetic protocol peer. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
const {SessionClient,SessionClientError}=await import("../../../frontend/packages/openmates-cli/dist/sdk-entry.js");
const ROOT=fileURLToPath(new URL("../../../",import.meta.url)),CAPABILITY="session.plans-workflows.v1";
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const camel=value=>Array.isArray(value)?value.map(camel):value&&typeof value==="object"?Object.fromEntries(Object.entries(value).map(([k,v])=>[k.replace(/_([a-z])/g,(_,c)=>c.toUpperCase()),camel(v)])):value;
const rejected=(operation,code="invalid_argument")=>assert.rejects(operation,e=>e instanceof SessionClientError&&e.code===code&&!e.message.includes("synthetic-private-server-diagnostic"));
async function runVector(suite,vector,fixturePath){
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??"python3",["tests/sdk-conformance/session_plans_workflows_server.py","--fixture",fixturePath,"--vector",vector.id,"--identity","npm"],{cwd:ROOT,stdio:["ignore","pipe","ignore"]});
 const lines=createInterface({input:peer.stdout});let client;
 try{
  const ready=await Promise.race([new Promise((resolve,reject)=>{lines.once("line",line=>{try{resolve(JSON.parse(line));}catch{reject(new Error("readiness"));}});peer.once("error",()=>reject(new Error("peer unavailable")));peer.once("exit",()=>reject(new Error("peer exited")));}),new Promise((_,reject)=>setTimeout(()=>reject(new Error("startup timeout")),10000).unref())]);
  assert.match(ready.endpoint,/^http:\/\/127\.0\.0\.1:\d+$/);
  const status=async()=>{const r=await fetch(ready.endpoint+"/__test/status");assert.equal(r.status,200);return r.json();};
  client=new SessionClient({apiUrl:ready.endpoint,privacy:{enhanced:false},allowPrivateOperations:vector.allow_private});
  const a=suite.account;
  await client.importSession({api_url:ready.endpoint,session_id:a.session_id,cookies:{auth_refresh_token:a.cookie},ws_token:null,master_key:a.master_key,hashed_email:"synthetic-email-hash",user_email_salt:"synthetic-salt",email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null});
  await client.setTeam(suite.team.team_id);
  const before=await client.exportSession({includeSecrets:true}),mode=vector.mode,filters={personal:true},flow=suite.workflow_id,run=suite.run_id;
  if(mode==="crud"){
   const plans=vector.family==="plans",api=plans?client.plans:client.workflows,scope=vector.team?{teamId:suite.team.team_id}:filters,input=suite.input[plans?"plan":"workflow"];
   const created=await api.create(camel(input),scope),idField=plans?"plan_id":"id",id=created[idField];assert.equal(created.title,input.title);
   if(plans){assert.equal(created.goal,input.goal);assert.deepEqual(created.user_flows,input.user_flows);}else{assert.equal(created.slug,input.slug);assert.ok(!("encrypted_slug"in created));}
   const rows=await api.list(scope);assert.equal(rows.length,1);assert.equal(rows[0][idField],id);assert.equal((await api.show(id,scope)).title,created.title);
   const patch=plans?{goal:"Synthetic revised private goal",plannerFocusId:null,status:"active"}:{title:"Synthetic revised Workflow",enabled:false};
   const updated=await api.update(id,patch,scope);if(plans){assert.equal(updated.goal,patch.goal);assert.equal(updated.planner_focus_id,null);}else{assert.equal(updated.title,patch.title);assert.equal(updated.enabled,false);}
   assert.equal((await api.delete(id,{confirmed:true},scope)).deleted,true);assert.deepEqual(await api.list(scope),[]);
  }else if(mode==="strict"){
   await rejected(()=>client.plans.create({title:"synthetic",goal:"private",model:"forbidden"},filters));
   await rejected(()=>client.plans.create({title:"synthetic",goal:"private",linkedProjectIds:[]},filters));
   await rejected(()=>client.workflows.run(flow,{idempotencyKey:"intent",provider:"forbidden"},filters));
   await rejected(()=>client.workflows.wait(flow,run,{timeoutMs:0},filters));
   await rejected(()=>client.workflows.create({title:"invalid",graph:{nodes:[{id:"start",type:"manual_trigger"}],edges:[{from:"start",to:"absent"}]}},filters));
  }else if(mode==="scope"){
   const team={teamId:suite.team.team_id};
   await rejected(()=>client.plans.list(team),"unavailable");await rejected(()=>client.workflows.run(flow,camel(suite.input.run),team),"unavailable");await rejected(()=>client.plans.list({}));await rejected(()=>client.workflows.list({personal:true,...team}));
  }else if(mode==="consent"){
   await rejected(()=>client.workflows.create(camel(suite.input.workflow),filters),"forbidden");await rejected(()=>client.workflows.run(flow,camel(suite.input.run),filters),"forbidden");
  }else if(mode==="confirmation"){
   for(const api of[client.plans,client.workflows])await rejected(()=>api.delete(flow,{confirmed:false},filters));
  }else if(mode==="http_error"){
   await rejected(()=>client.workflows.run(flow,camel(suite.input.run),filters),"forbidden");
  }else{
   const accepted=await client.workflows.run(flow,camel(suite.input.run),filters);assert.equal(accepted.id,run);assert.equal(accepted.status,"queued");
   const options={timeoutMs:5000,pollIntervalMs:10,syncIntervalMs:10};if(mode==="timeout"){options.timeoutMs=30;options.pollIntervalMs=1000;}
   if(["cancel","local_cancel"].includes(mode)){
    options.pollIntervalMs=10000;
    const waiting=client.workflows.wait(flow,run,options,filters),checked=rejected(()=>waiting,"cancelled");
    for(let i=0;i<500&&!(await status()).polls;i++)await pause(10);assert.equal((await status()).polls,1);await pause(50);
    if(mode==="local_cancel"){client.cancel();await checked;assert.equal((await status()).cancel_posts,0);}
    else{
     const requests=(await status()).requests;let waitFinished=false;waiting.then(()=>{waitFinished=true},()=>{waitFinished=true});
     await rejected(()=>client.workflows.cancelRun(flow,run,{teamId:suite.team.team_id}),"unavailable");
     assert.equal(waitFinished,false);assert.equal((await status()).requests,requests);assert.equal((await status()).cancel_posts,0);
     const unrelated=client.plans.list(filters);await pause(20);
     const cancelling=client.workflows.cancelRun(flow,run,filters);await checked;assert.deepEqual(await unrelated,[]);assert.equal((await cancelling).status,"cancellation_requested");assert.equal((await client.workflows.runDetail(flow,run,filters)).status,"cancelled");
    }
   }else if(mode==="run"){
    const completed=await client.workflows.wait(flow,run,options,filters);assert.equal(completed.status,"completed");assert.equal(completed.output_summary.deliveries.end.status,"acknowledged");
   }else await rejected(()=>client.workflows.wait(flow,run,options,filters),mode==="bad_identity"?"forbidden":"invalid_argument");
  }
  const report=await status();assert.equal(report.failure,null);
  if(["strict","scope","consent","confirmation"].includes(mode)){assert.equal(report.requests,0);assert.equal(report.writes,0);assert.equal(report.run_posts,0);}
  else{
   const after=await client.exportSession({includeSecrets:true});assert.ok(after.revision>before.revision);assert.equal(after.session.cookies.auth_refresh_token,report.cookie);assert.ok(report.checks.includes("cookie-only-identity-and-rotation"));
   if(mode==="crud"){assert.equal(report.writes,3);assert.equal(report.run_posts,0);for(const c of vector.family==="plans"?["encrypted-plan-private-fields","plan-master-project-wrappers","typed-flow-roundtrip"]:["canonical-server-visible-definition","encrypted-workflow-slug","opaque-variable-names-preserved"])assert.ok(report.checks.includes(c));}
   else{assert.equal(report.run_posts,1);assert.equal(report.cancel_posts,Number(mode==="cancel"));for(const c of["stable-run-idempotency","no-invented-routing"])assert.ok(report.checks.includes(c));if(["failed","bad_identity"].includes(mode))assert.equal(report.polls,1);if(mode==="run")assert.equal(report.polls,2);if(mode==="http_error")assert.equal(report.polls,0);}
  }
  return{id:vector.id,status:"passed"};
 }finally{
  if(client)await client.close();lines.close();if(peer.pid&&peer.exitCode===null&&peer.signalCode===null){const stopped=new Promise(resolve=>peer.once("exit",resolve));peer.kill("SIGTERM");await stopped;}
 }
}
const args=process.argv.slice(2),option=n=>args[args.indexOf(n)+1];assert.equal(option("--capability"),CAPABILITY);
const fixturePath=option("--fixture"),raw=readFileSync(fixturePath),suite=JSON.parse(raw).capabilities[CAPABILITY],results=[];
for(const vector of suite.vectors)results.push(await runVector(suite,vector,fixturePath));
console.log(JSON.stringify({capability:CAPABILITY,language:"npm",status:"passed",fixtureSha256:createHash("sha256").update(raw).digest("hex"),results}));
