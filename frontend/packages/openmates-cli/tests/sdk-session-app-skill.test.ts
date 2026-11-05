// contract-test-file: tooling
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
import test from 'node:test';
import assert from 'node:assert/strict';
import {SessionClient,SessionClientError} from '../src/sdkSession.ts';
function client(native:unknown):SessionClient{const value=Object.create(SessionClient.prototype);Object.assign(value,{native,essentialEpoch:0});return value;}
test('direct skill facade forwards opaque input/result and performs only one synchronous release',async()=>{
 const calls:unknown[]=[];const expected={success:true,data:{files:[{url:'https://files.example.invalid/private'}],ordered:[3,1,2]}};
 const c=client({runSkillPrepare:async(...args:unknown[])=>{calls.push(args);return{releaseJson(){calls.push('release');return JSON.stringify(expected);},discard(){calls.push('discard');}};}});
 assert.deepEqual(await c.runSkill('web','search',{query:'synthetic'}),expected);assert.deepEqual(calls,[['web','search','{"query":"synthetic"}'],'release','discard']);
});
test('direct queued original epoch refuses before private release and always discards',async()=>{
 let resume!:(value:unknown)=>void;const ticket=new Promise(resolve=>{resume=resolve;});let allocated=0,discarded=0;const c=client({runSkillPrepare:()=>ticket});
 const work=c.runSkill('web','search',{});Reflect.set(c,'essentialEpoch',1);resume({releaseJson(){allocated++;return 'private invalid JSON';},discard(){discarded++;}});
 await assert.rejects(work,e=>e instanceof SessionClientError&&e.code==='cancelled');assert.equal(allocated,0);assert.equal(discarded,1);
});
test('native final allocation denial is normalized and discarded',async()=>{
 let discarded=0;const c=client({runSkillPrepare:async()=>({releaseJson(){throw new Error('{"code":"cancelled","message":"The operation was cancelled."}');},discard(){discarded++;}})});
 await assert.rejects(()=>c.runSkill('web','search',{}),e=>e instanceof SessionClientError&&e.code==='cancelled');assert.equal(discarded,1);
});
test('input and native startup failures never return raw private diagnostics',async()=>{
 let calls=0;const c=client({runSkillPrepare(){calls++;throw new Error('synthetic-private-server-diagnostic');}});const cycle:Record<string,unknown>={};cycle.self=cycle;
 await assert.rejects(()=>c.runSkill('web','search',cycle),e=>e instanceof SessionClientError&&e.code==='invalid_argument');assert.equal(calls,0);
 await assert.rejects(()=>c.runSkill('web','search',{}),e=>e instanceof SessionClientError&&e.code==='native_failure'&&!e.message.includes('synthetic-private'));assert.equal(calls,1);
});

// contract-test: supporting surface=sdks.npm assertions=auth.session.isolation,sdk.encryption.local-only
test('actual supported toJSON cancellation rejects original call before any native prepare',async()=>{
 let cancelled=0,started=0;const c=client({cancel(){cancelled++;},runSkillPrepare(){started++;throw new Error('original retired request must never dispatch');}});
 const input={toJSON(){c.cancel();return{query:'synthetic'};}};
 await assert.rejects(()=>c.runSkill('web','search',input),e=>e instanceof SessionClientError&&e.code==='cancelled');
 assert.equal(cancelled,1);assert.equal(started,0);assert.equal(Reflect.get(c,'essentialEpoch'),1);
});

// contract-test: supporting surface=sdks.npm assertions=auth.session.isolation,sdk.encryption.local-only
test('actual serialization getter retirement rejects before native dispatch',async()=>{
 let cancelled=0,started=0;const c=client({cancel(){cancelled++;},runSkillPrepare(){started++;throw new Error('retired getter request must never dispatch');}});
 const input={get query(){c.cancel();return'synthetic';}};
 await assert.rejects(()=>c.runSkill('web','search',input),e=>e instanceof SessionClientError&&e.code==='cancelled');
 assert.equal(cancelled,1);assert.equal(started,0);
});
