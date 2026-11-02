/** Genuine NAPI Cookie SDK plus maintained explicit API-key SDK. */
// contract-test-file: tooling
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
// BEGIN CLOSED APPS DIAGNOSTIC
const APPS_DIAGNOSTIC_STAGES=Object.freeze(['public_sdk_import','arguments','fixture_read','fixture_decode','vector_admission','peer_spawn','peer_ready','endpoint_assert','api_key_constructor','api_key_run','api_key_result','session_constructor','session_import_explicit','queued_prepare','queued_successor_prepare','queued_release_assert','queued_invalidate','dispatch_call','dispatch_barrier','dispatch_cancel','expected_refusal','cookie_run','cookie_result','session_export','session_export_assert','peer_report','peer_report_assert','cleanup_release','cleanup_session','cleanup_peer','result_count','emit_result','unclassified']);
const APPS_DIAGNOSTIC_VECTORS=Object.freeze(["cookie-sync", "api_key-sync", "cookie-single_task", "api_key-single_task", "cookie-task_array_order", "api_key-task_array_order", "cookie-file_no_download", "api_key-file_no_download", "cookie-failed_task", "cookie-pending_a_failed_b", "cookie-auth_denial", "cookie-owner_rotation", "cookie-cancel_after_dispatch", "cookie-queued_cancel", "cookie-queued_import", "cookie-queued_malformed", "cookie-queued_close", "cookie-queued_successor"]);
const APPS_DIAGNOSTIC_ERRORS=Object.freeze(['assertion','module_not_found','unsupported_ts_syntax','syntax','type','reference','authentication','forbidden','cancelled','native_failure','protocol','native_binding_unavailable','invalid_argument','unclassified']);
const APPS_DIAGNOSTIC_SUITE_STAGES=Object.freeze(['public_sdk_import','arguments','fixture_read','fixture_decode','vector_admission','result_count','emit_result']);
const APPS_DIAGNOSTIC_GENERIC='npm SDK conformance failed: sdk.apps\n';
function appsDiagnosticError(error){
 try{
  if(error===null||(typeof error!=='object'&&typeof error!=='function'))return 'unclassified';
  const descriptor=Object.getOwnPropertyDescriptor(error,'code');const code=descriptor&&Object.hasOwn(descriptor,'value')?descriptor.value:undefined;
  const codes={ERR_ASSERTION:'assertion',ERR_MODULE_NOT_FOUND:'module_not_found',MODULE_NOT_FOUND:'module_not_found',ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX:'unsupported_ts_syntax',authentication:'authentication',forbidden:'forbidden',cancelled:'cancelled',native_failure:'native_failure',protocol:'protocol',native_binding_unavailable:'native_binding_unavailable',invalid_argument:'invalid_argument'};
  if(typeof code==='string'&&Object.hasOwn(codes,code))return codes[code];
  if(error instanceof SyntaxError)return 'syntax';if(error instanceof TypeError)return 'type';if(error instanceof ReferenceError)return 'reference';
 }catch{}
 return 'unclassified';
}
function appsDiagnosticLine(stage,vector,error){
 const safeStage=APPS_DIAGNOSTIC_STAGES.includes(stage)?stage:'unclassified';
 const safeVector=!APPS_DIAGNOSTIC_SUITE_STAGES.includes(safeStage)&&APPS_DIAGNOSTIC_VECTORS.includes(vector)?vector:'none';
 const safeError=APPS_DIAGNOSTIC_ERRORS.includes(error)?error:'unclassified';
 return 'apps_diagnostic:'+safeStage+':'+safeVector+':'+safeError+'\n';
}
let appsStage='public_sdk_import',appsVector='none',appsFailure;
function captureAppsFailure(error){if(appsFailure===undefined)appsFailure=appsDiagnosticLine(appsStage,appsVector,appsDiagnosticError(error));}
// END CLOSED APPS DIAGNOSTIC

