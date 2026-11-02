/** Actual built npm/NAPI calls. Peer process/lifecycle belongs to fixed gate. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {MetadataAuthentication} from '../../../frontend/packages/openmates-cli/dist/sdk-session-v1-entry.js';
const arg=name=>process.argv[process.argv.indexOf(name)+1];
const suite=JSON.parse(readFileSync(arg('--fixture'),'utf8')).capabilities['session.ephemeral-metadata-startup.v1'];
const vector=suite.vectors.find(row=>row.id===arg('--vector')),endpoint=arg('--endpoint');
let observedLifecycle;
async function refused(promise,code){await assert.rejects(promise,error=>error?.code===code);}
async function status(){const response=await fetch(endpoint+'/__test/status',{signal:AbortSignal.timeout(2000)});assert.equal(response.status,200);return response.json();}
async function waitMetadata(){for(let n=0;n<200;n++){if((await status()).metadata_requests===1)return;await new Promise(resolve=>setTimeout(resolve,10));}throw new Error('bounded metadata dispatch');}
function auth(extra={}){return new MetadataAuthentication({apiUrl:endpoint,appUrl:suite.protocol.app_origin,sessionId:suite.account.session_id,cookies:{auth_refresh_token:suite.account.cookie},...extra});}
const authFailureModes=new Set(['late_invalid_cookie','late_undecodable_cookie','malformed_body','truncated_body','held_malformed_body','cancel_before_headers','cancel_after_headers','foreign_auth_cancel','early_invalid_cookie','early_undecodable_cookie']);
async function waitFor(predicate){for(let n=0;n<200;n++){const value=await status();if(predicate(value))return value;await new Promise(resolve=>setTimeout(resolve,10));}throw new Error('bounded original auth condition');}
async function authFailure(pending){
  const mode=vector.mode;let issued=false;
  const run=pending.authenticate().then(value=>{issued=true;return value;});run.catch(()=>{});
  const held=['held_malformed_body','cancel_before_headers','cancel_after_headers','foreign_auth_cancel'].includes(mode);
  if(held){
    const marker=mode==='cancel_before_headers'?'before_headers_held':'body_held';
    const observed=await waitFor(value=>value.auth_events.includes(marker));
    assert.equal(observed.auth_active,1);assert.equal(observed.connections,0);assert.equal(issued,false);
    if(mode==='cancel_before_headers')assert.equal(pending.credentialSnapshot().cookies.auth_refresh_token,suite.account.cookie);
    else await waitFor(()=>pending.credentialSnapshot().cookies.auth_refresh_token==='synthetic-rotation-1');
    let drain,drained=false;
    if(mode!=='held_malformed_body'){
      // A JS Promise has no supported drop signal. This is explicit ORIGINAL
      // cancellation and real native drain, never a Promise-GC claim.
      pending.cancel();drain=pending.cancelAndDrain().then(()=>{drained=true;});drain.catch(()=>{});
      const stillHeld=await status();assert.equal(stillHeld.auth_active,1);assert.equal(stillHeld.auth_events.includes('body_written'),false);assert.equal(drained,false);assert.equal(issued,false);
    }
    const release=await fetch(endpoint+'/__test/release-auth',{signal:AbortSignal.timeout(2000)});assert.equal(release.status,200);
    await refused(run,vector.error);if(drain)await drain;
  }else await refused(run,vector.error);
  await pending.cancelAndDrain();assert.equal(issued,false);
  const credentials=pending.credentialSnapshot();assert.deepEqual(credentials.cookies,{auth_refresh_token:'synthetic-rotation-1'});
  await refused(pending.authenticate(),'conflict');
  const after=await waitFor(value=>value.auth_active===0);assert.equal(after.auth_requests,1);assert.equal(after.connections,0);
  if(mode==='foreign_auth_cancel')observedLifecycle='explicit-original-cancel-not-promise-drop';
}
async function main(){
  const mode=vector.mode;
  if(authFailureModes.has(mode)){const pending=auth();try{await authFailure(pending);}finally{await pending.cancelAndDrain();}return;}
  if(['owner_dto','api_key'].includes(mode)){
    assert.throws(()=>auth(mode==='owner_dto'?{ownerId:suite.account.owner_id}:{apiKey:'synthetic-api-key'}),error=>error.code===vector.error);return;
  }
  const pending=auth();let client;
  try{
    if(['denied','malformed','expired'].includes(mode)){
      await refused(pending.authenticate(),vector.error);assert.equal(pending.credentialSnapshot().cookies.auth_refresh_token,'synthetic-rotation-1');return;
    }
    client=await pending.authenticate();assert.equal(client.credentialSnapshot().cookies.auth_refresh_token,'synthetic-rotation-1');
    if(mode==='auth_cancel'){pending.cancel();assert.throws(()=>client.prepareInitialSync(),error=>error.code==='cancelled');return;}
    const operation=client.prepareInitialSync();
    if(mode==='cancel_before')operation.cancel();
    if(vector.error){
      const run=operation.run();run.catch(()=>{});
      if(mode==='cancel_inflight'){await waitMetadata();operation.cancel();}
      await refused(run,vector.error);
      if(mode==='rotation_failure'||mode==='changed_principal')assert.equal(client.credentialSnapshot().cookies.auth_refresh_token,'synthetic-rotation-2');
      await assert.rejects(async()=>client.prepareInitialSync(),error=>error.code==='cancelled');return;
    }
    const snapshot=await operation.run();assert.equal(snapshot.receivedMetadataCount(client),vector.expected_count);
    await refused(operation.run(),'conflict');
    if(mode==='foreign_snapshot'){
      // Same account and endpoint, DIFFERENT actual authenticated memory store.
      const second=new MetadataAuthentication({apiUrl:endpoint,appUrl:suite.protocol.app_origin,...client.credentialSnapshot()});
      const foreign=await second.authenticate();try{assert.throws(()=>snapshot.receivedMetadataCount(foreign),error=>error.code==='forbidden');}finally{await foreign.close();}
      assert.equal(snapshot.receivedMetadataCount(client),vector.expected_count);
    }
    if(mode==='stale_snapshot'){const next=client.prepareInitialSync();assert.throws(()=>snapshot.receivedMetadataCount(client),error=>error.code==='cancelled');next.cancel();}
    await client.close();assert.throws(()=>snapshot.receivedMetadataCount(client),error=>error.code==='cancelled');
  }finally{if(client)await client.close();pending.cancel();}
}
main().then(()=>process.stdout.write(JSON.stringify({id:vector.id,status:'passed',...(observedLifecycle?{lifecycle:observedLifecycle}:{})}))).catch(()=>{console.error('npm opaque metadata conformance failed');process.exitCode=1;});
