/** PRIVATE UNRUN actual npm facade/NAPI shared cache settlement vectors. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync,mkdirSync,openSync,writeFileSync,readFileSync,fsyncSync,closeSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createInterface} from 'node:readline';
import {SessionClient} from '../../../frontend/packages/openmates-cli/dist/sdk-entry.js';
const CAP='session.cache-preferred-settlement.v1',root=path.resolve(import.meta.dirname,'../../..');
const hash=raw=>createHash('sha256').update(raw).digest('hex');
const bounded=(p,ms=25000)=>Promise.race([p,new Promise((_,reject)=>{const timer=setTimeout(()=>reject(new Error('bounded cache settlement')),ms);timer.unref();})]);
const refused=(p,codes)=>assert.rejects(p,error=>codes.includes(error?.code));
function syncDirectory(directory){const fd=openSync(directory,'r');try{fsyncSync(fd);}finally{closeSync(fd);}}
function ack(stage,directory,index){
 const target=path.join(directory,String(index));mkdirSync(target,{mode:0o700});
 for(const name of ['checkpoint_json','credentials_json']){const raw=Buffer.from(stage[name],'utf8'),filename=path.join(target,name),fd=openSync(filename,'wx',0o600);try{writeFileSync(fd,raw);fsyncSync(fd);}finally{closeSync(fd);}assert.deepEqual(readFileSync(filename),raw);}
 syncDirectory(target);const digest=hash(readFileSync(path.join(target,'checkpoint_json')));assert.equal(digest,stage.ciphertext_sha256);
 return {ciphertext_sha256:digest,credential_revision:stage.credential_revision};
}
function assertOwnedRows(chat){assert.equal(chat.messages.length,40);for(let offset=0;offset<40;offset++){const index=offset+1,row=chat.messages[offset];assert.equal(row.id,`10000000-0000-4000-8000-${String(index).padStart(12,'0')}`);assert.equal(row.content,`Synthetic cache row ${String(index).padStart(3,'0')} 雪`);assert.equal(row.role,index%2?'user':'assistant');assert.equal(row.sender,'Fixture sender');assert.equal(row.thinking,'');assert.deepEqual(row.embeds,[]);}}
function output(value,canonical=false){assert.equal(value.source,canonical?'canonical':'cache_settled');assert.equal(value.history_complete,canonical);assert.equal(value.cached,!canonical);assert.equal(value.refreshing,false);assert.equal(value.pii_restoration,canonical?'all_user_rows':'all_cached_user_rows');assert.ok(value.chat.messages.length);assertOwnedRows(value.chat);if(!canonical)assert.equal(value.has_more_before,null);}
async function vector(suite,entry,fixture){
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',[path.join(root,'tests/sdk-conformance/cache_settlement_peer.py'),'--fixture',fixture,'--capability',CAP,'--vector',entry.id,'--identity','npm'],{stdio:['ignore','pipe','ignore']});
 const lines=createInterface({input:peer.stdout});const directory=mkdtempSync(path.join(tmpdir(),'openmates-cache-sdk-'));let client,monitor;
 try{
  const line=await bounded(lines[Symbol.asyncIterator]().next(),5000);const endpoint=JSON.parse(line.value).endpoint;assert.ok(endpoint.startsWith('http://127.0.0.1:'));
  client=new SessionClient({apiUrl:endpoint,appUrl:suite.protocol.app_origin,privacy:{enhanced:false},allowPrivateOperations:true});
  await client.importSession({api_url:endpoint,session_id:suite.account.session_id,cookies:{auth_refresh_token:suite.account.cookie},ws_token:null,master_key:suite.account.master_key,hashed_email:'synthetic-email-hash',user_email_salt:'synthetic-salt',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null});
  await client.validateSession();const chat=suite.protocol.initial_chat_id;
  let stage=await client.cacheChatStage(chat,{includeSecrets:true});assert.equal(stage.source,'canonical');output(await client.cacheChatCommit(stage.id,ack(stage,directory,0)),true);
  const mode=entry.mode;
  if(mode==='explicit-consent')await refused(client.cacheChatStage(chat,{includeSecrets:false}),['invalid_argument']);
  else if(mode==='selected-denied'){const response=await fetch(endpoint+'/__test/control?action=deny',{signal:AbortSignal.timeout(2000)});assert.equal(response.status,200);await refused(client.cacheChatStage(chat,{includeSecrets:true}),['forbidden']);}
  else if(mode==='monitor-exact-ack'){
   monitor=await client.watchChats();await monitor.next();stage=await monitor.stageRefreshPreferCache({includeSecrets:true,selectedChatId:chat});
   const result=await monitor.commitRefresh(stage.id,ack(stage,directory,1));assert.equal(result.selection.kind,'cache_settled');assert.equal(result.selection.history_complete,false);assert.equal(result.selection.pii_restoration,'all_cached_user_rows');assertOwnedRows(result.selection.chat);
  }else{
   stage=await client.cacheChatStage(chat,{includeSecrets:true});assert.equal(stage.source,'cache_settled');let receipt=ack(stage,directory,1);
   if(mode.startsWith('selected-wrong-')){const wrong={...receipt};if(mode.endsWith('hash'))wrong.ciphertext_sha256='0'.repeat(64);else wrong.credential_revision+=1;await refused(client.cacheChatCommit(stage.id,wrong),['conflict']);}
   else if(mode==='stale-a-active-b'){const other=await client.cacheChatStage(chat,{includeSecrets:true});await refused(client.cacheChatCommit(stage.id,receipt),['cancelled']);stage=other;receipt=ack(other,directory,2);}
   else if(mode==='discarded-stage'){await client.cacheChatDiscard(stage.id);await refused(client.cacheChatCommit(stage.id,receipt),['conflict']);return {id:entry.id,status:'passed'};}
   output(await client.cacheChatCommit(stage.id,receipt));await refused(client.cacheChatCommit(stage.id,receipt),['conflict']);
  }
  return {id:entry.id,status:'passed'};
 }finally{
  try{await monitor?.close();await client?.close();}finally{lines.close();if(peer.exitCode===null){peer.kill('SIGTERM');await bounded(new Promise(resolve=>peer.once('exit',resolve)),2000).catch(()=>peer.kill('SIGKILL'));}rmSync(directory,{recursive:true,force:true});}
 }
}
async function main(){const args=process.argv.slice(2),get=name=>args[args.indexOf(name)+1];assert.equal(get('--capability'),CAP);const fixture=path.resolve(get('--fixture')),raw=readFileSync(fixture),suite=JSON.parse(raw).capabilities[CAP],results=[];for(const entry of suite.vectors)results.push(await bounded(vector(suite,entry,fixture)));console.log(JSON.stringify({capability:CAP,language:'npm',status:'passed',fixtureSha256:hash(raw),results}));}
main().catch(()=>{console.error('Cache settlement npm conformance failed');process.exitCode=1;});
