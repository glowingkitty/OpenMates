/** PRIVATE UNRUN: real built npm SessionClient and NAPI, synthetic loopback only. */
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {deadline,cleanupOwned,runOwned,terminateChild,createOwnership} from './support/owned-lifecycle.mjs';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync,mkdirSync,openSync,writeFileSync,readFileSync,fsyncSync,closeSync,renameSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createInterface} from 'node:readline';
import {SessionClient} from '../../../frontend/packages/openmates-cli/dist/sdk-entry.js';
const CAP='session.chat-first-page-continuation.v1',root=path.resolve(import.meta.dirname,'../../..');
const vectors=[['cold-uuid','admit'],['cold-composite','admit'],['cold-opaque','admit'],['capacity-refused','capacity-false'],['capacity-io-error','capacity-error'],['wrong-checkpoint-hash','wrong-hash'],['wrong-credential-revision','wrong-revision'],['receipt-purpose-separated','wrong-purpose'],['store-cas-refused','cas-refused'],['callback-failed','callback-failure'],['callback-cancelled','callback-cancel'],['stale-a-preserves-b','stale-a-b'],['missing-secret-consent','no-secrets'],['missing-private-consent','no-private'],['warm-default-preserved','warm'],['strict-default-preserved','strict']];
const hash=raw=>createHash('sha256').update(raw).digest('hex');
// Closed diagnostic projection only. Error text/values/stacks never leave RAM.
const phases=new Set(['suite','peer_start','client_setup','session_import','session_validate','store_io','callback','stale_a_b','strict','continuation','negative','vector_complete']);
const errorCodes=new Set(['assertion','cancelled','conflict','forbidden','expired','authentication','invalid_argument','protocol','offline','unavailable','crypto','native_failure','native_binding_unavailable','storage_io','timeout','callback','unclassified']);
let diagnosticPhase='suite';
function closedDiagnostic(error,vectorId){
 let errorCode=error?.code==='ERR_ASSERTION'?'assertion':errorCodes.has(error?.code)?error.code:'unclassified';
 if(errorCode==='unclassified'&&typeof error?.message==='string'){
  if(error.message==='owned operation deadline'||error.message==='owned operation cleanup failed: pending work did not settle')errorCode='timeout';
  else if(error.message==='synthetic callback failed')errorCode='callback';
  else if(error.message==='synthetic capacity IO error')errorCode='storage_io';
  else if(error.message.length<=4096){try{const value=JSON.parse(error.message);if(value&&errorCodes.has(value.code))errorCode=value.code;}catch{/* No raw error projection. */}}
 }
 const sourceCoordinate='runner.'+(phases.has(diagnosticPhase)?diagnosticPhase:'suite');
 return {vectorId,phase:phases.has(diagnosticPhase)?diagnosticPhase:'suite',errorCode,sourceCoordinate};
}
// End closed diagnostic projection.
const bounded=(promise,ms=25000)=>deadline(()=>promise,ms);
function durable(filename,raw){const fd=openSync(filename,'wx',0o600);try{writeFileSync(fd,raw);fsyncSync(fd);}finally{closeSync(fd);}assert.deepEqual(readFileSync(filename),Buffer.from(raw));}
function syncDir(dir){const fd=openSync(dir,'r');try{fsyncSync(fd);}finally{closeSync(fd);}}
function makeStore(dir,mode,chat,check=()=>{}){const stages=[];const scopeKey=scope=>hash(JSON.stringify(scope));return {
 stages,async admitFirstPage(input){diagnosticPhase='store_io';check();assert.ok(input.checkpointJsonBytes>0);assert.ok(input.scope.api_url);if(mode==='capacity-error')throw new Error('synthetic capacity IO error');return mode!=='capacity-false';},
 async generation(scope){diagnosticPhase='store_io';check();const pointer=path.join(dir,scopeKey(scope)+'.head');return existsSync(pointer)?readFileSync(pointer,'utf8'):null;},
 async compareAndSwap(input){diagnosticPhase='store_io';check();const key=scopeKey(input.scope),head=path.join(dir,key+'.head'),current=existsSync(head)?readFileSync(head,'utf8'):null;if(mode==='cas-refused'||current!==input.expectedVersion)return {stored:false};const checkpoint=JSON.parse(input.checkpointJson);assert.ok(!input.checkpointJson.includes('Synthetic first-page row'));assert.ok(!input.checkpointJson.includes('Fixture sender'));assert.ok(!stages.some(stage=>stage.id===input.nextVersion));const selected=checkpoint.selected_first_pages?.[chat],history=checkpoint.history?.[chat];if(selected){assert.equal(history,undefined);assert.equal(selected.messages.length,100);}else{assert.equal(history.length,140);}stages.push({id:input.nextVersion,purpose:selected?'first_page':'canonical'});const target=mkdtempSync(path.join(dir,key+'-'));durable(path.join(target,'checkpoint_json'),input.checkpointJson);durable(path.join(target,'credentials_json'),input.credentialsJson);syncDir(target);const digest=hash(readFileSync(path.join(target,'checkpoint_json')));assert.equal(digest,input.ciphertextSha256);const pointer=path.join(dir,key+'.head'),pending=pointer+'.pending';durable(pending,input.nextVersion);renameSync(pending,pointer);syncDir(dir);
 // Negative ACK vectors deliberately corrupt only the returned receipt, after real persistence.
 return {stored:true,ciphertext_sha256:mode==='wrong-hash'?'0'.repeat(64):mode==='wrong-purpose'?hash(readFileSync(path.join(target,'credentials_json'))):digest,credential_revision:input.credentialRevision+(mode==='wrong-revision'?1:0)};
 }};}
