// contract-test-file: tooling
// Owned mocked scheduling/IndexedDB only; no browser/account/network or SDK execution.
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),ts=require('typescript');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'browser-host-lease-inert-'));
process.on('exit',()=>fs.rmSync(dir,{recursive:true,force:true}));
for(const file of ['browserAdapters','platformLifecycle','browserCredentialStorage','browserCredentialPreparation'])
 fs.writeFileSync(path.join(dir,file+'.js'),ts.transpileModule(fs.readFileSync(path.join(__dirname,'..',file+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);
const adapters=require(path.join(dir,'browserAdapters.js'));
const io=require(path.join(dir,'browserCredentialStorage.js'));
const {PriorProfileLifecycle}=require(path.join(dir,'platformLifecycle.js'));
const {createBrowserCredentialEffectHandler}=require(path.join(dir,'browserCredentialPreparation.js'));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
function locks(){let tail=Promise.resolve(),active=0,requests=0;return{
 request(name,options,callback){assert.equal(name,adapters.AUTH_REFRESH_LOCK);assert.equal(options.mode,'exclusive');requests++;
  const next=tail.then(async()=>{assert.equal(active,0);if(options.signal.aborted)throw Error('cancelled');active++;try{return await callback();}finally{active--;}});tail=next.catch(()=>{});return next;},get active(){return active;},get requests(){return requests;}};}
const owner='11111111-1111-4111-8111-111111111111',operationId='44444444-4444-4444-8444-444444444444';
const record={version:1,owner,generation:2,credentialRevision:3,apiEndpoint:'https://api.example',appOrigin:'https://app.example',snapshotId:'22222222-2222-4222-8222-222222222222',ciphertext:Buffer.alloc(100,1).toString('base64'),ciphertextSha256:'a'.repeat(64)};
const next={...record,snapshotId:'33333333-3333-4333-8333-333333333333',credentialRevision:4};
const read={kind:'read',operationId,owner,apiEndpoint:record.apiEndpoint,appOrigin:record.appOrigin};
const cas=(expected=null,value=next)=>({kind:'cas',operationId,expected,next:value});
const ABSENT=Symbol('absent');
function database(...values){const existing=values.length?values[0]:ABSENT;const rows=new Map([['id',owner]]);if(existing!==ABSENT)rows.set(io.BROWSER_CREDENTIAL_RECORD,existing);const transactions=[];const db=new EventTarget();
 db.transaction=(_name,mode)=>{const requests=[],writes=[];let aborted=0;const store={get(key){const request={key,kind:'get'};requests.push(request);return request;},getKey(key){const request={key,kind:'key'};requests.push(request);return request;},put(value,key){writes.push([key,value]);return{};}};
  const tx={mode,requests,writes,objectStore(){return store;},abort(){aborted++;},get aborted(){return aborted;},drain(){while(requests.length){const request=requests.shift();request.result=request.kind==='key'?(rows.has(request.key)?request.key:undefined):rows.get(request.key);request.onsuccess();}},complete(){for(const [key,value]of writes)rows.set(key,value);this.oncomplete();},abortTerminal(){this.onabort();}};transactions.push(tx);return tx;};
 return{db,rows,transactions};}
function direct(effect,...values){const f=database(...values),lifecycle=new PriorProfileLifecycle(),controller=new AbortController();const pending=io.executeBrowserCredentialIO(f.db,effect,lifecycle,lifecycle.current(),controller.signal,()=>{});return{...f,lifecycle,controller,pending,tx:f.transactions[0]};}

test('inherited existing refresh lease avoids reacquisition and refuses saved/copy/foreign tokens',async()=>{
 const manager=locks(),signal=new AbortController().signal;let saved;
 await adapters.withAuthRefreshLock(manager,signal,async lease=>{saved=lease;assert.throws(()=>structuredClone(lease));
  assert.equal(await adapters.withAuthRefreshLock(manager,signal,async inner=>{assert.equal(inner,lease);return return7();},{lease}),7);
  await assert.rejects(adapters.withAuthRefreshLock(locks(),signal,async()=>1,{lease}),/invalidated_snapshot/);
  await assert.rejects(adapters.withAuthRefreshLock(manager,signal,async()=>1,{lease:{}}),/invalidated_snapshot/);
 });
 assert.equal(manager.requests,1);await assert.rejects(adapters.withAuthRefreshLock(manager,signal,async()=>1,{lease:saved}),/invalidated_snapshot/);
 function return7(){return 7;}
});
test('queued lock acquisition rechecks cancellation and captured operation context before effects',async()=>{
 for(const reason of ['context','cancel']){const manager=locks(),gate=deferred(),first=adapters.withAuthRefreshLock(manager,new AbortController().signal,async()=>gate.promise);await tick();let current=true,calls=0;const controller=new AbortController();
  const second=adapters.withAuthRefreshLock(manager,controller.signal,async()=>{calls++;},{current:()=>{if(!current)throw Error('invalidated_snapshot');}});const rejected=assert.rejects(second,/invalidated_snapshot|cancelled/);
  if(reason==='context')current=false;else controller.abort();gate.resolve();await first;await rejected;assert.equal(calls,0);assert.equal(manager.active,0);}
});
test('unsupported WebLocks do not silently run stronger operation',async()=>{let called=false;await assert.rejects(adapters.withAuthRefreshLock(undefined,new AbortController().signal,async()=>{called=true;}),/auth_refresh_lock_unavailable/);assert.equal(called,false);});
test('local reverse lease binds actual issuer/operation, rejects clone and closes only after terminal IO',async()=>{
 const issuer={},controller=new AbortController(),terminal=deferred();const scope=adapters.openAuthRefreshEffectLease(issuer,operationId,controller.signal,()=>{});
 assert.throws(()=>structuredClone(scope.lease));assert.throws(()=>adapters.assertAuthRefreshEffectLease({},issuer,operationId),/invalidated_snapshot/);
 assert.throws(()=>adapters.assertAuthRefreshEffectLease(scope.lease,{},operationId),/invalidated_snapshot/);assert.throws(()=>adapters.assertAuthRefreshEffectLease(scope.lease,issuer,'other'),/invalidated_snapshot/);
 const effect=adapters.withAuthRefreshEffectLease(scope.lease,issuer,operationId,async signal=>{await terminal.promise;assert.equal(signal.aborted,true);return 1;});const rejected=assert.rejects(effect,/invalidated_snapshot/);await tick();let closed=false;const closing=scope.close().then(()=>{closed=true;});await tick();assert.equal(closed,false);assert.throws(()=>adapters.assertAuthRefreshEffectLease(scope.lease,issuer,operationId));terminal.resolve();await rejected;await closing;assert.equal(closed,true);
});
test('exact predecessor CAS performs X to Y, refuses stale X to Z and permits Y to Z',async()=>{
 const f=direct(cas(record,next),record);f.tx.drain();let settled=false;f.pending.then(()=>{settled=true;});await tick();assert.equal(settled,false);assert.deepEqual(f.rows.get(io.BROWSER_CREDENTIAL_RECORD),record);f.tx.complete();const receipt=await f.pending;assert.deepEqual(receipt.expected,record);assert.deepEqual(receipt.snapshot,next);assert.equal(receipt.crossDatabaseAssociationProven,false);assert.equal(receipt.credentialAcknowledged,false);
 const z={...next,snapshotId:'55555555-5555-4555-8555-555555555555'};const stale=direct(cas(record,z),next);stale.tx.drain();assert.equal(stale.tx.writes.length,0);const rejected=assert.rejects(stale.pending,/credential_conflict/);stale.tx.abortTerminal();await rejected;assert.deepEqual(stale.rows.get(io.BROWSER_CREDENTIAL_RECORD),next);
 const fresh=direct(cas(next,z),next);fresh.tx.drain();fresh.tx.complete();assert.deepEqual((await fresh.pending).snapshot,z);
});
test('READ distinguishes absent from malformed present rows; no write and no ACK',async()=>{
 for(const existing of [ABSENT,record]){const f=direct(read,existing);f.tx.drain();f.tx.complete();const receipt=await f.pending;assert.deepEqual(receipt.snapshot,existing===ABSENT?null:record);assert.equal('expected'in receipt,false);assert.equal(receipt.credentialAcknowledged,false);assert.equal(f.tx.mode,'readonly');assert.equal(f.tx.writes.length,0);}
 for(const existing of [null,undefined,{...record,owner:'other'}]){const f=direct(read,existing),rejected=assert.rejects(f.pending,/invalid_snapshot/);f.tx.drain();f.tx.abortTerminal();await rejected;}
});
test('create CAS accepts only actual absence and protects malformed existing namespace',async()=>{
 const f=direct(cas());f.tx.drain();f.tx.complete();assert.deepEqual((await f.pending).snapshot,next);
 for(const existing of [null,undefined,record]){const f=direct(cas(),existing),rejected=assert.rejects(f.pending,/invalid_snapshot|credential_conflict/);f.tx.drain();assert.equal(f.tx.writes.length,0);f.tx.abortTerminal();await rejected;}
});
test('unabortable wrong owner/conflict/versionchange never returns successful receipt',async()=>{
 for(const fault of ['owner','conflict','versionchange']){const f=direct(cas(),fault==='conflict'?record:ABSENT);f.tx.abort=()=>{throw Error('already-committing');};if(fault==='owner')f.rows.set('id','other');const rejected=assert.rejects(f.pending,/owner_mismatch|credential_conflict|invalidated_snapshot/);f.tx.drain();if(fault==='versionchange')f.db.dispatchEvent(new Event('versionchange'));f.tx.complete();await rejected;}
});
test('CAS captures supplied predecessor/next before awaits and never adopts mutated caller input',async()=>{
 const effect=cas({...record},{...next}),f=direct(effect,record);effect.next.snapshotId='66666666-6666-4666-8666-666666666666';effect.expected.snapshotId='77777777-7777-4777-8777-777777777777';f.tx.drain();f.tx.complete();assert.deepEqual((await f.pending).snapshot,next);
});
function handlerFixture(provider){const f=database(),issuer={},lifecycle=new PriorProfileLifecycle(),controller=new AbortController(),prior={generation:lifecycle.current(),persistence:'persisted',profile:{principal:owner}};let checks=0;const context={owner,teamId:null,workspaceEpoch:1,apiEndpoint:record.apiEndpoint,appOrigin:record.appOrigin};
 const handler=createBrowserCredentialEffectHandler({issuer,lifecycle,prior,reader:{async assertCurrent(){checks++;}},database:provider??(async()=>f.db),context:()=>({...context})});const scope=adapters.openAuthRefreshEffectLease(issuer,operationId,controller.signal,handler.current);
 return{...f,issuer,lifecycle,controller,handler,scope,context,get checks(){return checks;}};}
test('reverse host handler uses local correlation lease without WebLock reacquisition and drains IDB terminal on close',async()=>{
 const f=handlerFixture(),effect=f.handler.execute(cas(),f.scope.lease,f.controller.signal),rejected=assert.rejects(effect,/invalidated_snapshot|cancelled/);await tick();f.transactions[0].drain();let drained=false;const close=Promise.all([f.handler.close(),f.scope.close()]).then(()=>{drained=true;});await tick();assert.equal(drained,false);assert.equal(f.transactions[0].aborted,1);f.transactions[0].abortTerminal();await rejected;await close;assert.equal(drained,true);await assert.rejects(f.handler.execute(cas(),f.scope.lease,f.controller.signal),/invalidated_snapshot/);
});
test('handler close waits in-flight database opening and prevents any late transaction',async()=>{
 const opening=deferred(),f=handlerFixture(()=>opening.promise),effect=f.handler.execute(cas(),f.scope.lease,f.controller.signal),rejected=assert.rejects(effect,/invalidated_snapshot|cancelled/);await tick();let closed=false;const closing=Promise.all([f.handler.close(),f.scope.close()]).then(()=>{closed=true;});await tick();assert.equal(closed,false);opening.resolve(f.db);await rejected;await closing;assert.equal(f.transactions.length,0);
});
test('owner/Team/lifecycle drift during guarded host await refuses before IDB work',async()=>{
 for(const fault of ['owner','team','lifecycle']){const opening=deferred(),f=handlerFixture(()=>opening.promise),effect=f.handler.execute(cas(),f.scope.lease,f.controller.signal),rejected=assert.rejects(effect,/invalidated_snapshot|cancelled/);await tick();if(fault==='owner')f.context.owner='other';else if(fault==='team')f.context.teamId='changed';else f.lifecycle.invalidate();opening.resolve(f.db);await rejected;assert.equal(f.transactions.length,0);await f.handler.close();await f.scope.close();}
});
test('handler CAS input capture is synchronous and IO receipt stays unacknowledged',async()=>{
 const f=handlerFixture(),effect=cas(),pending=f.handler.execute(effect,f.scope.lease,f.controller.signal);effect.next={...next,snapshotId:'88888888-8888-4888-8888-888888888888'};await tick();f.transactions[0].drain();f.transactions[0].complete();const receipt=await pending;assert.deepEqual(receipt.snapshot,next);assert.equal(receipt.credentialAcknowledged,false);assert.equal(f.checks,2);await f.handler.close();await f.scope.close();
});
test('closed effect schema refuses fields, context drift, malformed/oversized combined CAS',()=>{
 assert.equal(io.validBrowserCredentialIOEffect(read),true);assert.equal(io.validBrowserCredentialIOEffect(cas()),true);
 for(const effect of [{...read,heldLock:true},{...cas(),associationProven:true},{...read,operationId:'bad'},{...cas(),expected:{...record,owner:'other'}},{...cas({...record,ciphertext:Buffer.alloc(7000).toString('base64')},{...next,ciphertext:Buffer.alloc(7000).toString('base64')})}])assert.equal(io.validBrowserCredentialIOEffect(effect),false);
});
