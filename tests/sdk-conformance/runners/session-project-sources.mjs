/** PRIVATE UNRUN: actual public npm/NAPI source APIs, independent HTTP peer. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
const {SessionClient,SessionClientError,OpenMates}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
const {RustApiKeyClient,RustApiKeyClientError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-session-v1-entry.js');
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
const CAPABILITY='session.project-source-authoring.v1', DEADLINE=12000, VECTOR_DEADLINE=60000;
// Pure deadline/cleanup helpers: tests extract this block without loading any SDK.
async function bounded(value, expires=Date.now()+DEADLINE){let timer;try{return await Promise.race([value,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('fixture deadline')),Math.max(0,Math.min(DEADLINE,expires-Date.now())));})]);}finally{clearTimeout(timer);}}
async function controlJson(endpoint,command,expires){
 const controller=new AbortController();
 try{return await bounded((async()=>{const response=await fetch(endpoint+(command?'/__test/control':'/__test/status'),{...(command?{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(command)}:{}),signal:controller.signal});assert.equal(response.status,200);const report=await response.json();assert.equal(report.failure,null,'peer rejected source protocol');return report;})(),expires);}
 finally{controller.abort();}
}
async function stopPeer(peer,graceMs=1000){
 if(!peer.pid||peer.exitCode!==null||peer.signalCode!==null)return;
 const stopped=new Promise(resolve=>peer.once('exit',resolve));
 peer.kill('SIGTERM');
 try{await bounded(stopped,Date.now()+graceMs);}catch{peer.kill('SIGKILL');await bounded(stopped,Date.now()+graceMs);}
}
// End pure deadline/cleanup helpers.
function camelOuter(input){const names={source_id:'sourceId',source_type:'sourceType',display_name:'displayName',created_at:'createdAt',updated_at:'updatedAt',last_indexed_at:'lastIndexedAt'};return Object.fromEntries(Object.entries(input).map(([key,value])=>[names[key]??key,value]));}
function session(suite,endpoint){return {api_url:endpoint,session_id:suite.account.session_id,cookies:{auth_refresh_token:suite.account.cookie},ws_token:null,master_key:suite.account.master_key,hashed_email:'synthetic-source-email',user_email_salt:'synthetic-salt',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null};}
async function refused(operation,code,apiKey=false){let caught;try{await bounded(operation());}catch(error){caught=error;}assert.ok(caught,'source operation unexpectedly accepted');assert.equal(caught.code,code,'exact typed source error');if(apiKey)assert.equal(caught.reason,'PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION');else assert.ok(caught instanceof SessionClientError,'native typed source error');}
async function readRefused(operation,code,apiKey){
 let caught;try{await bounded(operation());}catch(error){caught=error;}
 assert.ok(caught,'read unexpectedly accepted');assert.equal(caught.code,code,'exact typed read error');
 assert.ok(caught instanceof (apiKey?RustApiKeyClientError:SessionClientError),'actual native typed read error');
}
async function runVector(suite,vector,fixture){
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/session_project_sources_server.py','--fixture',fixture,'--vector',vector.id,'--identity','npm'],{cwd:ROOT,stdio:['ignore','pipe','ignore']});
 const expires=Date.now()+VECTOR_DEADLINE,wait=value=>bounded(value,expires);
 const lines=createInterface({input:peer.stdout});let client,readApi,primary,endpoint,currentIndex=-1,currentOperation='setup';
 try{
  const ready=await wait(new Promise((resolve,reject)=>{lines.once('line',line=>{try{resolve(JSON.parse(line));}catch{reject(new Error('fixture readiness'));}});peer.once('error',()=>reject(new Error('fixture launch')));peer.once('exit',()=>reject(new Error('fixture exited')));}));
  assert.match(ready.endpoint,/^http:\/\/127\.0\.0\.1:[1-9][0-9]*$/);
  endpoint=ready.endpoint;
  const control=command=>controlJson(endpoint,command,expires);
  if(vector.mode!=='read-api-key'){
   client=new SessionClient({apiUrl:endpoint,appUrl:'https://app.example.invalid',privacy:{enhanced:false},allowPrivateOperations:false});
   const imported=session(suite,endpoint);
   if(vector.mode==='read-unrelated-master')imported.master_key='KioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKio=';
   if(vector.mode==='expired'||vector.mode==='read-expired')imported.paired_session_expires_at=Date.now()+2000;
   await wait(client.importSession(imported));await wait(client.setTeam(suite.team.team_id));
   if(vector.mode==='expired'||vector.mode==='read-expired')await control({op:'await_expiry',deadline_ms:imported.paired_session_expires_at});
  }else readApi=new RustApiKeyClient({apiKey:'sk-api-syntheticsources',apiUrl:endpoint,deviceId:'synthetic-source-device',privacy:{enhanced:false},allowPrivateOperations:true});
  const scope=vector.team?{teamId:suite.team.team_id}:{personal:true};
  const api=vector.mode==='api-key'?new OpenMates({apiKey:'sk-api-syntheticsources',apiUrl:endpoint,deviceId:'synthetic-source-device'}):undefined;
  for(const [index,item] of vector.cases.entries()){currentIndex=index;currentOperation=['create','patch','list-raw','list-names'].includes(item.operation)?item.operation:'invalid';
   await control({op:'case',index});const before=await control();const service=api?.projects??client?.projects;
   const isRead=item.operation==='list-raw'||item.operation==='list-names';
   const operation=()=>item.operation==='list-raw'?(readApi?readApi.listProjectSourcesRaw(suite.project_id,scope):service.listSourcesRaw(suite.project_id,scope)):item.operation==='list-names'?service.listSourcesDecodedNames(suite.project_id,scope):item.operation==='create'?service.createSource(suite.project_id,camelOuter(item.input),scope):service.updateSourceCapabilities(suite.project_id,item.source_id,camelOuter(item.input),scope);
   if(isRead){
    if(vector.mode==='read-cancel'&&index===0){const observed=operation().then(value=>({ok:true,value}),error=>({ok:false,error}));await control({op:'entered'});client.cancel();await control({op:'release'});const outcome=await wait(observed);assert.equal(outcome.ok,false,'accepted source read cancel rejects');await wait(readRefused(()=>Promise.reject(outcome.error),'cancelled',false));}
    else if(item.expected_error)await wait(readRefused(operation,item.expected_error,!!readApi));
    else assert.deepEqual(await wait(operation()),item.expected,'exact raw rows or name-only DTO, including unknown metadata');
   }else if(api)await wait(refused(operation,'project_source_authoring_unavailable',true));
   else if(vector.mode==='cancel'&&index===0){const observed=operation().then(value=>({ok:true,value}),error=>({ok:false,error}));await control({op:'entered'});client.cancel();await control({op:'release'});const outcome=await wait(observed);assert.equal(outcome.ok,false,'accepted source cancel must reject');await wait(refused(()=>Promise.reject(outcome.error),'cancelled'));}
   else if(item.expected_error)await wait(refused(operation,item.expected_error));
   else {const expected=item.operation==='create'?item.input:{...structuredClone(suite.seed),source_id:item.source_id,...item.input};assert.deepEqual(await wait(operation()),expected,'exact full arbitrary metadata/source DTO');}
   const after=await control();assert.equal(after.mutation_attempts-before.mutation_attempts,api?0:item.expected_mutation_attempts,'exact attempts/no retry');
   if(isRead){
    for(const [field,expected]of [['source_reads',item.expected_read_attempts],['project_reads',item.expected_project_attempts],['team_reads',item.expected_team_attempts]])assert.equal(after[field]-before[field],expected,'exact read attempts/no extra resolve');
    if(readApi){assert.equal(after.project_reads-before.project_reads,0,'API-key raw never resolves Project');assert.equal(after.team_reads-before.team_reads,0,'API-key raw never unwraps Team');}
   }
   if(item.zero_transport)assert.equal(after.requests,before.requests,'zero transport refusal');
   if(after.requests>before.requests&&!readApi){const exported=await wait(client.exportSession({includeSecrets:true}));assert.equal(exported.session.cookies.auth_refresh_token,after.cookie,'retain final rotated credential on failure/cancel');assert.equal(exported.session.active_team_id,suite.team.team_id,'source operation never changes selected Team');}
  }
  return {id:vector.id,status:'passed'};
 }catch(error){primary=error;const id=/^[a-z0-9-]{1,80}$/.test(vector.id)?vector.id:'invalid';process.stderr.write(`source_phase_failed:${id}:${currentIndex}:${currentOperation}\n`);throw error;}
 finally{
  const failures=[];
  try{if(endpoint)await controlJson(endpoint,{op:'release'},Date.now()+1000);}catch(error){failures.push(error);process.stderr.write('source_fixture_cleanup_failed:release\n');}
  try{if(client)await bounded(client.close(),Date.now()+1000);if(readApi)readApi.close();}catch(error){failures.push(error);process.stderr.write('source_fixture_cleanup_failed:client\n');}
  try{lines.close();await stopPeer(peer);}catch(error){failures.push(error);process.stderr.write('source_fixture_cleanup_failed:peer\n');}
  if(!primary&&failures.length)throw failures[0];
 }
}
const args=process.argv.slice(2),option=name=>{const i=args.indexOf(name);assert.ok(i>=0&&args[i+1]);return args[i+1];};
try{assert.equal(option('--capability'),CAPABILITY);const fixture=option('--fixture'),raw=readFileSync(fixture),suite=JSON.parse(raw).capabilities[CAPABILITY];assert.ok(suite.vectors.length>0);assert.equal(new Set(suite.vectors.map(v=>v.id)).size,suite.vectors.length);const results=[];for(const vector of suite.vectors){try{results.push(await runVector(suite,vector,fixture));}catch(error){const id=/^[a-z0-9-]{1,80}$/.test(vector.id)?vector.id:'invalid';const code=typeof error?.code==='string'&&/^[a-zA-Z_0-9]+$/.test(error.code)?error.code:'assertion_or_protocol';process.stderr.write(`source_case_failed:${id}:${code}\n`);throw error;}}console.log(JSON.stringify({capability:CAPABILITY,language:'npm',status:'passed',fixtureSha256:createHash('sha256').update(raw).digest('hex'),results}));}catch{process.stderr.write('npm Project source conformance failed\n');process.exitCode=1;}
