// contract-test-file: tooling
/** Inert scheduling doubles only. No Rust/IDB/auth/crypto proof is claimed. */
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ts=require(process.env.OPENMATES_TEST_TYPESCRIPT||'typescript');
const root=process.env.OPENMATES_TEST_RUST_CORE_ROOT||path.resolve(__dirname,'..');
const loaded={};new vm.Script('(function(exports){'+ts.transpileModule(fs.readFileSync(path.join(root,'recoveryFinalizationOperation.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText+'})').runInThisContext()(loaded);
const {OwnedRecoveryFinalization}=loaded,deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};},tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({unsupported=false,missingTerminal=false,stale=false}={}){
 const io=deferred(),events=[];let phase=false,cancelled=false,borrow=false,current=!stale,finished=0,freed=0;
 const client={},check=actual=>{assert.equal(actual,client);assert.equal(phase,true);if(!current||cancelled)throw Error('cancelled');};
 const terminal={native_io_quiescent(){return true},free(){freed++;}};
 const stored={ensure_current:check,free(){freed++;}};
 const finalizer={ensure_current:check,async drive(){assert.equal(phase,false);borrow=true;events.push('drive');try{await io.promise;}finally{borrow=false;}if(cancelled)throw Error('cancelled');events.push('actual-return')},
  finish(actual){check(actual);events.push('finish');finished++;return stored;},terminal(){assert.equal(borrow,false);return missingTerminal?undefined:terminal},
  cancel(){assert.fail('borrowed mutable WASM finalizer must not be cancelled')},free(){freed++;}};
 const recovery={ensure_current:check,begin_metadata_local_finalize(actual){check(actual);events.push('begin');if(unsupported)throw Error('unsupported_actual_core');return finalizer}};
 const control={cancel(){cancelled=true;events.push('negative')}};
 const runPhase=async operation=>{assert.equal(phase,false);phase=true;try{return await operation();}finally{phase=false;}};
 const operation=new OwnedRecoveryFinalization(client,recovery,control,runPhase,()=>{if(!current)throw Error('cancelled')});
 return{operation,io,events,runPhase,get finished(){return finished},get freed(){return freed},expire(){current=false}};
}
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
test('exact begin and finish phases enclose detached native drive and retain typed result',async()=>{
 const f=fixture(),run=f.operation.run();await tick();assert.deepEqual(f.events,['begin','drive']);assert.equal(f.finished,0);assert.equal(f.operation.nativeIoQuiescent(),false);
 f.io.resolve();await run;assert.deepEqual(f.events,['begin','drive','actual-return','finish']);assert.equal(f.finished,1);assert.equal(f.freed,0);assert.equal(f.operation.nativeIoQuiescent(),true);
 await f.runPhase(async()=>f.operation.ensure_current());f.operation.releaseAfterRecoveryRetired();assert.equal(f.freed,3);await assert.rejects(f.operation.run(),/unavailable/);
});
// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,chats.persistence.client-encrypted
test('original negative during a held native drive neither frees nor finishes or rearms',async()=>{
 const f=fixture(),run=f.operation.run(),refused=assert.rejects(run,/cancelled/);await tick();f.operation.cancel();assert.equal(f.finished,0);assert.equal(f.freed,0);assert.equal(f.operation.nativeIoQuiescent(),false);
 f.io.resolve();await refused;assert.equal(f.finished,0);assert.equal(f.freed,0);assert.throws(()=>f.operation.releaseAfterRecoveryRetired(),/unavailable/);await assert.rejects(f.operation.run(),/unavailable/);
});
// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,chats.persistence.client-encrypted
test('unknown native rejection retains all originals and cannot manufacture terminal success',async()=>{
 const f=fixture(),run=f.operation.run(),refused=assert.rejects(run,/native_unknown/);await tick();f.io.reject(Error('native_unknown'));await refused;assert.equal(f.finished,0);assert.equal(f.freed,0);assert.equal(f.operation.nativeIoQuiescent(),false);assert.throws(()=>f.operation.releaseAfterRecoveryRetired(),/unavailable/);await assert.rejects(f.operation.run(),/unavailable/);
});
for(const scope of ['unsupported','stale','missingTerminal']){
 // contract-test: supporting surface=gui.web assertions=auth.session.isolation,auth.session.authoritative-enforcement,chats.persistence.client-encrypted
 test('original refusal retains resources and grants no native terminal: '+scope,async()=>{
  const f=fixture({[scope]:true}),run=f.operation.run(),refused=assert.rejects(run,scope==='unsupported'?/unsupported_actual_core/:scope==='stale'?/cancelled/:/unavailable/);
  if(scope==='missingTerminal'){await tick();f.io.resolve();}await refused;assert.equal(f.freed,0);assert.equal(f.operation.nativeIoQuiescent(),false);assert.throws(()=>f.operation.releaseAfterRecoveryRetired(),/unavailable/);await assert.rejects(f.operation.run(),/unavailable/);
 });
}
// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,auth.session.isolation,chats.persistence.client-encrypted
test('scope retirement after actual native return still denies result publication',async()=>{
 const f=fixture(),run=f.operation.run(),refused=assert.rejects(run,/cancelled/);await tick();f.expire();f.io.resolve();await refused;assert.equal(f.finished,0);assert.equal(f.freed,0);assert.equal(f.operation.nativeIoQuiescent(),false);
});
