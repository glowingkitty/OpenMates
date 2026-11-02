// contract-test-file: tooling
// Maintained thin orchestration, explicit inert Rust resources. No native auth/socket proof.
const{test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
const file=path.resolve(__dirname,'../phasedCacheMonitorOperation.ts'),module_=new Module(file);module_.filename=file;module_.paths=module.paths;module_._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,file);const{OwnedCacheMonitorAcquisition}=module_.exports;
const hold=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}},tick=()=>new Promise(r=>setImmediate(r));
function fixture(){let inPhase=false,revoked=false,cancelled=false,nextCount=0,retained=0,applyCount=0,retireCount=0,freeCount=0;const waits=[hold(),hold(),hold()],client={},calls=[];
 const monitor={id:'actual-inert-monitor',changed:async()=>true,close(){calls.push('monitorClose')},free(){}};
 const control={cancel(){cancelled=true;calls.push('cancel')},ensure_current(c){assert.equal(c,client);if(revoked||cancelled)throw Error('session_expired')},async retire(){assert.equal(inPhase,false);retireCount++},terminal(){return undefined},free(){assert.fail('unknown control freed')}};
 const driver={control:()=>control,async next(){assert.equal(inPhase,false);return waits[nextCount++].promise},terminal(){return undefined},free(){assert.fail('unknown driver freed')}};
 const prepare=()=>{assert.equal(inPhase,true);return driver};
 const phase=async f=>{assert.equal(inPhase,false);inPhase=true;try{return await f()}finally{inPhase=false}};
 const current=()=>{if(revoked)throw Error('session_expired')};
 const acquisition=new OwnedCacheMonitorAcquisition(client,prepare,phase,current);
 const apply={kind:'apply',apply(c){assert.equal(c,client);assert.equal(inPhase,true);applyCount++;calls.push('matchedCookieApply')},retain(){assert.fail()},free(){freeCount++}};
 const ready={kind:'ready',apply(){assert.fail()},retain(c){assert.equal(c,client);assert.equal(inPhase,true);retained++;return monitor},free(){freeCount++}};
 return{acquisition,waits,phase,apply,ready,calls,monitor,client,revoke(){revoked=true},get inPhase(){return inPhase},get nextCount(){return nextCount},get applyCount(){return applyCount},get retained(){return retained},get freeCount(){return freeCount},get retireCount(){return retireCount}};
}
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,sync.client.shared-rust-policy
// spec-assertion: Held actual acquisition futures leave the Client/auth lane free for a same-owner B; ready retains the actual opaque monitor once.
test('held next releases phase and same client B can run before actual ready',async()=>{
 const f=fixture(),a=f.acquisition.run({handle:'original',generation:1,owner:'owner'});await tick();assert.equal(f.nextCount,1);assert.equal(f.inPhase,false);let b=false;await f.phase(async()=>{b=true});assert.equal(b,true);assert.equal(f.retained,0);
 f.waits[0].resolve(f.apply);await tick();assert.equal(f.applyCount,1);assert.equal(f.nextCount,2);assert.equal(f.inPhase,false);f.waits[1].resolve(f.ready);assert.equal(await a,f.monitor);assert.equal(f.retained,1);await assert.rejects(f.acquisition.run({handle:'original',generation:1,owner:'owner'}),/unavailable/);
});
// contract-test: supporting surface=gui.web assertions=auth.session.authoritative-enforcement,auth.session.isolation
// spec-assertion: Local cancellation/expiry cannot block a matched Cookie bookkeeping Apply, but full original guards still refuse private ready retention.
test('cancelled or revoked original still applies matched headers before refusing ready',async()=>{
 for(const revoke of [false,true]){const f=fixture(),a=f.acquisition.run({handle:'original',generation:1,owner:'owner'}),rejected=assert.rejects(a,/cancelled|session_expired/);await tick();if(revoke)f.revoke();f.acquisition.cancel();f.waits[0].resolve(f.apply);await tick();assert.equal(f.applyCount,1);assert.equal(f.nextCount,2);f.waits[1].resolve(f.ready);await rejected;assert.equal(f.retained,0);assert.equal(f.freeCount,1,'failed ready remains retained, only consumed Apply freed');assert.equal(f.acquisition.acquisitionIoQuiescent(),false);}
});
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,sync.client.shared-rust-policy
// spec-assertion: Error and negative retire do not free/rearm unknown actual acquisition resources or invent an acquisition terminal.
test('failed acquisition remains one-use and explicit retire runs outside phase',async()=>{
 const f=fixture(),a=f.acquisition.run({handle:'original',generation:1,owner:'owner'}),rejected=assert.rejects(a,/held_socket_failure/);await tick();f.waits[0].reject(Error('held_socket_failure'));await rejected;assert.equal(f.acquisition.acquisitionIoQuiescent(),false);assert.equal(f.freeCount,0);await f.acquisition.retire();assert.equal(f.retireCount,1);assert.equal(f.inPhase,false);await assert.rejects(f.acquisition.run({handle:'original',generation:1,owner:'owner'}),/unavailable/);
});
