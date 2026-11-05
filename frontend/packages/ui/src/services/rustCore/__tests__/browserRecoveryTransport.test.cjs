// contract-test-file: tooling
// Actual PAGE transport+fixed storage source with fixture-only native IDB/port
// realm. NO browser/Worker/port/IDB/WASM/Rust/persistence proof execution.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {api,setup,effect,request,closeFixture,tick,emit,ports,factories,transactions,roots,OP,KEY,NEXT}=require('./helpers/recoveryPortInertRealm.cjs');
test('private factory exposes no port and replies only after full native fixture readback/terminal',async()=>{
 const f=setup();await tick();assert.ok(f.contextId);assert.throws(()=>structuredClone(f.bootstrap));assert.deepEqual(Object.keys(f.bootstrap),['checkpoint']);
 assert.throws(()=>api.createBrowserRecoveryBootstrap(f.worker,f.factory),/unavailable/);assert.throws(()=>api.postBrowserRecoveryBootstrap(f.bootstrap,{}),/invalidated_snapshot/);
 request(f);await tick();const io=f.open();f.all(io.tx);await tick();assert.equal(f.worker.wire.some(v=>v?.result),false);assert.equal(f.data.has(KEY),false);
 io.tx.oncomplete=()=>{};await tick();assert.equal(f.worker.wire.some(v=>v?.result),false);
 io.tx.complete();await tick();const reply=f.worker.wire.find(v=>v?.result);assert.equal(reply.result.ok,true);assert.equal(reply.result.record,NEXT);assert.equal(f.data.get(KEY),NEXT);assert.deepEqual(f.data.get('legacy-unrelated'),{encrypted:'unchanged'});await closeFixture(f);
});
test('generic Worker data and synthetic private events cannot satisfy original physical IO',async()=>{
 const f=setup();await tick();f.worker.postMessage({version:1,finish:true,result:{ok:true,record:NEXT}});await tick();assert.equal(factories.get(f.factory).opens.length,0);
 const pagePort=ports.get(f.worker.remote).peer;pagePort.dispatchEvent(new MessageEvent('message',{data:{version:1,contextId:f.contextId,sequence:1,operationId:OP,effect:effect()}}));await tick();assert.equal(factories.get(f.factory).opens.length,0);assert.equal(f.worker.wire.some(v=>v?.result),false);await closeFixture(f);
});
test('cancel holds actual transaction terminal and later stale A cancel cannot retire B',async()=>{
 const f=setup();await tick();request(f);await tick();const a=f.open();f.all(a.tx);
 f.send({version:1,contextId:f.contextId,sequence:1,operationId:OP,cancel:true});await tick();assert.ok(transactions.get(a.tx).abortRequested);assert.equal(f.worker.wire.some(v=>v?.result),false);
 a.tx.abortTerminal();await tick();assert.equal(f.worker.wire.find(v=>v?.result).result.ok,false);
 const bid='33333333-3333-4333-8333-333333333333';request(f,2,effect('read',bid));await tick();const b=f.open(1);f.all(b.tx);
 f.send({version:1,contextId:f.contextId,sequence:1,operationId:OP,cancel:true});await tick();assert.equal(transactions.get(b.tx).abortRequested,0);
 b.tx.complete();await tick();assert.equal(f.worker.wire.find(v=>v?.sequence===2&&v.result).result.ok,true);await closeFixture(f);
});
test('root revoke/close remains pending until actual original IO terminal, then negative result precedes closed',async()=>{
 const f=setup();await tick();request(f);await tick();const io=f.open();f.all(io.tx);let drained=false;
 const closing=api.closeAndDrainBrowserRecoveryTransport(f.bootstrap).then(()=>{drained=true;});await tick();assert.equal(drained,false);assert.ok(transactions.get(io.tx).abortRequested);
 f.send({version:1,contextId:f.contextId,close:true});await tick();assert.equal(drained,false);io.tx.abortTerminal();await closing;
 const result=f.worker.wire.findIndex(v=>v?.result),closed=f.worker.wire.findIndex(v=>v?.closed);assert.ok(result>=0&&closed>result);assert.equal(f.worker.wire[result].result.ok,false);
});
test('actual root invalidation after IO withholds success',async()=>{
 const f=setup();await tick();request(f);await tick();const io=f.open();f.all(io.tx);f.invalidate();io.tx.complete();await tick();assert.equal(f.worker.wire.find(v=>v?.result).result.ok,false);await closeFixture(f);
});

test('synthetic terminal cannot mint readback and refusal still waits genuine original terminal',async()=>{
 const f=setup();await tick();request(f);await tick();const io=f.open();f.all(io.tx);emit(io.tx,'complete',false);await tick();assert.equal(f.worker.wire.some(v=>v?.result),false);assert.ok(transactions.get(io.tx).abortRequested);
 io.tx.abortTerminal();await tick();assert.equal(f.worker.wire.find(v=>v?.result).result.ok,false);await closeFixture(f);
});
test('private-port post failure rejects drain without claiming a closed native resource',async()=>{
 const f=setup();await tick();const page=ports.get(f.worker.remote).peer;ports.get(page).fail=true;
 await assert.rejects(api.closeAndDrainBrowserRecoveryTransport(f.bootstrap),/recovery_port_unobserved/);assert.equal(f.worker.wire.some(v=>v?.closed),false);
});
