/** Actual NAPI anonymous inference through the shared test-only loopback peer. */
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {createHash} from "node:crypto";
import {readFileSync} from "node:fs";
import {createInterface} from "node:readline";
import {fileURLToPath} from "node:url";
const{SessionClient,SessionClientError}=await import("../../../frontend/packages/openmates-cli/dist/sdk-entry.js");
const ROOT=fileURLToPath(new URL("../../../",import.meta.url)),CAPABILITY="session.anonymous-stream.v1";
const rejected=(operation,code)=>assert.rejects(operation,e=>e instanceof SessionClientError&&e.code===code&&!e.message.includes("synthetic-private-server-diagnostic"));
function outcome(value,suite){
 assert.equal(value.status,"completed");assert.equal(value.assistant,suite.text);assert.match(value.chatId,/^anonymous-/);assert.deepEqual(value.followUpSuggestions,["Synthetic follow-up"]);
 for(const field of["pendingTaskUpdateJobs","taskEvents","subChatEvents","appSettingsMemoryRequests"])assert.deepEqual(value[field],[]);
 assert.equal(value.chat.id,value.chatId);assert.equal(value.chat.messages.length,2);
 assert.equal(value.userMessageId,value.chat.messages[0].id);assert.match(value.userMessageId,/^anonymous-message-/);
 for(const message of value.chat.messages)assert.equal(message.content,suite.text);
}
async function runVector(suite,vector,fixture){
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??"python3",["tests/sdk-conformance/session_anonymous_server.py","--fixture",fixture,"--vector",vector.id,"--identity","npm"],{cwd:ROOT,stdio:["ignore","pipe","ignore"]}),lines=createInterface({input:peer.stdout});let client;
 try{
  const ready=await Promise.race([new Promise((resolve,reject)=>{lines.once("line",line=>{try{resolve(JSON.parse(line));}catch{reject(new Error("fixture readiness"));}});peer.once("error",()=>reject(new Error("fixture unavailable")));peer.once("exit",()=>reject(new Error("fixture exited")));}),new Promise((_,reject)=>setTimeout(()=>reject(new Error("fixture startup timeout")),10000).unref())]);
  assert.match(ready.endpoint,/^http:\/\/127\.0\.0\.1:\d+$/);
  const status=async()=>{const response=await fetch(ready.endpoint+"/__test/status");assert.equal(response.status,200);return response.json();};
  client=new SessionClient({apiUrl:ready.endpoint,appUrl:"https://app.example.invalid",privacy:{enhanced:false},allowPrivateOperations:vector.allow_private});
  let before;
  if(vector.signed){const a=suite.account;await client.importSession({api_url:ready.endpoint,session_id:a.session_id,cookies:{auth_refresh_token:a.cookie},ws_token:null,master_key:a.master_key,hashed_email:"synthetic-email",user_email_salt:"synthetic-salt",email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null});before=await client.exportSession({includeSecrets:true});}
  const mode=vector.mode,call=()=>client.sendAnonymous(suite.anonymous_id,suite.text);
  if(mode==="sse"){
   for(let repetition=0;repetition<vector.repetitions;repetition++){
    if(repetition)outcome(await call(),suite);
    else{const seen=new Set();for await(const event of client.streamAnonymous(suite.anonymous_id,suite.text)){if(event.type==="update")for(const key of Object.keys(event.update))seen.add(key);else outcome(event.outcome,suite);}for(const type of["Started","Submitted","Content","Completed"])assert.ok(seen.has(type));assert.ok(!seen.has("Admitted")&&!seen.has("Consent"));}
   }
  }else if(mode==="cancel"){
   let content=false;for await(const event of client.streamAnonymous(suite.anonymous_id,suite.text)){if(event.type==="update"&&event.update.Content){content=true;break;}}assert.ok(content);await fetch(ready.endpoint+"/__test/release");outcome(await call(),suite);
  }else if(mode==="preflight"){
   for(const id of["","invalid id","x".repeat(129)])await rejected(()=>client.sendAnonymous(id,suite.text),"invalid_argument");
   for(const options of[{model:"forbidden"},{projectId:"11111111-1111-4111-8111-111111111111"},{responseTimeoutMs:0}])await rejected(()=>client.sendAnonymous(suite.anonymous_id,suite.text,options),"invalid_argument");
   const aborted=new AbortController();aborted.abort();await rejected(()=>client.sendAnonymous(suite.anonymous_id,suite.text,{signal:aborted.signal}),"cancelled");
  }else await rejected(call,({budget:"signup_required",redirect:"forbidden",malformed:"protocol",policy:"forbidden",private:"protocol"})[mode]);
  if(vector.signed)assert.deepEqual(await client.exportSession({includeSecrets:true}),before);else await rejected(()=>client.exportSession({includeSecrets:true}),"authentication");
  const report=await status();assert.equal(report.failure,null);assert.equal(report.redirects,0);
  if(["preflight","policy"].includes(mode)){assert.equal(report.status_gets,0);assert.equal(report.posts,0);}else{const expected=mode==="cancel"?2:vector.repetitions;assert.equal(report.status_gets,expected);assert.equal(report.posts,["budget","redirect"].includes(mode)?0:expected);assert.ok(report.checks.includes("public-headers-without-account-identity"));if(report.posts){for(const c of["local-pii-redaction","empty-history-fresh-ephemeral-identities","no-routing-or-durable-capabilities"])assert.ok(report.checks.includes(c));assert.equal(report.chat_ids.length,expected);}}
  return{id:vector.id,status:"passed"};
 }finally{if(client)await client.close();lines.close();if(peer.pid&&peer.exitCode===null&&peer.signalCode===null){const stopped=new Promise(resolve=>peer.once("exit",resolve));peer.kill("SIGTERM");await stopped;}}
}
const args=process.argv.slice(2),option=name=>args[args.indexOf(name)+1];assert.equal(option("--capability"),CAPABILITY);
const fixture=option("--fixture"),raw=readFileSync(fixture),suite=JSON.parse(raw).capabilities[CAPABILITY],results=[];
for(const vector of suite.vectors)results.push(await runVector(suite,vector,fixture));
console.log(JSON.stringify({capability:CAPABILITY,language:"npm",status:"passed",fixtureSha256:createHash("sha256").update(raw).digest("hex"),results}));
