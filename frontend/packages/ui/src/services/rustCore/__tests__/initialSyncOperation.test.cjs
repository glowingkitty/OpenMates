/** Inert phase/lifetime tests only; never native/browser persistence proof. */
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ts=require(process.env.OPENMATES_TEST_TYPESCRIPT||'typescript');
const root=process.env.OPENMATES_TEST_RUST_CORE_ROOT||path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'initialSyncOperation.ts'),'utf8');
const loaded={};new vm.Script('(function(exports){'+ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText+'})').runInThisContext()(loaded);
const {OwnedInitialSyncOperation}=loaded;
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
function fixture(){
 let inPhase=false,cancelled=false,finished=0,native=false,consumed=false;const read=deferred(),write=deferred(),events=[];
 const check=actual=>{assert.equal(actual,client);assert.equal(inPhase,true);if(cancelled)throw Error('cancelled');};
 const control={cancel(){cancelled=true;events.push('cancel');},ensure_current:check,free(){throw Error('free_before_typed_transfer');}};
 const proof={ensure_current:check,stored_metadata_count(c){check(c);return 501;},free(){}};
 const store={control(){return control;},async drive(){assert.equal(inPhase,false);events.push('store_io');await write.promise;native=true;},finish(c){check(c);finished++;return proof;},terminal(){return native?{native_io_quiescent(){return true;},free(){}}:undefined;},free(){throw Error('unknown_free');}};
 const metadata={ensure_current:check,received_metadata_count(c){check(c);assert.equal(consumed,false);return 501;},begin_store(c){check(c);assert.equal(consumed,false);consumed=true;return store;},cancel(){cancelled=true;},free(){throw Error('unknown_free');}};
 const handle={control(){return control;},async drive(){assert.equal(inPhase,false);events.push('actor_io');await read.promise;},retain(c){check(c);events.push('retain');return metadata;},free(){throw Error('unknown_free');}};
 const client={begin_initial_sync(){assert.equal(inPhase,true);return handle;}};
 const phase=async operation=>{assert.equal(inPhase,false);inPhase=true;try{return await operation();}finally{inPhase=false;}};
 const op=new OwnedInitialSyncOperation(client,phase,()=>{});
 return{op,read,write,events,get finished(){return finished;},binding:{handle:'h',generation:1,owner:'owner',monitorId:'actual-monitor'}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement,chats.persistence.client-encrypted
test('actor and native IO wait outside Client phase; counts keep every metadata row',async()=>{
 const f=fixture(),running=f.op.run(f.binding);await tick();assert.deepEqual(f.events,['actor_io']);assert.equal(f.op.succeeded,false);
 f.read.resolve();await tick();assert.deepEqual(f.events,['actor_io','retain','store_io']);assert.equal(f.finished,0);
 f.write.resolve();assert.deepEqual(await running,{receivedMetadataCount:501,storedMetadataCount:501});assert.equal(f.finished,1);assert.equal(f.op.succeeded,true);
 await assert.rejects(f.op.run(f.binding),/unavailable/);
});
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,auth.session.isolation,chats.persistence.client-encrypted
test('cancel while actual native IO is held cannot finish or rearm; native-only terminal grants nothing',async()=>{
 const f=fixture(),running=f.op.run(f.binding);const rejected=assert.rejects(running,/cancelled/);f.read.resolve();await tick();f.op.cancel();
 assert.equal(f.op.nativeIoQuiescent(),false);assert.equal(f.finished,0);f.write.resolve();await rejected;
 assert.equal(f.op.nativeIoQuiescent(),true);assert.equal(f.op.succeeded,false);assert.equal(f.finished,0);await assert.rejects(f.op.run(f.binding),/unavailable/);
});
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,auth.session.isolation,chats.persistence.client-encrypted
test('native unknown failure remains held and refuses a successor',async()=>{
 const f=fixture(),running=f.op.run(f.binding);const rejected=assert.rejects(running,/actual_unknown/);f.read.resolve();await tick();f.write.reject(Error('actual_unknown'));await rejected;
 assert.equal(f.op.nativeIoQuiescent(),false);assert.equal(f.op.succeeded,false);assert.equal(f.finished,0);await assert.rejects(f.op.run(f.binding),/unavailable/);
});