let SessionClient,SessionClientError,OpenMates;
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
const bounded=p=>Promise.race([p,new Promise((_,reject)=>setTimeout(()=>reject(Error('direct fixture deadline')),30000).unref())]);
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function runVector(suite,v,fixture){
 appsStage='peer_spawn';
 const peer=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/session_direct_app_skill_peer.py','--fixture',fixture,'--vector',v.id,'--identity','npm'],{cwd:ROOT,stdio:['ignore','pipe','ignore']});
 const lines=createInterface({input:peer.stdout});let c,endpoint;const oldOrigin=process.env.OPENMATES_APP_URL;
 try{
  appsStage='peer_ready';
  const ready=await bounded(new Promise((resolve,reject)=>{lines.once('line',line=>{try{resolve(JSON.parse(line));}catch{reject(Error('direct readiness'));}});peer.once('error',reject);peer.once('exit',()=>reject(Error('direct peer exited')));}));
  appsStage='endpoint_assert';
  endpoint=ready.endpoint;assert.match(endpoint,/^http:\/\/127\.0\.0\.1:\d+$/);process.env.OPENMATES_APP_URL=endpoint;
  const status=async()=>{const response=await fetch(endpoint+'/__test/status');assert.equal(response.status,200);return response.json();};
  const refused=(operation,code=v.expected_error??'cancelled')=>assert.rejects(operation,e=>e instanceof SessionClientError&&e.code===code&&!e.message.includes('synthetic-private'));
  const release=output=>{try{const raw=output.releaseJson();assert.throws(()=>output.releaseJson(),e=>JSON.parse(e.message).code==='cancelled');return JSON.parse(raw);}catch(error){captureAppsFailure(error);throw error;}finally{output.discard();}};
  const deny=output=>{try{assert.throws(()=>output.releaseJson(),e=>JSON.parse(e.message).code==='cancelled'&&!e.message.includes('synthetic-private'));}catch(error){captureAppsFailure(error);throw error;}finally{output.discard();}};
  const r=suite.request,a=suite.account;
  if(v.credential==='api_key'){
   appsStage='api_key_constructor';const sdk=new OpenMates({apiKey:a.api_key,apiUrl:endpoint,deviceId:a.device_id});
   appsStage='api_key_run';const actual=await sdk.runAppSkill(r.app,r.skill,r.input);appsStage='api_key_result';assert.deepEqual(actual,v.expected);
  }else{
   appsStage='session_constructor';c=new SessionClient({apiUrl:endpoint,appUrl:endpoint,privacy:{enhanced:false},allowPrivateOperations:true});
   const explicit={api_url:endpoint,session_id:a.session_id,cookies:{auth_refresh_token:a.cookie},ws_token:null,master_key:a.master_key,hashed_email:'synthetic-email-hash',user_email_salt:'synthetic-salt',email_encryption_key:null,created_at:1,paired_session_expires_at:null,active_team_id:null};appsStage='session_import_explicit';await c.importSession(explicit);
   if(v.mode.startsWith('queued_')){
    appsStage='queued_prepare';const native=Reflect.get(c,'native'),held=await native.runSkillPrepare(r.app,r.skill,JSON.stringify(r.input));
    if(v.mode==='queued_successor'){appsStage='queued_successor_prepare';const successor=await native.runSkillPrepare(r.app,r.skill,JSON.stringify({query:'synthetic explicit successor B'}));appsStage='queued_release_assert';deny(held);assert.deepEqual(release(successor),suite.sync_expected);}
    else{appsStage='queued_invalidate';if(v.mode==='queued_cancel')c.cancel();else if(v.mode==='queued_import')await c.importSession(explicit);else if(v.mode==='queued_malformed')await refused(()=>c.importSession({}),'invalid_argument');else if(v.mode==='queued_close')await c.close();appsStage='queued_release_assert';deny(held);}
   }else if(v.mode==='cancel_after_dispatch'){
    appsStage='dispatch_call';const call=c.runSkill(r.app,r.skill,r.input);const observation=refused(()=>call);
    appsStage='dispatch_barrier';let dispatched=false;for(let i=0;i<500;i++){const report=await status();assert.equal(report.failure,null);if(report.skill_posts===1){dispatched=true;break;}await pause(10);}assert.ok(dispatched);
    appsStage='dispatch_cancel';c.cancel();await fetch(endpoint+'/__test/release');await observation;
   }else if(v.expected_error){
    // owner_rotation: establish the original owner, then the command's own admission observes the change.
    if(v.mode==='owner_rotation'){appsStage='owner_establish';await c.validateSession();}
    appsStage='expected_refusal';await refused(()=>c.runSkill(r.app,r.skill,r.input));}
   else{appsStage='cookie_run';const actual=await c.runSkill(r.app,r.skill,r.input);appsStage='cookie_result';assert.deepEqual(actual,v.expected);appsStage='session_export';const snapshot=await c.exportSession({includeSecrets:true});appsStage='session_export_assert';assert.equal(snapshot.session.master_key,explicit.master_key);assert.equal(snapshot.session.session_id,explicit.session_id);}
  }
  appsStage='peer_report';const report=await status();appsStage='peer_report_assert';assert.equal(report.failure,null);assert.equal(report.skill_posts,v.expected_skill_posts);assert.equal(report.downloads,v.expected_downloads);assert.equal(report.retention_posts,v.expected_retention_posts);
  if(v.mode==='pending_a_failed_b'){assert.equal(report.polls.task_a,1);assert.equal(report.polls.task_b,1);}if(v.credential==='cookie'&&report.skill_posts)assert.ok(report.auth>=3);
  return{id:v.id,status:'passed',evidence:v.credential==='cookie'?'genuine-NAPI':'maintained-API-key',peer:report};
 }catch(error){captureAppsFailure(error);throw error;}finally{
  try{appsStage='cleanup_release';if(endpoint)try{await fetch(endpoint+'/__test/release');}catch{}if(c){appsStage='cleanup_session';await bounded(c.close());}}catch(error){captureAppsFailure(error);throw error;}finally{lines.close();if(peer.exitCode===null&&peer.signalCode===null){appsStage='cleanup_peer';const ended=new Promise(resolve=>peer.once('exit',resolve));peer.kill('SIGTERM');await bounded(ended);}if(oldOrigin===undefined)delete process.env.OPENMATES_APP_URL;else process.env.OPENMATES_APP_URL=oldOrigin;}
 }
}
async function main(){
 appsStage='public_sdk_import';({SessionClient,SessionClientError,OpenMates}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js'));
 appsStage='arguments';
 const arg=process.argv.indexOf('--fixture'),fixture=arg>=0?process.argv[arg+1]:ROOT+'tests/sdk-conformance/fixtures/session-direct-app-skill.json';
 const cap=process.argv.indexOf('--capability');if(cap>=0)assert.equal(process.argv[cap+1],'sdk.apps');
 appsStage='fixture_read';const bytes=readFileSync(fixture),fixtureSha256=createHash('sha256').update(bytes).digest('hex');
 appsStage='fixture_decode';const suite=JSON.parse(bytes).capabilities['sdk.apps'];const results=[];
 for(const vector of suite.vectors){appsStage='vector_admission';appsVector=APPS_DIAGNOSTIC_VECTORS.includes(vector.id)?vector.id:'none';results.push(await bounded(runVector(suite,vector,fixture)));appsVector='none';}
 appsStage='result_count';assert.equal(results.length,18);appsStage='emit_result';console.log(JSON.stringify({capability:'sdk.apps',language:'npm',status:'passed',fixtureSha256,results}));
}
try{await main();}catch(error){captureAppsFailure(error);process.stderr.write(APPS_DIAGNOSTIC_GENERIC+appsFailure);process.exitCode=1;}
