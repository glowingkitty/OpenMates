/** Actual NAPI library bounded saved-read reads against a synthetic owned loopback peer.
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
const CAPABILITY='session.saved-chat-read.v1';
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
async function assertFullRead(client,suite,vector,id,status,endpoint) {
 let result,errorCode=null;
 try {
  if(vector.full_action==='inflight_cancel') {
   const pending=settledOutcome(client.openChat(id));let observed=false;
   for(let i=0;i<500;i++){if((await status()).metadata===1){observed=true;break;}await new Promise(r=>setTimeout(r,5));}
   assert.equal(observed,true);client.cancel();
   const response=await fetch(endpoint+'/__test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'release'}),signal:AbortSignal.timeout(3000)});assert.equal(response.status,200);
   const outcome=await pending;if(Object.hasOwn(outcome,'error'))throw outcome.error;result=outcome.value;
  } else result=await bounded(client.openChat(id));
 } catch(error) {assert.ok(error instanceof SessionClientError);errorCode=error.code;}
 assert.equal(errorCode,vector.expected_error);
 if(errorCode!==null){assert.equal(result,undefined);return;}
 assert.deepEqual(result,vector.full_expected);
 // Real native prepare returns an opaque object after actual HTTP/decryption.
 // This deliberately exercises the production final runtime allocator itself.
 if(vector.foreign_final){
  const output=await bounded(client.native.openChatPrepare(id));
  try {
   const finish=()=>output.releaseJson();
   const refused=(code='cancelled')=>assert.throws(finish,error=>{
    assert.ok(error instanceof Error);const detail=JSON.parse(error.message);
    assert.equal(detail.code,code);return true;
   });
   if(vector.foreign_final==='permitted') {assert.deepEqual(JSON.parse(finish()),vector.full_expected);refused();}
   else if(vector.foreign_final==='cancel') {client.cancel();refused();}
   else if(vector.foreign_final==='owner') {
    await client.importSession({api_url:endpoint,session_id:suite.account.session_id+'-replacement',cookies:{auth_refresh_token:suite.account.cookie},ws_token:null,master_key:suite.account.master_key,hashed_email:'other-synthetic-owner',user_email_salt:'synthetic',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null});refused();
   } else if(vector.foreign_final==='successor') {
    // B holds the actual client/HTTP lane; A must refuse without blocking,
    // replacing or cancelling B's child. Then B genuinely finishes publicly.
    const pending=settledOutcome(client.openChat(id));let observed=false;
    for(let i=0;i<500;i++){if((await status()).metadata===3){observed=true;break;}await new Promise(r=>setTimeout(r,5));}
    assert.equal(observed,true);refused('conflict');
    const response=await fetch(endpoint+'/__test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'release'}),signal:AbortSignal.timeout(3000)});assert.equal(response.status,200);
    const outcome=await pending;if(Object.hasOwn(outcome,'error'))throw outcome.error;
    assert.deepEqual(outcome.value,vector.full_expected);assert.ok((await status()).checks.includes('successor-barrier-released'));
   } else {assert.equal(vector.foreign_final,'discard');output.discard();refused();}
  } finally {output.discard();}
 }
}

async function assertDetailsRead(client,suite,vector,id,status,endpoint) {
 const expected=structuredClone(vector.expected_details);
 if(vector.expected_draft_utf16)expected.chat.draftPreview=String.fromCharCode(...vector.expected_draft_utf16);
 if(vector.expected_pii_utf16)expected.messages[vector.expected_pii_utf16.index].piiMappings=[String.fromCharCode(...vector.expected_pii_utf16.units)];
 if(vector.semantic_pii)expected.messages[vector.semantic_pii.message_index].piiMappings=JSON.parse(vector.semantic_pii.sdk_json);
 let result,errorCode=null;
 try {
  if(vector.details_action==='inflight_cancel') {
   const pending=settledOutcome(client.chatDetails(id,vector.details_options));let observed=false;
   for(let i=0;i<500;i++){if((await status())[vector.cancel_barrier??'metadata']===1){observed=true;break;}await new Promise(r=>setTimeout(r,5));}
   assert.equal(observed,true);client.cancel();
   const response=await fetch(endpoint+'/__test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'release'}),signal:AbortSignal.timeout(3000)});assert.equal(response.status,200);
   const outcome=await pending;if(Object.hasOwn(outcome,'error'))throw outcome.error;result=outcome.value;
  } else result=await bounded(client.chatDetails(id,vector.details_options));
 } catch(error) {assert.ok(error instanceof SessionClientError);errorCode=error.code;}
 assert.equal(errorCode,vector.expected_error);
 if(errorCode!==null){assert.equal(result,undefined);return;}
 assert.deepEqual(result,expected);
 // Real native prepare returns an opaque object after actual HTTP/decryption.
 // This deliberately exercises the production final runtime allocator itself.
 if(vector.foreign_final){
  const output=await bounded(client.native.chatDetailsPrepare(id,JSON.stringify(vector.details_options)));
  try {
   const finish=()=>output.releaseJson();
   const refused=(code='cancelled')=>assert.throws(finish,error=>{
    assert.ok(error instanceof Error);const detail=JSON.parse(error.message);
    assert.equal(detail.code,code);return true;
   });
   if(vector.foreign_final==='permitted') {assert.deepEqual(JSON.parse(finish()),expected);refused();}
   else if(vector.foreign_final==='cancel') {client.cancel();refused();}
   else if(vector.foreign_final==='owner') {
    await client.importSession({api_url:endpoint,session_id:suite.account.session_id+'-replacement',cookies:{auth_refresh_token:suite.account.cookie},ws_token:null,master_key:suite.account.master_key,hashed_email:'other-synthetic-owner',user_email_salt:'synthetic',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null});refused();
   } else if(vector.foreign_final==='successor') {
    // B holds the actual client/HTTP lane; A must refuse without blocking,
    // replacing or cancelling B's child. Then B genuinely finishes publicly.
    const pending=settledOutcome(client.chatDetails(id,vector.details_options));let observed=false;
    for(let i=0;i<500;i++){if((await status()).metadata===3){observed=true;break;}await new Promise(r=>setTimeout(r,5));}
    assert.equal(observed,true);refused('conflict');
    const response=await fetch(endpoint+'/__test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'release'}),signal:AbortSignal.timeout(3000)});assert.equal(response.status,200);
    const outcome=await pending;if(Object.hasOwn(outcome,'error'))throw outcome.error;
    assert.deepEqual(outcome.value,expected);assert.ok((await status()).checks.includes('successor-barrier-released'));
   } else {assert.equal(vector.foreign_final,'discard');output.discard();refused();}
  } finally {output.discard();}
 }
}

async function runVector(suite,vector,fixture) {
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/saved_chat_read_server.py','--fixture',fixture,'--vector',vector.id,'--identity','npm'],{cwd:ROOT,stdio:['ignore','pipe','ignore']});
 const lines=createInterface({input:peer.stdout});let client;
 try {
  const ready=await bounded(new Promise((resolve,reject)=>{lines.once('line',line=>{try{resolve(JSON.parse(line));}catch{reject(new Error('fixture readiness'));}});peer.once('error',()=>reject(new Error('fixture launch')));peer.once('exit',()=>reject(new Error('fixture exit')));}));
  assert.match(ready.endpoint,/^http:\/\/127\.0\.0\.1:\d+$/);
  const status=async()=>{const r=await fetch(ready.endpoint+'/__test/status',{signal:AbortSignal.timeout(3000)});assert.equal(r.status,200);return r.json();};
  const allowPrivateOperations=Object.hasOwn(vector,'allow_private_operations')?vector.allow_private_operations:suite.allow_private_operations;
  assert.equal(typeof allowPrivateOperations,'boolean');
  client=new SessionClient({apiUrl:ready.endpoint,appUrl:suite.protocol.app_origin,privacy:{enhanced:false},allowPrivateOperations});
  if(vector.mode!=='noauth'&&vector.full_action!=='noauth'&&vector.details_action!=='noauth')await client.importSession({api_url:ready.endpoint,session_id:suite.account.session_id,cookies:{auth_refresh_token:suite.account.cookie},ws_token:null,master_key:suite.account.master_key,hashed_email:'synthetic',user_email_salt:'synthetic',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:vector.team_id??null});
  const id=suite.protocol.chat_id;
  if(vector.mode==='details') {
   await assertDetailsRead(client,suite,vector,id,status,ready.endpoint);
   const report=await status();assert.equal(report.failure,null);assert.equal(report.identity,'npm');assert.equal(report.consumed,vector.requests.length);assert.equal(report.metadata,vector.expected_metadata_requests);assert.equal(report.window,vector.expected_window_requests);assert.equal(report.exact,vector.expected_exact_requests);assert.equal(report.details_embeds,vector.expected_embed_requests);for(const check of vector.expected_checks)assert.ok(report.checks.includes(check));
   return {id:vector.id,status:'passed',checks:vector.expected_checks,detailsBoundary:vector.foreign_final??vector.details_action};
  }
  if(vector.mode==='full') {
   await assertFullRead(client,suite,vector,id,status,ready.endpoint);
   const report=await status();assert.equal(report.failure,null);assert.equal(report.identity,'npm');assert.equal(report.consumed,vector.requests.length);assert.equal(report.metadata,vector.expected_metadata_requests);assert.equal(report.window,vector.expected_window_requests);assert.equal(report.exact,vector.expected_exact_requests);for(const check of vector.expected_checks)assert.ok(report.checks.includes(check));
   return {id:vector.id,status:'passed',checks:vector.expected_checks,fullReadBoundary:vector.foreign_final??vector.full_action};
  }
  let options=structuredClone(vector.options);let expectedScope=null;
  if(Object.hasOwn(vector,'preflight')){const first=await client.savedChatRead(id,vector.preflight);assertWindow(suite,{expected_public_paging:vector.preflight_expected,expected_messages:vector.preflight_expected.chat.messages},first);expectedScope=first.startCursor.scope;options={...options,[vector.mode==='after'?'after':'before']:{...first.startCursor}};assert.ok(options[vector.mode==='after'?'after':'before'].scope);}
  if(vector.mode==='partial_cache')assert.deepEqual((await client.openChat(id)).messages,vector.expected_cached_messages);
  let result,errorCode=null;
  try {
   if(vector.mode==='cancel'){
    const pending=settledOutcome(client.savedChatRead(id,options));let observed=false;
    for(let i=0;i<500;i++){if((await status()).metadata===1){observed=true;break;}await new Promise(r=>setTimeout(r,5));}
    assert.equal(observed,true);client.cancel();const release=await fetch(ready.endpoint+'/__test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'release'}),signal:AbortSignal.timeout(3000)});assert.equal(release.status,200);const outcome=await pending;if(Object.hasOwn(outcome,'error'))throw outcome.error;result=outcome.value;
   }else result=await bounded(client.savedChatRead(id,options));
  }catch(error){assert.ok(error instanceof SessionClientError);errorCode=error.code;}
  assert.equal(errorCode,vector.expected_error);
  if(vector.expected_error===null){assertWindow(suite,vector,result,expectedScope);if(vector.mode==='exact'){
    const cursor=structuredClone(result.oversizedMessageCursor);
    if(vector.exactCursorMutation==='scope')cursor.scope='0'.repeat(64);
    if(vector.exactCursorMutation==='chat')cursor.chatId='99999999-9999-4999-8999-999999999999';
    let exact,exactError=null;
    try{
     const operation=client.savedChatExactMessage(id,{cursor,contentMode:'stored'});
     if(vector.exactAction==='cancel'){
      const pending=settledOutcome(operation);let observed=false;
      for(let i=0;i<500;i++){if((await status()).metadata===2){observed=true;break;}await new Promise(r=>setTimeout(r,5));}
      assert.equal(observed,true);client.cancel();const release=await fetch(ready.endpoint+'/__test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'release'}),signal:AbortSignal.timeout(3000)});assert.equal(release.status,200);
      const outcome=await pending;if(Object.hasOwn(outcome,'error'))throw outcome.error;exact=outcome.value;
     }else exact=await bounded(operation);
    }catch(error){assert.ok(error instanceof SessionClientError);exactError=error.code;}
    assert.equal(exactError,vector.exact_expected_error??null);
    if(exactError===null)assert.deepEqual(exact,vector.exact_expected);else assert.equal(exact,undefined);
   }}
  else assert.equal(result,undefined);
  if(vector.mode==='partial_cache')assert.deepEqual((await client.openChat(id)).messages,vector.expected_cached_messages);
  const report=await status();assert.equal(report.exact,vector.expected_exact_requests);assert.equal(report.consumed,vector.requests.length);assert.equal(report.failure,null);assert.equal(report.metadata,vector.expected_metadata_requests);assert.equal(report.window,vector.expected_window_requests);assert.equal(report.identity,'npm');for(const check of vector.expected_checks)assert.ok(report.checks.includes(check));
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
if(process.argv[1]&&pathToFileURL(process.argv[1]).href===import.meta.url)main().catch(()=>{process.stderr.write('npm bounded saved-read library conformance failed\n');process.exitCode=1;});
