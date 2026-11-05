import {selectedRecovery} from './selected-recovery.mjs';
import {startupSync} from './startup-sync.mjs';
/** PRIVATE UNRUN. Actual built npm facade/NAPI against independent encrypted peer. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync,openSync,writeFileSync,fsyncSync,closeSync,readFileSync,renameSync,rmSync,mkdirSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createInterface} from 'node:readline';
import {SessionClient} from '../../../frontend/packages/openmates-cli/dist/sdk-entry.js';
const root=path.resolve(import.meta.dirname,'../../..');
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const bounded=(promise,ms=5000)=>Promise.race([promise,new Promise((_,reject)=>{const timer=setTimeout(()=>reject(new Error('bounded essential operation')),ms);timer.unref();})]);
async function get(endpoint,route){const response=await fetch(endpoint+route,{signal:AbortSignal.timeout(2000)});assert.equal(response.status,200);return response.json();}
async function refused(operation,codes){await assert.rejects(operation,error=>codes.includes(error?.code));}
async function wait(endpoint,predicate){const until=Date.now()+2000;while(Date.now()<until){const value=await get(endpoint,'/__test/status');if(predicate(value))return value;await new Promise(resolve=>setTimeout(resolve,10));}throw new Error('bounded peer condition');}
function session(suite,endpoint){return{api_url:endpoint,session_id:suite.account.session_id,cookies:{auth_refresh_token:suite.account.cookie},ws_token:null,master_key:suite.account.master_key,hashed_email:'synthetic-email-hash',user_email_salt:'synthetic-salt',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null};}
async function client(suite,endpoint){const value=new SessionClient({apiUrl:endpoint,appUrl:suite.protocol.app_origin,privacy:{enhanced:false},allowPrivateOperations:true});await value.importSession(session(suite,endpoint));return value;}
function durable(filename,raw){const fd=openSync(filename,'wx',0o600);try{writeFileSync(fd,raw);fsyncSync(fd);}finally{closeSync(fd);}}
function store(directory){
 const pointer=path.join(directory,'current');
 return{async generation(){return existsSync(pointer)?JSON.parse(readFileSync(pointer,'utf8')).version:null;},
  async compareAndSwap(input){const current=existsSync(pointer)?JSON.parse(readFileSync(pointer,'utf8')).version:null;if(current!==input.expectedVersion)return{stored:false};
   const target=path.join(directory,input.nextVersion);mkdirSync(target,{mode:0o700});
   const bytes=Buffer.from(input.checkpointJson,'utf8');durable(path.join(target,'checkpoint'),bytes);durable(path.join(target,'credentials'),Buffer.from(input.credentialsJson,'utf8'));
   const fd=openSync(target,'r');try{fsyncSync(fd);}finally{closeSync(fd);}
   const next=path.join(directory,'next');durable(next,JSON.stringify({version:input.nextVersion,scope:input.scope}));renameSync(next,pointer);const parent=openSync(directory,'r');try{fsyncSync(parent);}finally{closeSync(parent);}
   return{stored:true,ciphertext_sha256:hash(readFileSync(path.join(target,'checkpoint'))),credential_revision:input.credentialRevision};
  }};
}
async function vector(capability,suite,vector,fixture){
 const directory=mkdtempSync(path.join(tmpdir(),'openmates-essential-conformance-'));const python=process.env.OPENMATES_SDK_CONFORMANCE_PYTHON||'python3';
 const peer=spawn(python,[path.join(root,capability==='session.initial-startup-sync.v1'?'tests/sdk-conformance/startup_sync_server.py':'tests/sdk-conformance/essential_session_server.py'),'--fixture',fixture,'--capability',capability,'--vector',vector.id,'--identity','npm'],{cwd:root,stdio:['ignore','pipe','ignore']});
 const lines=createInterface({input:peer.stdout});let first,second,monitor;
 const watchdog=setTimeout(()=>{try{first?.cancel();second?.cancel();}catch{}peer.kill("SIGTERM");},12000);watchdog.unref();
 try{
  const ready=JSON.parse((await bounded(lines[Symbol.asyncIterator]().next())).value);const endpoint=ready.endpoint;assert.match(endpoint,/^http:\/\/127\.0\.0\.1:[1-9][0-9]*$/);first=await client(suite,endpoint);
  if(vector.mode.startsWith('startup_')){
   await startupSync({first,secondClient:()=>client(suite,endpoint),replaceCredentials:()=>first.importSession(session(suite,endpoint)),vector,endpoint,get,wait,refused});
  }else if(vector.mode.startsWith('selected_')){
   await selectedRecovery({first,suite,vector,endpoint,directory,get,wait,refused,durable,hash});
  }else if(vector.mode.startsWith('monitor')){
   monitor=await first.watchChats();
   if(vector.mode==='monitor_read_cancel'){await monitor.next();await monitor.refreshAndPublish(store(directory),{includeSecrets:true});const pending=monitor.next();pending.catch(()=>{});await new Promise(resolve=>setTimeout(resolve,20));await monitor.close();await refused(()=>pending,['cancelled']);monitor=await first.watchChats();await get(endpoint,'/__test/control?action=burst');}
   await monitor.next();
   if(vector.mode==='monitor_phase1b_context'){
    await refused(()=>monitor.stageRefresh({includeSecrets:true}),['forbidden']);
    assert.equal(existsSync(path.join(directory,'checkpoint')),false);
   }
   else if(vector.mode==='monitor_denial'){await get(endpoint,'/__test/control?action=deny');await refused(()=>monitor.stageRefresh({includeSecrets:true,selectedChatId:suite.protocol.initial_chat_id}),['forbidden']);const denial=monitor.accessDenial();assert.equal(denial.reason,'chat_unavailable');assert.equal(denial.chat_id,suite.protocol.initial_chat_id);assert.equal(existsSync(path.join(directory,'checkpoint')),false);}
   else if(vector.mode==='monitor_store_failure'){const failed={async generation(){return null;},async compareAndSwap(){throw new Error('synthetic-store-write-failed');}};await assert.rejects(()=>monitor.refreshAndPublish(failed,{includeSecrets:true}),/synthetic-store-write-failed/);await monitor.next();const models=await monitor.refreshAndPublish(store(directory),{includeSecrets:true});assert.ok(Array.isArray(models.items));}
   else if(vector.mode==='monitor_revoke'){await get(endpoint,'/__test/control?action=burst');await get(endpoint,'/__test/control?action=revoke');await wait(endpoint,status=>status.monitor_disconnects>=1);await refused(()=>monitor.stageRefresh({includeSecrets:true}),['cancelled','forbidden']);}
   else if(vector.mode==='monitor_data_changed'){
    const stage=await monitor.stageRefresh({includeSecrets:true});durable(path.join(directory,'checkpoint'),Buffer.from(stage.checkpoint_json,'utf8'));durable(path.join(directory,'credentials'),Buffer.from(stage.credentials_json,'utf8'));
    await get(endpoint,'/__test/control?action=advance');await first.list('chats');await refused(()=>monitor.commitRefresh(stage.id,{ciphertext_sha256:hash(readFileSync(path.join(directory,'checkpoint'))),credential_revision:stage.credential_revision}),['cancelled']);
   }
   else if(vector.mode==='monitor_cas'){
    const storage=store(directory);let entered,continueWrite;
    const started=new Promise(resolve=>{entered=resolve;});const proceed=new Promise(resolve=>{continueWrite=resolve;});
    const delayed={generation:scope=>storage.generation(scope),async compareAndSwap(input){entered();await proceed;return storage.compareAndSwap(input);}};
    const pending=monitor.refreshAndPublish(delayed,{includeSecrets:true});pending.catch(()=>{});await bounded(started);
    await get(endpoint,'/__test/control?action=advance');await first.list('chats');
    second=await client(suite,endpoint);const fresh=await second.watchChats();await fresh.next();
    const saved=await fresh.refreshAndPublish(storage,{includeSecrets:true});assert.ok(Array.isArray(saved.items));
    const before=readFileSync(path.join(directory,'current'));continueWrite();await refused(()=>pending,['conflict']);assert.deepEqual(readFileSync(path.join(directory,'current')),before);await fresh.close();
   }else{
    const stage=await monitor.stageRefresh({includeSecrets:true});assert.ok(stage.checkpoint_json.includes('camelCase')&&stage.checkpoint_json.includes('雪'));
    if(vector.mode.startsWith('monitor_phase1b')){
     const snapshot=JSON.parse(stage.checkpoint_json),id=suite.protocol.initial_chat_id,window=snapshot.sync_message_windows[id];
     assert.equal(window.messages.length,2);assert.equal(window.server_message_count,5);assert.equal(window.has_more_before,true);
     assert.equal(Object.hasOwn(snapshot.history,id),false);assert.equal(Object.hasOwn(window,'history_complete'),false);
     for(const message of window.messages){assert.equal(message.chat_id,id);assert.equal(typeof message.encrypted_content,'string');assert.equal(Object.hasOwn(message,'content'),false);}
     if(['monitor_phase1b_metadata_coverage','monitor_phase1b_metadata_responses'].includes(vector.mode)){
      const parents=[id,...Array.from({length:24},(_,index)=>`30000000-0000-4000-8000-${String(index+1).padStart(12,'0')}`)],child='60000000-0000-4000-8000-000000000000',expected=[...parents,child];
      if(vector.mode==='monitor_phase1b_metadata_responses'){
       expected.push('70000000-0000-4000-8000-000000000001','70000000-0000-4000-8000-000000000002');
       assert.equal(Object.hasOwn(snapshot.chats,'80000000-0000-4000-8000-000000000001'),false);assert.equal(Object.hasOwn(snapshot,'older_metadata_pages'),false);
       assert.equal(snapshot.chats[expected[27]].parent_id,expected[26]);assert.equal(snapshot.chats[expected[27]].is_sub_chat,true);
       for(const chat of expected.slice(26))assert.equal(Object.hasOwn(snapshot.history,chat),false);
      }
      assert.deepEqual(Object.keys(snapshot.chats).sort(),[...expected].sort());assert.deepEqual(snapshot.chat_arrival_order_v1.ids,expected);
      assert.deepEqual(Object.keys(snapshot.sync_message_windows).sort(),parents.slice(0,20).sort());
      assert.equal(snapshot.chats[child].parent_id,id);assert.equal(snapshot.chats[child].is_sub_chat,true);assert.equal(Object.hasOwn(snapshot.history,child),false);
      for(const [index,chat]of expected.entries()){const row=snapshot.chats[chat];assert.equal(row.id,chat);assert.equal(typeof row.encrypted_title,'string');assert.equal(row.pinned,index<25&&index%2===0||vector.mode==='monitor_phase1b_metadata_responses'&&index===26);assert.deepEqual(row.opaqueUserMetadata,{linkedProjectIds:['雪','😀'],camelCase:{sourceId:'preserve-verbatim'}});}
     }
    }
    const bytes=Buffer.from(stage.checkpoint_json+(vector.mode==='monitor_byte'?' ':''),'utf8');durable(path.join(directory,'checkpoint'),bytes);durable(path.join(directory,'credentials'),Buffer.from(stage.credentials_json,'utf8'));
    const invoke=()=>monitor.commitRefresh(stage.id,{ciphertext_sha256:hash(readFileSync(path.join(directory,'checkpoint'))),credential_revision:stage.credential_revision});
    if(vector.mode==='monitor_byte')await refused(invoke,['conflict']);else{const models=await invoke();assert.ok(Array.isArray(models.items));assert.equal(hash(bytes),stage.ciphertext_sha256);}
   }
   await monitor.close();
  }else{
   await refused(()=>first.completionRecovery.jobs(),['unavailable']);await first.completionRecovery.enable(true);
   if(vector.mode!=='disabled'){
    const jobs=await first.completionRecovery.jobs();assert.equal(jobs.length,1);
    if(vector.mode==='main_legacy_created_at'){
     const staged=await first.completionRecovery.stage(jobs[0].id);assert.equal(staged.kind,'ready');
     const needle=',"created_at":'+vector.created_at+'},"encrypted_candidate"';assert.equal(staged.checkpoint_json.split(needle).length,2);
     const legacy=staged.checkpoint_json.replace(needle,'},"encrypted_candidate"');assert.equal(Object.hasOwn(JSON.parse(legacy).job,'created_at'),false);
     durable(path.join(directory,'legacy-checkpoint'),Buffer.from(legacy));await first.close();await new Promise(resolve=>setTimeout(resolve,1200));
     first=await client(suite,endpoint);await first.completionRecovery.enable(true);const authentic=await first.completionRecovery.jobs();assert.equal(authentic[0].job.created_at,vector.created_at);
     const resumed=await first.completionRecovery.resume(readFileSync(path.join(directory,'legacy-checkpoint'),'utf8'));assert.equal(resumed.kind,'ready');
     assert.equal(resumed.checkpoint_json,legacy,'old canonical checkpoint bytes/ciphertext must survive metadata enrichment');
     const receipt=await first.completionRecovery.commit(resumed.id,{checkpoint_sha256:hash(readFileSync(path.join(directory,'legacy-checkpoint')))});assert.equal(receipt.state,'TERMINAL');
    }
    else if(vector.mode==='main_cancel'){const pending=first.completionRecovery.stage(jobs[0].id);await wait(endpoint,s=>s.claims===1);first.cancel();await refused(()=>pending,['cancelled']);}
    else{
     const stage=await first.completionRecovery.stage(jobs[0].id);assert.equal(stage.kind,'ready');if(vector.mode==='main_created_at')assert.equal(JSON.parse(stage.checkpoint_json).encrypted_candidate.created_at,vector.created_at);const raw=stage.checkpoint_json;const bytes=Buffer.from(raw+(vector.mode==='main_byte'?' ':''),'utf8');durable(path.join(directory,'checkpoint'),bytes);
     assert.equal((await get(endpoint,'/__test/status')).persists,0);
     if(vector.mode==='main_owner'){const before=(await get(endpoint,'/__test/status')).claims;const forged=raw.replace(suite.account.owner_id,'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');await refused(()=>first.completionRecovery.resume(forged),['forbidden']);assert.equal((await get(endpoint,'/__test/status')).claims,before);}
     if(vector.mode==='main_expiry')await new Promise(resolve=>setTimeout(resolve,2300));
     if(vector.mode==='main_reset')await first.importSession(session(suite,endpoint));
     const commit=()=>first.completionRecovery.commit(stage.id,{checkpoint_sha256:hash(readFileSync(path.join(directory,'checkpoint')))});
     if(vector.mode==='main_owner'){}
     else if(['main_byte','main_reset','main_expiry'].includes(vector.mode))await refused(commit,['conflict','cancelled']);
     else if(vector.mode==='main_cas_exhausted')await refused(commit,['conflict']);
     else if(vector.mode==='main_lost_ack'){await refused(commit,['offline']);await first.close();first=await client(suite,endpoint);await first.completionRecovery.enable(true);const resumed=await first.completionRecovery.resume(readFileSync(path.join(directory,'checkpoint'),'utf8'));assert.equal(resumed.kind,'canonical');assert.equal(resumed.receipt.assistant_message_id,suite.protocol.assistant_id);}
     else{const receipt=await commit();assert.equal(receipt.state,'TERMINAL');assert.equal(receipt.assistant_message_id,suite.protocol.assistant_id);}
    }
   }
  }
  await second?.close();await first.close();const status=await get(endpoint,'/__test/status');assert.equal(status.failure,null);assert.equal(status.admissions,0);
  if(vector.mode.startsWith('main_cas_')){assert.equal(status.persist_attempts,4);assert.equal(status.claims,1);}
  if(vector.mode==='main_legacy_created_at')assert.equal(status.claims,2);
  const expected=['main','main_lost_ack','selected_main','main_created_at','main_cas_retry','main_legacy_created_at'].includes(vector.mode)?1:0;assert.equal(status.persists,expected);return{id:vector.id,status:'passed'};
 }finally{try{try{first?.cancel();second?.cancel();}catch{}await bounded(Promise.resolve(monitor?.close()),2000).catch(()=>{});await bounded(Promise.resolve(second?.close()),2000).catch(()=>{});await bounded(Promise.resolve(first?.close()),2000).catch(()=>{});}finally{clearTimeout(watchdog);lines.close();if(peer.exitCode===null){peer.kill('SIGTERM');await bounded(new Promise(resolve=>peer.once('exit',resolve)),2000).catch(()=>peer.kill('SIGKILL'));}rmSync(directory,{recursive:true,force:true});}}
}
export async function main(expected){const args=process.argv.slice(2),option=name=>args[args.indexOf(name)+1];const capability=option('--capability');assert.equal(capability,expected);const fixture=path.resolve(option('--fixture'));const bytes=readFileSync(fixture);const suite=JSON.parse(bytes).capabilities[capability];const results=[];for(const entry of suite.vectors)results.push(await bounded(vector(capability,suite,entry,fixture),15000));console.log(JSON.stringify({capability,language:'npm',status:'passed',fixtureSha256:hash(bytes),results}));}
