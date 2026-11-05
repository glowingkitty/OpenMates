/** Native doubles prove facade handoff only; actual Rust/HTTP proof stays in isolated CI. */
// contract-test-file: tooling
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {SessionClient,SessionClientError} from '../src/sdkSession.ts';
function client(native:object):SessionClient {const c=Object.create(SessionClient.prototype) as SessionClient;Object.defineProperty(c,'essentialEpoch',{value:0,writable:true});Object.defineProperty(c,'native',{value:native});return c;}
// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,auth.session.isolation
test('Apps list uses opaque fixed native inventory and preserves JSON items with final synchronous release',async()=>{
 const calls:string[]=[];const expected=[{id:'fixture-app',title:'Fixture inventory',fields:{id:'fixture-app'}}];
 const c=client({list:()=>assert.fail('legacy Apps list must not run'),appsInventoryOpen:()=>({cancel(){},run:async()=>({releaseJson:()=>{calls.push('release');return JSON.stringify(expected);},discard:()=>calls.push('discard')})})});
 assert.deepEqual(await c.list('apps'),expected);assert.deepEqual(calls,['release','discard']);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,auth.session.isolation
test('queued Apps output is discarded without allocation when original epoch retires',async()=>{
 let discarded=false;const c:SessionClient=client({appsInventoryOpen:()=>({cancel(){},run:async()=>{Reflect.set(c,'essentialEpoch',1);return {releaseJson:()=>assert.fail('stale output allocated'),discard:()=>{discarded=true;}};}})});
 await assert.rejects(c.list('apps'),(e:unknown)=>e instanceof SessionClientError&&e.code==='cancelled');assert.equal(discarded,true);
});

// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,auth.session.isolation
test('pre-aborted Apps signal performs no original native dispatch or global cancellation',async()=>{
 const aborted=new AbortController();aborted.abort();let opens=0;
 const c=client({appsInventoryOpen:()=>{opens++;assert.fail('pre-aborted native operation opened');},cancel:()=>assert.fail('global cancel touches A')});
 await assert.rejects(c.list('apps',{signal:aborted.signal}),(e:unknown)=>e instanceof SessionClientError&&e.code==='cancelled');assert.equal(opens,0);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,auth.session.isolation
test('Apps AbortSignal cancels only its original opaque operation while native return remains awaited',async()=>{
 const aborted=new AbortController();let ownCancels=0,reject!:(error:Error)=>void,started!:()=>void;
 const began=new Promise<void>(resolve=>{started=resolve});const pending=new Promise<never>((_,failed)=>{reject=failed});
 const c=client({appsInventoryOpen:()=>({run:()=>{started();return pending;},cancel:()=>{ownCancels++;reject(new Error(JSON.stringify({code:'cancelled',message:'The operation was cancelled.'})));}}),cancel:()=>assert.fail('global cancel touches A')});
 const result=c.list('apps',{signal:aborted.signal});await began;aborted.abort();await assert.rejects(result,(e:unknown)=>e instanceof SessionClientError&&e.code==='cancelled');assert.equal(ownCancels,1);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,auth.session.isolation
test('Apps signal input getter cannot retire original epoch then dispatch a replacement native operation',async()=>{
 let opens=0;const c:SessionClient=client({appsInventoryOpen:()=>{opens++;assert.fail('obsolete input dispatch');}});
 const options={get signal(){Reflect.set(c,'essentialEpoch',1);return new AbortController().signal;}};
 await assert.rejects(c.list('apps',options),(e:unknown)=>e instanceof SessionClientError&&e.code==='cancelled');assert.equal(opens,0);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,auth.session.isolation
test('actual pre-aborted AbortSignal state cannot be hidden by a caller property override',async()=>{
 const aborted=new AbortController();aborted.abort();Object.defineProperty(aborted.signal,'aborted',{value:false});let opens=0;
 const c=client({appsInventoryOpen:()=>{opens++;assert.fail('actual aborted state was replaced');}});
 await assert.rejects(c.list('apps',{signal:aborted.signal}),(e:unknown)=>e instanceof SessionClientError&&e.code==='cancelled');assert.equal(opens,0);
});
