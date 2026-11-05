/** Actual NAPI SessionClient draft calls; developer harness only, no CLI. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')){
  const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/session-drafts.py','--language','npm',...process.argv.slice(2)],{cwd:root,stdio:'inherit'});
  process.exitCode=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
}else{
  const {SessionClient,SessionClientError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
  const bytes=readFileSync(0);assert.ok(bytes.length<=1024*1024);const c=JSON.parse(bytes);const url=new URL(c.endpoint);assert.equal(url.protocol,'http:');assert.equal(url.hostname,'127.0.0.1');assert.ok(url.port);assert.equal(url.pathname,'/');assert.equal(url.search,'');assert.equal(url.hash,'');assert.equal(url.username,'');assert.equal(url.password,'');assert.equal(c.suite.account.cookie,'synthetic-cookie');assert.equal(c.suite.account.session_id,'synthetic-session');
  const {suite,vector:v}=c;const client=new SessionClient({apiUrl:c.endpoint,appUrl:suite.protocol.app_origin,privacy:{enhanced:false},allowPrivateOperations:v.mode!=='policy-denied'});
  try{
    if(v.mode!=='noauth')await client.importSession({api_url:c.endpoint,session_id:suite.account.session_id,cookies:{auth_refresh_token:suite.account.cookie},ws_token:null,master_key:v.mode==='wrong-key'?Buffer.alloc(32,2).toString('base64'):suite.account.master_key,hashed_email:suite.account.hashed_email,user_email_salt:'',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:v.mode==='team'?suite.protocol.team_id:null});
    if(v.preflight_get)assert.deepEqual(await client.drafts.get(suite.protocol.chat_id,{refresh:true}),suite.records.base);
    let output;
    try{const options={refresh:v.options.force_refresh};const value=v.operation==='cached-list'?await client.drafts.cachedList():v.operation==='list'?await client.drafts.list(options):v.operation==='get'?await client.drafts.get(suite.protocol.chat_id,options):await client.drafts.sync();output={ok:true,value};}
    catch(error){assert.ok(error instanceof SessionClientError);output={ok:false,error:error.code};}
    console.log(JSON.stringify(output));
  }finally{await client.close();}
}
