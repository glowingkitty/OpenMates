/** Actual public npm/NAPI watch facade against the independent shared peer. */
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFileSync,writeFileSync,openSync,fsyncSync,closeSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
const {SessionClient,SessionClientError,OpenMates}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
const CAPABILITY='session.project-task-watch.v1', DEADLINE=10000;
async function bounded(value){let timer;try{return await Promise.race([value,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('bounded fixture deadline')),DEADLINE);})]);}finally{clearTimeout(timer);}}
async function rejected(operation,codes){let error;try{await bounded(operation());}catch(caught){error=caught;}assert.ok(error,'operation unexpectedly accepted');assert.notEqual(error.message,'bounded fixture deadline');if(codes){if(!codes.includes('project_task_watch_unavailable'))assert.ok(error instanceof SessionClientError,'native typed SessionClientError');assert.ok(codes.includes(error.code),'typed refusal');}return error;}
const session=(suite,endpoint)=>({api_url:endpoint,session_id:suite.account.session_id,cookies:{auth_refresh_token:suite.account.cookie},ws_token:'synthetic-watch-ws',master_key:suite.account.master_key,hashed_email:'synthetic-email-hash',user_email_salt:'synthetic-salt',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null});
async function runVector(suite,vector,fixture){
 const process=spawn(globalThis.process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/session_project_task_watch_server.py','--fixture',fixture,'--vector',vector.id,'--identity','npm'],{cwd:ROOT,stdio:['ignore','pipe','ignore']});
 const lines=createInterface({input:process.stdout});
 const directory=mkdtempSync(join(tmpdir(),'sdk-watch-durable-'));
 const watches=new Map(),snapshots=new Map(),saved=new Map(),bindings=new Map();let client,endpoint,negativeSubscriptions=0;
 try{
  const ready=await bounded(new Promise((resolve,reject)=>{lines.once('line',line=>{try{resolve(JSON.parse(line));}catch{reject(new Error('fixture readiness'));}});process.once('error',()=>reject(new Error('fixture launch')));process.once('exit',()=>reject(new Error('fixture exited')));}));
  assert.match(ready.endpoint,/^http:\/\/127\.0\.0\.1:[1-9][0-9]*$/);endpoint=ready.endpoint;
  const scope=vector.team?{teamId:suite.team.team_id}:{personal:true};
  client=new SessionClient({apiUrl:endpoint,appUrl:'https://app.example.invalid',privacy:{enhanced:false},allowPrivateOperations:false});
  await client.importSession(session(suite,endpoint));
  async function rawControl(op,fields={}){const r=await bounded(fetch(endpoint+'/__test/control',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({op,...fields})}));assert.equal(r.status,200);const v=await r.json();assert.equal(v.failure,null);return v;}
  async function bind(name){const binding=bindings.get(name);assert.ok(binding,'pending logical binding');const status=await rawControl('beacon',{key:'subscriptions',minimum:0});if(status.active_generations.includes(binding.generation))return binding.generation;const after=binding.generation??binding.after;const report=await rawControl('bind_watch',{watch:name,after,source_id:suite.source_id});assert.equal(report.source_id,suite.source_id);assert.equal(report.project_id,suite.project_id);assert.ok(Number.isInteger(report.generation)&&report.generation>after);binding.generation=report.generation;return report.generation;}
  async function bindPending(){for(const [name,binding] of bindings)if(binding.generation===undefined)await bind(name);}
  async function control(op,fields={}){if(fields.watch!==undefined){let generation;if(['closed','late_force_logout'].includes(op)){generation=bindings.get(fields.watch)?.generation;assert.ok(Number.isInteger(generation),'observed prior connection required');}else generation=await bind(fields.watch);fields={...fields,generation};}return rawControl(op,fields);}
  async function open(name,checkpoint){await bindPending();const report=await rawControl('beacon',{key:'subscriptions',minimum:0});const watch=await client.projects.watchTasks(suite.project_id,{sourceId:suite.source_id,...(checkpoint?{checkpoint}:{})},scope);watches.set(name,watch);bindings.set(name,{after:report.subscriptions});}
  async function event(name,target,terminal=false){for(let i=0;i<32;i++){let result;try{result=await bounded(watches.get(name).next());}catch(error){if((terminal||target==='refused')&&['cancelled','forbidden','expired'].includes(error.code)){if(bindings.get(name)?.generation===undefined)bindings.delete(name);return {kind:'state',state:'closed'};}throw error;}assert.equal(result.done,false);const v=result.value;assert.ok(['snapshot','state'].includes(v.kind));if(terminal){assert.notEqual(v.kind,'snapshot','stale plaintext after terminal control');if(['revoked','expired','closed','failed'].includes(v.state)){if(bindings.get(name)?.generation===undefined)bindings.delete(name);return v;}}else if(target==='refused'&&v.kind==='state'&&['reconnecting','failed','revoked','expired','closed'].includes(v.state))return v;else if(v.kind===target||v.state===target)return v;else assert.ok(!['revoked','expired','closed','failed'].includes(v.state),'unexpected terminal');}assert.fail('bounded state transitions');}
  function checkSnapshot(name,value,count,cursor){assert.equal(value.cursor,cursor);assert.equal(value.tasks.length,count);assert.deepEqual(value.scope,{api_url:endpoint,account_id:suite.owner_id,workspace:vector.team?{team:suite.team.team_id}:'personal',project_id:suite.project_id,source_id:suite.source_id});assert.equal(new Set(value.tasks.map(r=>r.task_id)).size,count);assert.deepEqual(value.tasks.map(r=>Number(BigInt('0x'+r.task_id.replaceAll('-','')))).sort((a,b)=>a-b),Array.from({length:count},(_,i)=>i+(cursor==='epoch:2'?2:1)));for(const row of value.tasks){const index=Number(BigInt('0x'+row.task_id.replaceAll('-','')))-1;assert.equal(row.task.title,`Synthetic watch Task ${index}`);assert.equal(row.task.description,'Synthetic private description');assert.equal('encrypted_title'in row.task,false);}assert.equal(value.checkpoint.cursor,cursor);assert.deepEqual(value.checkpoint.scope,value.scope);assert.equal(value.checkpoint.tasks.length,count);assert.ok(value.checkpoint.tasks.every(r=>r.opaque_fixture_metadata?.preserved===true));assert.equal(JSON.stringify(value.checkpoint).includes('Synthetic watch Task'),false);snapshots.set(name,value);}
  async function execute(s){const name=s.watch??'a',watch=watches.get(name);switch(s.op){
   case 'open':await open(name,s.checkpoint?structuredClone(snapshots.get(s.checkpoint).checkpoint):undefined);break;
   case 'send':case 'beacon':case 'closed':case 'drop':case 'revoke':case 'force_logout':case 'late_force_logout':case 'ttl_elapsed':case 'hold_upgrade':case 'release_upgrade':case 'deny_source':case 'rotate':case 'idle_flood':{const {op,...fields}=s;await control(op,fields);break;}
   case 'multipart_snapshot':{const pending=event(name,'snapshot');let timer;try{const early=await Promise.race([pending.then(()=>true),new Promise(resolve=>{timer=setTimeout(()=>resolve(false),100);})]);assert.equal(early,false,'partial multipart publication');}finally{clearTimeout(timer);}await control('send',{watch:name,kind:'final'});checkSnapshot(name,await bounded(pending),s.count,s.cursor);break;}
   case 'reject_current_commit':await rejected(()=>watch.commit(snapshots.get(name).receipt),['conflict']);break;
   case 'snapshot':checkSnapshot(name,await event(name,'snapshot'),s.count,s.cursor);break;
   case 'state':{const v=await event(name,s.state);assert.equal(v.state,s.state);assert.equal(v.cursor,snapshots.get(name).receipt.cursor);break;}
   case 'terminal':await event(name,'',true);break;
   case 'commit':{const checkpoint=snapshots.get(name).checkpoint;const path=join(directory,name+'.json');writeFileSync(path,JSON.stringify(checkpoint),{mode:0o600});const fd=openSync(path,'r');try{fsyncSync(fd);}finally{closeSync(fd);}const directoryFd=openSync(directory,'r');try{fsyncSync(directoryFd);}finally{closeSync(directoryFd);}assert.deepEqual(JSON.parse(readFileSync(path)),checkpoint);await bounded(watch.commit(snapshots.get(name).receipt));break;}
   case 'reject_commit':for(const bad of [{...snapshots.get(name).receipt,batch_id:'wrong'},{...snapshots.get(name).receipt,cursor:'epoch:999'}])await rejected(()=>watch.commit(bad),['conflict']);break;
   case 'reject_expired_commit':await rejected(()=>watch.commit(snapshots.get(name).receipt),['expired','cancelled','conflict']);break;
   case 'set_team':await bindPending();await client.setTeam(suite.team.team_id);break;
   case 'close_client':await bindPending();await client.close();break;
   case 'save_receipt':saved.set(name,structuredClone(snapshots.get(name).receipt));break;
   case 'reject_saved_commit':await rejected(()=>watch.commit(saved.get(name)),['conflict']);break;
   case 'assert_resume':assert.equal((await control('beacon',{key:'subscriptions',minimum:1})).resumes.at(-1),s.cursor);break;
   case 'ordinary_read':assert.deepEqual(await bounded(client.projects.list(scope)),[]);break;
   case 'close':await bounded(watch.close());if(bindings.get(name)?.generation===undefined)bindings.delete(name);break;
   case 'iterator_close':await bounded(watch.return());assert.equal((await watch.next()).done,true);break;
   case 'close_pending':{const p=watch.next();assert.deepEqual(await bounded(client.projects.list(scope)),[]);await watch.close();const result=await bounded(p);assert.ok(result.done||(result.value.kind==='state'&&result.value.state==='closed'));break;}
   case 'reset':await bindPending();await bounded(client.importSession(session(suite,endpoint)));break;
   case 'assert_session':assert.equal((await client.exportSession({includeSecrets:true})).session.session_id,suite.account.session_id);break;
   case 'assert_logged_out':await rejected(()=>client.exportSession({includeSecrets:true}),['authentication']);break;
   case 'assert_rotation':assert.equal((await client.exportSession({includeSecrets:true})).session.cookies.auth_refresh_token,'synthetic-watch-rotated');break;
   case 'tampered_checkpoint':for(const kind of ['source','ciphertext']){const cp=structuredClone(snapshots.get('a').checkpoint);if(kind==='source')cp.scope.source_id='foreign-source';else cp.tasks[0].encrypted_title='invalid-ciphertext';await open('bad',cp);await event('bad','',true);}break;
   case 'negative_scope':for(const kind of ['owner','project','team','ciphertext','expired']){await open('a');await control('beacon',{key:'subscriptions',minimum:++negativeSubscriptions});await control('send',{watch:'a',kind:'bad-'+kind});await event('a','refused');await watches.get('a').close();await control('closed',{watch:'a'});}break;
   case 'cap':for(let i=0;i<16;i++)await open(String(i));await control('beacon',{key:'subscriptions',minimum:16});await rejected(()=>open('excess'),['conflict']);await watches.get('0').close();await open('replacement');break;
   case 'busy_finish':{await control('hold_list');const pending=client.projects.list(scope);await control('beacon',{key:'list_entered',minimum:1});await control('send',{watch:'a',kind:'baseline'});await event('a','reconnecting');await control('release_list');assert.deepEqual(await bounded(pending),[]);break;}
   case 'commit_flood_close':{await rejected(()=>watch.commit({batch_id:'wrong',cursor:'epoch:999'}),['conflict']);const pending=Array.from({length:32},()=>watch.commit({batch_id:'wrong',cursor:'epoch:999'}).then(()=>({accepted:true}),error=>({error})));assert.deepEqual(await bounded(client.projects.list(scope)),[]);await watch.close();const results=await bounded(Promise.all(pending));assert.ok(results.every(x=>x.error instanceof SessionClientError&&['conflict','cancelled'].includes(x.error.code)),'typed concurrent commit/close outcomes');assert.deepEqual(await bounded(client.projects.list(scope)),[]);break;}
   case 'api_key_refusal':{const api=new OpenMates({apiKey:'sk-api-syntheticwatch',apiUrl:endpoint,deviceId:'synthetic-watch-device'});const error=await rejected(()=>api.projects.watchTasks(suite.project_id,{sourceId:suite.source_id},{personal:true}),['project_task_watch_unavailable']);assert.equal(error.reason,'PROJECT_TASK_WATCH_REQUIRES_COOKIE_SESSION');break;}
   default:assert.fail('unrecognized fixed fixture action');
  }}
  for(const step of vector.steps)await bounded(execute(step));
  const report=await bounded(fetch(endpoint+'/__test/status').then(r=>r.json()));assert.equal(report.failure,null);assert.equal(report.client_messages,0);if(vector.id==='api-key-refusal-before-transport'){assert.equal(report.requests,0);assert.equal(report.upgrades,0);}
  return {id:vector.id,status:'passed'};
 }finally{for(const watch of watches.values())await watch.close();if(client)await client.close();lines.close();if(process.exitCode===null&&process.signalCode===null){const stopped=new Promise(resolve=>process.once('exit',resolve));process.kill('SIGTERM');await bounded(stopped);}rmSync(directory,{recursive:true,force:true});}
}
const args=process.argv.slice(2),option=name=>{const i=args.indexOf(name);assert.ok(i>=0&&args[i+1]);return args[i+1];};
assert.equal(option('--capability'),CAPABILITY);const fixture=option('--fixture'),raw=readFileSync(fixture),suite=JSON.parse(raw).capabilities[CAPABILITY];
const results=[];for(const vector of suite.vectors)results.push(await runVector(suite,vector,fixture));
console.log(JSON.stringify({capability:CAPABILITY,language:'npm',status:'passed',fixtureSha256:createHash('sha256').update(raw).digest('hex'),results}));