function logicalId(index,mode,chat){const uuid=`10000000-0000-4000-8000-${String(index).padStart(12,'0')}`;return mode==='composite'?chat.replaceAll('-','').slice(0,10)+'-'+uuid:mode==='opaque'?`legacy_msg_${String(index).padStart(4,'0')}`:uuid;}
function rows(value,start,end,mode,chat){assert.equal(value.chat.messages.length,end-start+1);for(let index=start;index<=end;index++){const row=value.chat.messages[index-start];assert.equal(row.id,logicalId(index,mode,chat));assert.equal(row.content,`Synthetic first-page row ${String(index).padStart(3,'0')} 雪`);assert.equal(row.role,index%2?'user':'assistant');assert.equal(row.sender,'Fixture sender');}}
function canonical(value,mode,chat){assert.equal(value.source,'canonical');assert.equal(value.cached,false);assert.equal(value.refreshing,false);assert.equal(value.history_complete,true);assert.equal(value.has_more_before,false);assert.equal(value.pii_restoration,'all_user_rows');rows(value,1,140,mode,chat);}
async function vector(suite,entry,fixture){
 diagnosticPhase='peer_start';
 const directory=mkdtempSync(path.join(tmpdir(),'openmates-first-page-npm-')),log=path.join(directory,'requests.jsonl'),idMode=entry.message_id_mode,mode=entry.mode;
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',[path.join(root,'tests/sdk-conformance/first_page_continuation_peer.py'),'--fixture',fixture,'--capability',CAP,'--request-log',log,'--identity','npm','--message-id-mode',idMode],{stdio:['ignore','pipe','ignore']});
 const lines=createInterface({input:peer.stdout});let client,nativeClient,termination,callbacks=0;const lease=createOwnership(),owner=lease.vector,controller=lease.read,check=lease.check;const owned=async operation=>{check();const value=await operation();check();return value;};const requests=()=>existsSync(log)?readFileSync(log,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];
 const latest=[{direction:'latest',limit:100}],full=[...latest,{direction:'before',limit:100,...(idMode==='uuid'?{}:{cursor_message_id:logicalId(41,idMode,suite.protocol.initial_chat_id)})}];
 return await runOwned(async()=>{
  const line=await bounded(lines[Symbol.asyncIterator]().next(),5000),endpoint=JSON.parse(line.value).endpoint;check();assert.ok(endpoint.startsWith('http://127.0.0.1:'));
  diagnosticPhase='client_setup';if(mode!=='stale-a-b')client=new SessionClient({apiUrl:endpoint,appUrl:suite.protocol.app_origin,privacy:{enhanced:false},allowPrivateOperations:true});
  const session={api_url:endpoint,session_id:suite.account.session_id,cookies:{auth_refresh_token:suite.account.cookie},ws_token:null,master_key:suite.account.master_key,hashed_email:'synthetic-email-hash',user_email_salt:'synthetic-salt',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null};if(client){diagnosticPhase='session_import';await owned(()=>client.importSession(session));diagnosticPhase='session_validate';await owned(()=>client.validateSession());}
  const chat=suite.protocol.initial_chat_id,store=makeStore(directory,mode,chat,check);
  const options={includeSecrets:true,includePrivateOutput:true,signal:controller.signal,onFirstPage:async page=>{diagnosticPhase='callback';callbacks++;assert.equal(page.kind,'first_page');assert.equal(page.source,'first_page');assert.equal(page.cached,true);assert.equal(page.refreshing,true);assert.equal(page.history_complete,false);assert.equal(page.has_more_before,true);assert.equal(page.pii_restoration,'page_local');rows(page,41,140,idMode,chat);assert.deepEqual(requests(),latest);await Promise.resolve();assert.deepEqual(requests(),latest);if(mode==='callback-failure')throw new Error('synthetic callback failed');if(['callback-cancel','stale-a-b'].includes(mode))controller.abort();}};
  if(mode==='no-secrets')options.includeSecrets=false;if(mode==='no-private')options.includePrivateOutput=false;
  if(mode==='stale-a-b'){
   diagnosticPhase='stale_a_b';
   const allowed=new Set(['linux-arm64','linux-x64','darwin-arm64','darwin-x64','win32-arm64','win32-x64']),platform=`${process.platform}-${process.arch}`;assert.ok(allowed.has(platform),'unsupported native platform');
   check();const {NativeSessionClient}=createRequire(import.meta.url)(path.join(root,'frontend/packages/openmates-cli/native',platform+'.node'));
   check();nativeClient=new NativeSessionClient(JSON.stringify({api_url:endpoint,app_url:suite.protocol.app_origin,enhanced_privacy:false,allow_private_operations:true}));
   await owned(()=>nativeClient.importSession(JSON.stringify(session)));await owned(()=>nativeClient.validateSession());
   const next=async id=>JSON.parse(await owned(()=>nativeClient.firstPageNext(id)));
   const persist=async stage=>{check();const receipt=await store.compareAndSwap({scope:stage.scope,expectedVersion:await store.generation(stage.scope),nextVersion:stage.id,checkpointJson:stage.checkpoint_json,credentialsJson:stage.credentials_json,ciphertextSha256:stage.ciphertext_sha256,credentialRevision:stage.credential_revision});assert.equal(receipt.stored,true);check();return JSON.stringify({ciphertext_sha256:receipt.ciphertext_sha256,credential_revision:receipt.credential_revision});};
   const a=JSON.parse(await owned(()=>nativeClient.firstPageOpen(chat,true,true))).id,capacity=await next(a);assert.equal(capacity.kind,'capacity');nativeClient.firstPageCapacity(a,capacity.id,true);const stageA=await next(a);assert.equal(stageA.source,'first_page');const receiptA=await persist(stageA);nativeClient.firstPageReceipt(a,stageA.id,receiptA);const page=await next(a);assert.equal(page.kind,'first_page');rows(page,41,140,idMode,chat);assert.deepEqual(requests(),latest);nativeClient.firstPageClose(a);
   const b=JSON.parse(await owned(()=>nativeClient.firstPageOpen(chat,true,true))).id,stageB=await next(b);assert.equal(stageB.kind,'stage');assert.equal(stageB.source,'cache_settled');const receiptB=await persist(stageB);
   // B is now awaiting its exact ACK. Exercise stale A against that live boundary.
   const conflict=error=>{try{return JSON.parse(error.message).code==='conflict';}catch{return error.code==='conflict';}};assert.throws(()=>nativeClient.firstPageClose(a),conflict);assert.throws(()=>nativeClient.firstPageReceipt(a,stageA.id,receiptA),conflict);assert.deepEqual(requests(),latest);
   nativeClient.firstPageReceipt(b,stageB.id,receiptB);const done=await next(b);assert.equal(done.kind,'completed');assert.equal(done.source,'cache_settled');assert.equal(done.cached,true);assert.equal(done.refreshing,false);assert.equal(done.history_complete,false);assert.equal(done.pii_restoration,'all_cached_user_rows');rows(done,41,140,idMode,chat);try{nativeClient.firstPageClose(b);}catch(error){assert.ok(conflict(error));}assert.deepEqual(requests(),latest);
  }else if(mode==='strict'){
   diagnosticPhase='strict';
   const stage=await owned(()=>client.cacheChatStage(chat,{includeSecrets:true}));check();const receipt=await store.compareAndSwap({scope:stage.scope,expectedVersion:await store.generation(stage.scope),nextVersion:stage.id,checkpointJson:stage.checkpoint_json,credentialsJson:stage.credentials_json,ciphertextSha256:stage.ciphertext_sha256,credentialRevision:stage.credential_revision});assert.equal(receipt.stored,true);canonical(await owned(()=>client.cacheChatCommit(stage.id,{ciphertext_sha256:receipt.ciphertext_sha256,credential_revision:receipt.credential_revision})),idMode,chat);assert.equal(callbacks,0);assert.deepEqual(requests(),full);
  }else if(['admit','warm','capacity-false'].includes(mode)){
   diagnosticPhase='continuation';
   canonical(await client.readChatWithFirstPage(chat,store,options),idMode,chat);assert.deepEqual(store.stages.map(stage=>stage.purpose),mode==='capacity-false'?['canonical']:['first_page','canonical']);assert.equal(callbacks,mode==='capacity-false'?0:1);assert.deepEqual(requests(),full);
   if(mode==='warm'){const settled=await client.readChatWithFirstPage(chat,store,{...options,onFirstPage:()=>{throw new Error('warm callback forbidden');}});assert.equal(settled.source,'cache_settled');assert.equal(settled.cached,true);assert.equal(settled.refreshing,false);assert.equal(settled.history_complete,false);assert.equal(settled.pii_restoration,'all_cached_user_rows');rows(settled,1,140,idMode,chat);assert.deepEqual(requests(),full);}
  }else if(['capacity-error','wrong-hash','wrong-revision','wrong-purpose','cas-refused','callback-failure','callback-cancel','no-secrets','no-private'].includes(mode)){
   diagnosticPhase='negative';
   const expectedCode=['wrong-hash','wrong-revision','wrong-purpose','cas-refused'].includes(mode)?'conflict':['no-secrets','no-private'].includes(mode)?'invalid_argument':['callback-cancel','stale-a-b'].includes(mode)?'cancelled':null;await assert.rejects(client.readChatWithFirstPage(chat,store,options),error=>expectedCode?error?.code===expectedCode:error?.message===(mode==='capacity-error'?'synthetic capacity IO error':'synthetic callback failed'));assert.equal(callbacks,['callback-failure','callback-cancel','stale-a-b'].includes(mode)?1:0);assert.deepEqual(requests(),['no-secrets','no-private'].includes(mode)?[]:latest);
   // Subsequent cache-only read proves callback errors/cancellation closed A without older IO.
   if(['callback-failure','callback-cancel'].includes(mode)){const settled=await client.readChatWithFirstPage(chat,makeStore(directory,'admit',chat,check),{includeSecrets:true,includePrivateOutput:true,onFirstPage:()=>{throw new Error('owned operation was not closed');}});assert.equal(settled.source,'cache_settled');rows(settled,41,140,idMode,chat);assert.deepEqual(requests(),latest);}
  }else throw new Error(`Unsupported first-page mode: ${mode}`);
  diagnosticPhase='vector_complete';return {id:entry.id,status:'passed'};
 },25000,()=>{lease.cancelAll();try{client?.cancel();}catch{}try{nativeClient?.cancel();}catch{}termination=terminateChild(peer).catch(error=>error);},async()=>{try{if(termination){const error=await termination;if(error instanceof Error)throw error;}await cleanupOwned({child:peer,close:async()=>{await client?.close();await nativeClient?.close();}});}finally{lines.close();rmSync(directory,{recursive:true,force:true});}});
}

async function main(){const args=process.argv.slice(2),get=name=>{assert.ok(args.includes(name));return args[args.indexOf(name)+1];};assert.equal(get('--capability'),CAP);const fixture=path.resolve(get('--fixture')),raw=readFileSync(fixture),suite=JSON.parse(raw).capabilities[CAP];assert.deepEqual(suite.vectors.map(({id,mode})=>[id,mode]),vectors);for(const entry of suite.vectors)assert.equal(entry.message_id_mode,entry.id==='cold-composite'?'composite':entry.id==='cold-opaque'?'opaque':'uuid');const results=[];for(const entry of suite.vectors){try{results.push(await vector(suite,entry,fixture));}catch(error){results.push({id:entry.id,status:'failed'});console.log(JSON.stringify({capability:CAP,language:'npm',status:'failed',fixtureSha256:hash(raw),results,diagnostic:closedDiagnostic(error,entry.id)}));process.exitCode=1;return;}}console.log(JSON.stringify({capability:CAP,language:'npm',status:'passed',fixtureSha256:hash(raw),results}));}
main().catch(()=>{console.error('First-page npm conformance failed before vector attribution.');process.exitCode=1;});
