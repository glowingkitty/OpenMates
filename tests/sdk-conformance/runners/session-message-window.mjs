/** Actual NAPI library one-page reads against a synthetic owned loopback peer.
 * Public fixture credentials only; no CLI or installed profile is discovered.
 * Peer commands belong to this harness, never the SessionClient implementation.
 * Every expected failure and response/call bound is independently asserted.
 * Root runs this executable only in isolated managed conformance CI.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath, pathToFileURL } from 'node:url';
const {SessionClient,SessionClientError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
const CAPABILITY='session.message-window.v1';
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
const bounded = promise => Promise.race([promise,new Promise((_,reject)=>setTimeout(()=>reject(new Error('bounded fixture timeout')),10000).unref())]);
// Observe rejection synchronously, before polling/cancel/control awaits.
export function settledOutcome(promise) {
 return promise.then(value=>({value}),error=>({error}));
}
export function assertWindow(suite,vector,result,expectedScope=null) {
 const expected=structuredClone(vector.expected_public_paging);
 assert.ok(expected&&typeof expected==='object');
 expected.chat.messages=structuredClone(vector.expected_messages);
 let scope=expectedScope;
 for(const name of ['startCursor','endCursor','oversizedMessageCursor']) {
  if(expected[name]===null){assert.equal(result[name],null);continue;}
  const actual=result[name];assert.ok(actual&&typeof actual==='object');
  assert.deepEqual(Object.keys(actual).sort(),['chatId','scope','createdAt','messageId'].sort());
  assert.equal(actual.chatId,suite.protocol.chat_id);assert.match(actual.scope,/^[0-9a-f]{64}$/);
  if(scope===null)scope=actual.scope;else assert.equal(actual.scope,scope);
  expected[name].chatId=suite.protocol.chat_id;expected[name].scope=scope;
 }
 assert.deepEqual(result,expected);
 assert.ok(result.payloadBytes<=suite.protocol.page_max_bytes);
}
async function runVector(suite,vector,fixture) {
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/message_window_server.py','--fixture',fixture,'--vector',vector.id,'--identity','npm'],{cwd:ROOT,stdio:['ignore','pipe','ignore']});
 const lines=createInterface({input:peer.stdout});let client;
 try {
  const ready=await bounded(new Promise((resolve,reject)=>{lines.once('line',line=>{try{resolve(JSON.parse(line));}catch{reject(new Error('fixture readiness'));}});peer.once('error',()=>reject(new Error('fixture launch')));peer.once('exit',()=>reject(new Error('fixture exit')));}));
  assert.match(ready.endpoint,/^http:\/\/127\.0\.0\.1:\d+$/);
  const status=async()=>{const r=await fetch(ready.endpoint+'/__test/status',{signal:AbortSignal.timeout(3000)});assert.equal(r.status,200);return r.json();};
  const allowPrivateOperations=Object.hasOwn(vector,'allow_private_operations')?vector.allow_private_operations:suite.allow_private_operations;
  assert.equal(typeof allowPrivateOperations,'boolean');
  client=new SessionClient({apiUrl:ready.endpoint,appUrl:suite.protocol.app_origin,privacy:{enhanced:false},allowPrivateOperations});
  if(vector.mode!=='noauth')await client.importSession({api_url:ready.endpoint,session_id:suite.account.session_id,cookies:{auth_refresh_token:suite.account.cookie},ws_token:null,master_key:suite.account.master_key,hashed_email:'synthetic',user_email_salt:'synthetic',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null});
  const id=suite.protocol.chat_id;let options=structuredClone(vector.options);let expectedScope=null;
  if(vector.preflight){const first=await client.chatMessageWindow(id,vector.preflight);assertWindow(suite,suite.vectors.find(v=>v.mode==='latest'),first);expectedScope=first.startCursor.scope;options={...options,direction:vector.mode==='after'?'after':'before',cursor:{...first.startCursor}};assert.ok(options.cursor.scope);if(vector.mode==='forbidden_context')options.cursor.chatId='99999999-9999-4999-8999-999999999999';if(vector.mode==='wrong_scope')options.cursor.scope='0'.repeat(64);}
  if(vector.mode==='partial_cache')assert.deepEqual((await client.openChat(id)).messages,vector.expected_cached_messages);
  let result,errorCode=null;
  try {
   if(vector.mode==='cancel'){
    const pending=settledOutcome(client.chatMessageWindow(id,options));let observed=false;
    for(let i=0;i<500;i++){if((await status()).metadata===1){observed=true;break;}await new Promise(r=>setTimeout(r,5));}
    assert.equal(observed,true);client.cancel();const release=await fetch(ready.endpoint+'/__test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'release'}),signal:AbortSignal.timeout(3000)});assert.equal(release.status,200);const outcome=await pending;if(Object.hasOwn(outcome,'error'))throw outcome.error;result=outcome.value;
   }else result=await bounded(client.chatMessageWindow(id,options));
  }catch(error){assert.ok(error instanceof SessionClientError);errorCode=error.code;}
  assert.equal(errorCode,vector.expected_error);
  if(vector.expected_error===null){assertWindow(suite,vector,result,expectedScope);}
  else assert.equal(result,undefined);
  if(vector.mode==='partial_cache')assert.deepEqual((await client.openChat(id)).messages,vector.expected_cached_messages);
  const report=await status();assert.equal(report.failure,null);assert.equal(report.metadata,vector.expected_metadata_requests);assert.equal(report.window,vector.expected_window_requests);assert.equal(report.identity,'npm');for(const check of vector.expected_checks)assert.ok(report.checks.includes(check));
  await client.close();client=null;
  return {id:vector.id,status:'passed',checks:vector.expected_checks};
 } finally {
  try { if(client)await client.close(); } finally {
   lines.close();
   if(peer.exitCode===null&&peer.signalCode===null){peer.kill('SIGTERM');await Promise.race([new Promise(r=>peer.once('exit',r)),new Promise(r=>setTimeout(r,1000))]);if(peer.exitCode===null&&peer.signalCode===null){peer.kill('SIGKILL');await bounded(new Promise(r=>peer.once('exit',r)));}}
  }
 }
}
async function main(){const args=process.argv.slice(2),option=name=>args[args.indexOf(name)+1];assert.equal(option('--capability'),CAPABILITY);const file=option('--fixture'),raw=readFileSync(file),suite=JSON.parse(raw).capabilities[CAPABILITY];const results=[];for(const vector of suite.vectors)results.push(await runVector(suite,vector,file));process.stdout.write(JSON.stringify({capability:CAPABILITY,language:'npm',status:'passed',fixtureSha256:createHash('sha256').update(raw).digest('hex'),results})+'\n');}
if(process.argv[1]&&pathToFileURL(process.argv[1]).href===import.meta.url)main().catch(()=>{process.stderr.write('npm one-page library conformance failed\n');process.exitCode=1;});
