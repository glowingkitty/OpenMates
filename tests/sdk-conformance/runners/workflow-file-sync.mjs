/** AUTHORED UNRUN actual direct NAPI API; only this harness spawns coordinator. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')){
 const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/workflow-file-sync.py','--language','npm',...process.argv.slice(2)],{cwd:root,stdio:'inherit'});
 process.exitCode=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
}else{
 const {SessionClient,SessionClientError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
 const raw=readFileSync(0);assert.ok(raw.length<=1024*1024);const c=JSON.parse(raw),s=c.suite,v=c.vector;const u=new URL(c.endpoint);assert.equal(u.protocol,'http:');assert.equal(u.hostname,'127.0.0.1');assert.ok(u.port);assert.equal(u.pathname,'/');assert.equal(u.search,'');assert.equal(u.hash,'');assert.equal(u.username,'');assert.equal(u.password,'');assert.equal(s.account.cookie,'synthetic-cookie');assert.equal(s.account.session_id,'synthetic-session');
 const client=new SessionClient({apiUrl:c.endpoint,appUrl:s.app_origin,privacy:{enhanced:false},allowPrivateOperations:v.mode!=='policy-denied'});
 try{
  if(v.mode!=='noauth')await client.importSession({api_url:c.endpoint,session_id:s.account.session_id,cookies:{auth_refresh_token:s.account.cookie},ws_token:null,master_key:v.mode==='wrong-master'?'AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI=':s.account.master_key,hashed_email:s.account.hashed_email,user_email_salt:'',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null});
  const pending=client.projects.syncWorkflowFiles(s.workflow_id,s.expected_version,{approvedPaths:v.approved_paths??[s.path]},{personal:true,...(v.mode==='bad-scope'?{teamId:s.team_id}:{})});
  // Attach a rejection observer before the held fixture control awaits.
  pending.catch(()=>{});
  if(v.mode==='cancel-held'){
   const deadline=Date.now()+5000;while(!(await (await fetch(c.endpoint+'/__test/status')).json()).blocked){assert.ok(Date.now()<deadline);await new Promise(r=>setTimeout(r,20));}
   client.cancel();await fetch(c.endpoint+'/__test/release',{method:'POST',body:'{}'});
  }
  try{console.log(JSON.stringify({ok:true,value:await pending}));}catch(error){assert.ok(error instanceof SessionClientError);console.log(JSON.stringify({ok:false,error:error.code}));}
 }finally{await client.close();}
}
