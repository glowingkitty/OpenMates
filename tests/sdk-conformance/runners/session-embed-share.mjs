/** Actual NAPI Cookie namespace; only developer harness can spawn its coordinator. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')){
 const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/session-embed-share.py','--language','npm',...process.argv.slice(2)],{cwd:root,stdio:'inherit'});
 process.exitCode=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
}else{
 const {SessionClient,SessionClientError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
 const raw=readFileSync(0);assert.ok(raw.length<=1024*1024);const c=JSON.parse(raw);const url=new URL(c.endpoint);assert.equal(url.protocol,'http:');assert.equal(url.hostname,'127.0.0.1');assert.ok(url.port);assert.equal(url.pathname,'/');assert.equal(url.search,'');assert.equal(url.hash,'');assert.equal(url.username,'');assert.equal(url.password,'');
 const s=c.suite,v=c.vector;assert.equal(s.account.cookie,'synthetic-cookie');assert.equal(s.account.session_id,'synthetic-session');
 const client=new SessionClient({apiUrl:c.endpoint,appUrl:s.protocol.app_origin,privacy:{enhanced:false},allowPrivateOperations:v.mode!=='policy-denied'});
 try{
  if(v.mode!=='noauth')await client.importSession({api_url:c.endpoint,session_id:s.account.session_id,cookies:{auth_refresh_token:s.account.cookie},ws_token:null,master_key:v.mode==='wrong-key'?'AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI=':s.account.master_key,hashed_email:s.account.hashed_email,user_email_salt:'',email_encryption_key:null,created_at:1,paired_session_expires_at:v.mode==='paired-expired'?1:null,active_team_id:v.mode==='team'?s.protocol.team_id:null});
  let out;try{out={ok:true,value:await client.embeds.shareUrl(s.embed_id,v.expires,v.password)};}catch(error){assert.ok(error instanceof SessionClientError);out={ok:false,error:error.code};}console.log(JSON.stringify(out)); // sensitive-logging: allow - conformance runner result protocol on stdout; synthetic fixture data only
 }catch(error){assert.ok(error instanceof SessionClientError);console.log(JSON.stringify({ok:false,error:error.code}));}finally{await client.close();}
}
