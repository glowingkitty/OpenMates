/** Genuine NAPI saved-stream lifecycle; no facade/native doubles or test hooks. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
const ROOT=fileURLToPath(new URL('../../../../',import.meta.url));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const bounded=(work)=>Promise.race([work,new Promise((_,reject)=>setTimeout(()=>reject(new Error('saved stream deadline')),10000).unref())]);
export async function savedStreamVector(suite,vector,fixturePath,SessionClient,SessionClientError){
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/session_work_server.py','--fixture',fixturePath,'--vector',vector.id,'--identity','npm'],{cwd:ROOT,stdio:['ignore','pipe','ignore']});
 const lines=createInterface({input:peer.stdout});let client;
 try{
  const ready=await bounded(new Promise((resolve,reject)=>{lines.once('line',line=>{try{resolve(JSON.parse(line));}catch{reject(new Error('saved fixture readiness'));}});peer.once('error',()=>reject(new Error('saved fixture start')));peer.once('exit',()=>reject(new Error('saved fixture exited')));}));
  assert.match(ready.endpoint,/^http:\/\/127\.0\.0\.1:\d+$/);
  const spec=suite.saved_stream,account=spec.account,protocol=spec.protocol;
  const status=async()=>{const response=await fetch(ready.endpoint+'/__test/status');assert.equal(response.status,200);return response.json();};
  const wait=async(predicate)=>{for(let i=0;i<500;i++){const report=await status();assert.equal(report.failure,null);if(predicate(report))return report;await pause(10);}assert.fail('saved protocol barrier');};
  const assertB=async(chat)=>{const report=await status();const expected=report.admitted_messages.at(-1);assert.equal(chat.id,report.admitted_chats.at(-1));assert.ok(chat.messages.some(m=>m.id===expected&&m.role==='user'&&m.content===protocol.input));};
  client=new SessionClient({apiUrl:ready.endpoint,appUrl:protocol.app_origin,privacy:{enhanced:false},allowPrivateOperations:true});
  const session={api_url:ready.endpoint,session_id:account.session_id,cookies:{auth_refresh_token:account.cookie},ws_token:null,master_key:account.master_key,hashed_email:'synthetic-email-hash',user_email_salt:'synthetic-salt',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null};await client.importSession(session);
  const options=vector.chat_selector==='new'?{}:{chatId:protocol.initial_chat_id};
  const native=Reflect.get(client,'native');
  const nativeEvent=async(id)=>{const output=await native.nextEventPrepare(id);try{const raw=output.releaseJson();assert.throws(()=>output.releaseJson(),e=>JSON.parse(e.message).code==='cancelled');return JSON.parse(raw);}finally{output.discard();}};
  const drainNative=async(id)=>{try{while(true){const output=await native.nextEventPrepare(id);let terminal;try{terminal=output.isTerminal();}finally{output.discard();}if(terminal)break;}}catch(error){assert.equal(JSON.parse(error.message).code,'cancelled');}};
  const refused=operation=>assert.rejects(operation,e=>e instanceof SessionClientError&&['cancelled','expired','authentication','forbidden'].includes(e.code)&&!e.message.includes('synthetic-private'));
  if(vector.mode.startsWith('saved_owned_apps_')){
   const a=client.stream(protocol.input,options);let admitted;
   do{admitted=(await a.next()).value;assert.equal(admitted.type,'update');}while(!Object.hasOwn(admitted.update,'Admitted'));
   await wait(s=>s.admissions===1);assert.equal((await status()).closed_sockets,0);
   const assertInventory=rows=>{assert.equal(rows.length,1);assert.equal(rows[0].id,'fixture-app');assert.equal(rows[0].title,'Fixture inventory');assert.equal(rows[0].category,'Apps');assert.equal(rows[0].fields.id,'fixture-app');};
   if(vector.mode==='saved_owned_apps_pre_cancel'){
    const own=new AbortController();own.abort();await assert.rejects(client.list('apps',{signal:own.signal}),e=>e instanceof SessionClientError&&e.code==='cancelled');
    assert.equal((await status()).inventory_requests,0);
   }else if(vector.mode==='saved_owned_apps_success'){
    assertInventory(await bounded(client.list('apps')));assert.equal((await status()).inventory_requests,1);
   }else if(vector.mode==='saved_owned_apps_cancel_headers'){
    await fetch(ready.endpoint+'/__test/inventory-hold-next');const own=new AbortController();const b=client.list('apps',{signal:own.signal});const checked=assert.rejects(b,e=>e instanceof SessionClientError&&e.code==='cancelled');checked.catch(()=>{});
    await wait(s=>s.inventory_headers===1);
    // A second actual request must carry B's rotated cookie; its success is
    // the authenticated header-application witness, not the sent-header flag.
    assertInventory(await bounded(client.list('apps')));own.abort();await bounded(checked);
    await fetch(ready.endpoint+'/__test/inventory-release-body');assert.equal((await status()).inventory_requests,2);
   }else assert.fail('unknown saved owned Apps mode');
   assert.equal((await status()).closed_sockets,0,'own B cancellation cannot close actual A');
   await fetch(ready.endpoint+'/__test/release-owned-a');let completed;
   do{completed=(await bounded(a.next())).value;assert.notEqual(completed.type,'error');}while(completed.type!=='completed');await assertB(completed.chat);
   await a.return();const after=await client.exportSession({includeSecrets:true});
   if(vector.mode!=='saved_owned_apps_pre_cancel')assert.equal(after.session.cookies.auth_refresh_token,vector.mode==='saved_owned_apps_success'?'synthetic-inventory-rotation-1':'synthetic-inventory-rotation-2');
  }else if(vector.mode==='saved_auth_denial'){
   await refused(()=>client.send(protocol.input,options));await refused(()=>client.send(protocol.input,options));
  }else if(['saved_queued_import_revoke','saved_queued_close_revoke','saved_queued_malformed_revoke'].includes(vector.mode)){
   const a=await native.startSend(protocol.input,options.chatId);const held=await native.nextEventPrepare(a);
   assert.equal(held.isTerminal(),false);await wait(s=>s.admissions===1);
   if(vector.mode==='saved_queued_import_revoke')await client.importSession(session);else if(vector.mode==='saved_queued_close_revoke')await client.close();else await assert.rejects(()=>client.importSession({}),e=>e instanceof SessionClientError&&e.code==='invalid_argument');
   assert.throws(()=>held.releaseJson(),e=>JSON.parse(e.message).code==='cancelled');held.discard();await drainNative(a);
   if(vector.mode==='saved_queued_import_revoke'){const b=await client.send(protocol.input);await assertB(b);}
   if(vector.mode==='saved_queued_malformed_revoke'){const unchanged=await client.exportSession({includeSecrets:true});assert.equal(unchanged.session.session_id,session.session_id);assert.equal(unchanged.session.master_key,session.master_key);}
  }else if(vector.mode==='saved_queued_successor_terminal'){
   const a=await native.startSend(protocol.input,options.chatId);let held;
   while(true){held=await native.nextEventPrepare(a);if(held.isTerminal())break;held.releaseJson();held.discard();}
   await wait(s=>s.closed_sockets===1);const b=await native.startSend(protocol.input,options.chatId);
   let event;do{event=await nativeEvent(b);assert.equal(event.type,'update');}while(!Object.hasOwn(event.update,'Admitted'));
   await wait(s=>s.admissions===2);assert.throws(()=>held.releaseJson(),e=>JSON.parse(e.message).code==='cancelled');held.discard();assert.equal((await status()).closed_sockets,1);
   await fetch(ready.endpoint+'/__test/release-b');do{event=await nativeEvent(b);assert.notEqual(event.type,'error');}while(event.type!=='completed');await assertB(event.chat);
  }else if(vector.mode==='saved_pre_effect_abort'){
   const a=await native.startSend(protocol.input,options.chatId);await wait(s=>s.snapshot_waiting);
   native.cancelStream(a);await drainNative(a);await wait(s=>s.closed_sockets===1);
   const b=await bounded(client.send(protocol.input,options));await assertB(b);
  }else if(vector.mode==='saved_stale_terminal'){
   // Exercise the actual public native ID API directly for exact stale-id
   // refusal. The other modes execute the maintained ergonomic facade itself.
   const a=await native.startSend(protocol.input,options.chatId);
   while((await nativeEvent(a)).type!=='completed'){}await wait(s=>s.closed_sockets===1);
   const b=await native.startSend(protocol.input,options.chatId);await wait(s=>s.admissions===2);
   assert.throws(()=>native.cancelStream(a),e=>JSON.parse(e.message).code==='conflict');
   assert.equal((await status()).closed_sockets,1,'stale A must leave B socket open');
   await fetch(ready.endpoint+'/__test/release-b');let event;
   do{event=await nativeEvent(b);assert.notEqual(event.type,'error');}while(event.type!=='completed');await assertB(event.chat);
  }else{
   const controller=new AbortController();const a=client.stream(protocol.input,{...options,signal:controller.signal});
   let admitted;do{admitted=(await a.next()).value;assert.equal(admitted.type,'update');}while(!Object.hasOwn(admitted.update,'Admitted'));await wait(s=>s.admissions===1);
   if(vector.mode==='saved_active_task_cancel'){let content;do{content=(await a.next()).value;assert.equal(content.type,'update');}while(!Object.hasOwn(content.update,'Content'));assert.equal(content.update.Content.content,'Synthetic live fragment');}
   if(['saved_consumer_close','saved_same_chat_after_uncertain','saved_active_task_cancel'].includes(vector.mode))await a.return();
   else if(vector.mode==='saved_host_abort'){controller.abort();await refused(()=>a.next());await a.return();}
   else if(vector.mode==='saved_global_cancel'){client.cancel();await refused(()=>a.next());await a.return();}
   else if(vector.mode==='saved_close_no_rearm'){const close=client.close();await refused(()=>a.next());await a.return();await close;await refused(()=>client.send(protocol.input,options));}
   else assert.fail('unknown saved mode');
   await wait(s=>s.closed_sockets>=1);
   if(vector.mode!=='saved_close_no_rearm'){
    // A remains quarantined/uncertain; B is a new caller-owned operation.
    const bOptions=vector.successor_chat_selector==='same'?options:{};
    const b=await client.send(protocol.input,bOptions);await assertB(b);
   }
  }
  const report=await wait(s=>s.admissions===vector.expected_admissions);assert.equal(report.failure,null);
  assert.equal(new Set(report.turns).size,vector.expected_admissions);assert.equal(new Set(report.message_ids).size,vector.expected_admissions);
  if(vector.mode==='saved_active_task_cancel')assert.equal(report.task_cancel_requests,1);
  if(vector.mode==='saved_auth_denial')assert.ok(report.auth_denials>=1);
  else for(const name of ['actual-encrypted-saved-admission','no-replay-of-turn-or-message-identities','no-model-provider-override'])assert.ok(report.checks.includes(name));
  return{id:vector.id,status:'passed'};
 }finally{
  try{await bounded(Promise.resolve(client?.close()));}finally{lines.close();if(peer.exitCode===null&&peer.signalCode===null){const stopped=new Promise(resolve=>peer.once('exit',resolve));peer.kill('SIGTERM');await bounded(stopped);}}
 }
}
