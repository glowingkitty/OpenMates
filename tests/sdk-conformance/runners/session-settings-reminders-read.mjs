/** Actual public npm v1 Account read; source-only authored, execution requires isolated CI. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
const {SessionClient,SessionSettingsReadError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-session-v1-entry.js');
const ROOT=fileURLToPath(new URL('../../../',import.meta.url)),CAPABILITY='session.settings-reminders-read',DEADLINE=75000;
async function bounded(value,ms=DEADLINE){let timer;try{return await Promise.race([value,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('settings fixture deadline')),ms);})]);}finally{clearTimeout(timer);}}
function session(endpoint){return {api_url:endpoint,session_id:'synthetic-settings-session',cookies:{auth_refresh_token:'fixture'},ws_token:null,master_key:'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',hashed_email:'synthetic',user_email_salt:'',email_encryption_key:null,created_at:0,paired_session_expires_at:null,active_team_id:'00000000-0000-4000-8000-000000000001'};}
async function status(endpoint,phase="status"){const controller=new AbortController();try{return await bounded((async()=>{const response=await fetch(endpoint+'/__test/'+phase,{...(phase==='release'?{method:'POST'}:{}),signal:controller.signal});assert.equal(response.status,200);return response.json();})(),2000);}finally{controller.abort();}}
async function stop(peer){if(!peer.pid||peer.exitCode!==null||peer.signalCode!==null)return;const exited=new Promise(resolve=>peer.once('exit',resolve));peer.kill('SIGTERM');try{await bounded(exited,2000);}catch{peer.kill('SIGKILL');await bounded(exited,2000);}}
async function runCase(item,fixture){
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/session_settings_reminders_server.py','--fixture',fixture,'--case',item.id,'--identity','npm'],{cwd:ROOT,stdio:['ignore','pipe','ignore']});
 const lines=createInterface({input:peer.stdout});let client,endpoint,primary;
 try{
  const ready=await bounded(new Promise((resolve,reject)=>{lines.once('line',line=>{try{resolve(JSON.parse(line));}catch{reject(new Error('invalid fixture readiness'));}});peer.once('error',()=>reject(new Error('fixture launch failed')));peer.once('exit',()=>reject(new Error('fixture exited')));}),2000);
  assert.match(ready.endpoint,/^http:\/\/127\.0\.0\.1:[1-9][0-9]*$/);endpoint=ready.endpoint;
  client=new SessionClient({apiUrl:endpoint,appUrl:'https://app.example.invalid',privacy:{enhanced:false},allowPrivateOperations:false});
  if(item.session)await bounded(client.importSession(session(endpoint)),2000);
  let value,error;try{
   if(item.action==='cancel_body'||item.action==='cancel_retry'){
    const controller=new AbortController();
    const pending=client.account.reminders({signal:controller.signal}).then(value=>({value}),error=>({error}));
    const entered=await status(endpoint,'entered');assert.equal(entered.failure,null);assert.equal(entered.requests,1);
    controller.abort();await status(endpoint,'release');const outcome=await bounded(pending);value=outcome.value;error=outcome.error;
   }else value=await bounded(client.account.reminders());
  }catch(caught){error=caught;}
  const expected=item.expected;
  if(expected.ok){
   assert.equal(error,undefined,'successful raw read');assert.deepEqual(value,expected.value,'complete raw JSON, including scalar/null and unknown encrypted fields');
   if(Object.hasOwn(expected,'root_keys')){
    assert.ok(value!==null&&typeof value==='object'&&!Array.isArray(value));
    const serialized=JSON.stringify(value);
    assert.equal(serialized,expected.serialized_json,'exact public serialized JSON including root order and Unicode');
    assert.deepEqual(Object.keys(value),expected.root_keys,'public root Object.keys ordering');
    const ordered=Object.fromEntries(expected.root_keys.map(key=>[key,value[key]]));
    assert.equal(serialized,JSON.stringify(ordered),'actual public raw serialization retains the expected root order');
   }
  }
  else{assert.ok(error instanceof SessionSettingsReadError,'actual native typed settings failure');assert.equal(error.code,expected.error.toLowerCase());assert.equal(error.httpStatus,expected.http_status);if(Object.hasOwn(expected,'message'))assert.equal(error.message,expected.message,'exact typed settings refusal message');if(expected.http_status!==null)assert.equal(error.message,`Settings GET failed with HTTP ${expected.http_status}`);}
  const observed=await status(endpoint);assert.equal(observed.failure,null,'independent peer accepted exact wire protocol');assert.equal(observed.requests,expected.requests,'exact one retry or original refusal/no extra request');
  if(expected.wait_ms.length){assert.equal(observed.times_ns.length,2);assert.ok((observed.times_ns[1]-observed.times_ns[0])/1e6>=61000,'production61secondretry, no foreign clock override');}
  if(item.id==='cookie-rotation-malformed-body'||item.id==='one-429-retry-cookie-preserved'||item.action==='cancel_body'){const exported=await bounded(client.exportSession({includeSecrets:true}),2000);assert.equal(exported.session.cookies.auth_refresh_token,'rotated','canonical rotated cookie persists before decode');}
  if(item.id==='expired-malformed-body'||item.id==='owner-denial'){await assert.rejects(()=>client.exportSession({includeSecrets:true}),error=>error.code==='authentication','canonical credential revocation persists');}
  return {id:item.id,status:'passed'};
 }catch(error){primary=error;throw error;}
 finally{
  const failures=[];try{if(endpoint)await status(endpoint,'release');}catch(error){failures.push(error);}try{if(client)await bounded(client.close(),2000);}catch(error){failures.push(error);}
  try{if(endpoint){const last=await status(endpoint);assert.equal(last.failure,null);assert.equal(last.requests,item.expected.requests);}}catch(error){failures.push(error);}
  try{lines.close();await stop(peer);}catch(error){failures.push(error);}
  if(!primary&&failures.length)throw failures[0];
 }
}
const args=process.argv.slice(2),option=name=>{const i=args.indexOf(name);assert.ok(i>=0&&args[i+1]);return args[i+1];};
try{
 assert.equal(option('--capability'),CAPABILITY);const fixture=option('--fixture'),raw=readFileSync(fixture);assert.ok(raw.length<=1024*1024);const suite=JSON.parse(raw);assert.equal(suite.capability,CAPABILITY);assert.deepEqual(suite.retry,{only_status:429,max_retries:1,delay_ms:61000});assert.equal(suite.cases.length,28,'complete shared V4 fixture required');assert.equal(new Set(suite.cases.map(x=>x.id)).size,suite.cases.length);
 const results=[];for(const item of suite.cases){assert.match(item.id,/^[a-z0-9-]{1,80}$/);results.push(await runCase(item,fixture));}
 console.log(JSON.stringify({capability:CAPABILITY,language:'npm',status:'passed',fixtureSha256:createHash('sha256').update(raw).digest('hex'),results}));
}catch{process.stderr.write('npm settings reminders conformance failed\n');process.exitCode=1;}
