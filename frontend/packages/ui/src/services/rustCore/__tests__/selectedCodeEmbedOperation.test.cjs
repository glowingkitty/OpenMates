// contract-test-file: tooling
/** Inert same-resource adapter doubles only, never Core/native/browser proof. */
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ts=require(process.env.OPENMATES_TEST_TYPESCRIPT||'typescript');
const root=process.env.OPENMATES_TEST_RUST_CORE_ROOT||path.resolve(__dirname,'..');
const text=fs.readFileSync(path.join(root,'selectedCodeEmbedOperation.ts'),'utf8');
const out={};new vm.Script('(function(exports){'+ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText+'})').runInThisContext()(out);
const {OwnedSelectedCodeEmbedStore}=out;
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const ID='22222222-2222-4222-8222-222222222222';
function fixture(options={}){
 const client={},metadataProof={},read={},acquire=deferred(),nativeIO=deferred(),events=[];
 let phase=false,current=true,cancelled=false,steps=0,finishes=0,storeBegins=0;
 const check=c=>{assert.equal(c,client);assert.equal(phase,true);if(!current||cancelled)throw Error('cancelled');};
 const negative=()=>{cancelled=true;events.push('negative');};
 const selected={ensure_current:check,cancel:negative};
 const readControl={ensure_current:check,cancel:negative,terminal(){return options.noReadTerminal?undefined:{acquisition_io_quiescent:()=>true};}};
 const readHandle={control:()=>readControl,async next(){assert.equal(phase,false);events.push('next');
  if(steps++===0){await acquire.promise;return{kind:'apply',apply(c){assert.equal(c,client);assert.equal(phase,true);events.push('actual-auth-apply');}};}
  return{kind:'ready',retain(c){check(c);events.push('one-use-retain');return selected;}};
 }};
 const stored={ensure_current:check};
 const native={ensure_current:check,control(){return{ensure_current:check,cancel:negative};},
  async drive(){assert.equal(phase,false);events.push('native-await');await nativeIO.promise;events.push('native-return');},
  finish(c){check(c);events.push('native-finish');finishes++;return stored;},
  terminal(){return options.noNativeTerminal?undefined:{native_io_quiescent:()=>true};}};
 const recovery={ensure_current:check,prepare_selected_code_embed_read(c,p,id){check(c);assert.equal(p,metadataProof);assert.equal(id,ID);events.push('prepare');return readHandle;},
  begin_selected_code_embed_local_store(c,p,r){check(c);assert.equal(p,metadataProof);assert.equal(r,selected);storeBegins++;events.push('native-begin');return native;}};
 const metadata={ensure_current(){check(client);},beginReply(c,begin){check(c);events.push('opaque-proof');return begin(metadataProof);}};
 const runPhase=async operation=>{assert.equal(phase,false);phase=true;try{return await operation();}finally{phase=false;}};
 const operation=new OwnedSelectedCodeEmbedStore(client,recovery,metadata,ID,runPhase,()=>{if(!current)throw Error('cancelled');});
 return{operation,acquire,nativeIO,events,runPhase,expire(){current=false;},get finishes(){return finishes;},get storeBegins(){return storeBegins;}};
}
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
test('same opaque proof/read flows once through detached acquisition/native IO and guarded finish',async()=>{
 const f=fixture(),run=f.operation.run();await tick();assert.deepEqual(f.events,['opaque-proof','prepare','next']);
 f.acquire.resolve();await tick();assert.equal(f.storeBegins,1);assert.equal(f.finishes,0);assert.ok(f.events.includes('native-await'));
 f.nativeIO.resolve();await run;assert.equal(f.finishes,1);await f.runPhase(async()=>f.operation.ensure_current());
 assert.ok(f.events.indexOf('actual-auth-apply')<f.events.indexOf('one-use-retain'));
 assert.ok(f.events.indexOf('native-return')<f.events.indexOf('native-finish'));await assert.rejects(f.operation.run(),/unavailable/);
 for(const name of ['free','retire','release','releaseAfterRecoveryRetired','nativeIoQuiescent','row','key','receipt'])assert.equal(f.operation[name],undefined);
});
// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
test('cancel while auth is held still applies actual matched phase before denying private continuation',async()=>{
 const f=fixture(),run=f.operation.run(),refused=assert.rejects(run,/cancelled/);await tick();f.operation.cancel();f.acquire.resolve();await refused;
 assert.ok(f.events.includes('actual-auth-apply'));assert.equal(f.storeBegins,0);assert.equal(f.finishes,0);await assert.rejects(f.operation.run(),/unavailable/);
});
// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,chats.persistence.client-encrypted
test('unknown acquisition never constructs or releases a native store or permits retry',async()=>{
 const f=fixture(),run=f.operation.run(),refused=assert.rejects(run,/auth_io_unknown/);await tick();f.acquire.reject(Error('auth_io_unknown'));await refused;
 assert.equal(f.storeBegins,0);assert.equal(f.finishes,0);assert.throws(()=>f.operation.ensure_current(),/unavailable/);await assert.rejects(f.operation.run(),/unavailable/);
});
for(const negative of ['cancel','profile','unknown']){
 // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,chats.persistence.client-encrypted
 test('actual held native IO stays awaited and no stored result follows '+negative,async()=>{
  const f=fixture(),run=f.operation.run(),refused=assert.rejects(run,negative==='unknown'?/native_unknown/:/cancelled/);await tick();f.acquire.resolve();await tick();
  assert.equal(f.storeBegins,1);assert.equal(f.finishes,0);
  if(negative==='cancel')f.operation.cancel();else if(negative==='profile')f.expire();
  if(negative==='unknown')f.nativeIO.reject(Error('native_unknown'));else f.nativeIO.resolve();await refused;
  assert.equal(f.finishes,0);assert.throws(()=>f.operation.ensure_current(),/unavailable/);await assert.rejects(f.operation.run(),/unavailable/);
 });
}
for(const flag of ['noReadTerminal','noNativeTerminal']){
 // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,sync.client.shared-rust-policy
 test('missing actual narrow terminal refuses without freeing resources: '+flag,async()=>{
  const f=fixture({[flag]:true}),run=f.operation.run(),refused=assert.rejects(run,/unavailable/);await tick();f.acquire.resolve();await tick();
  if(flag==='noNativeTerminal')f.nativeIO.resolve();await refused;assert.throws(()=>f.operation.ensure_current(),/unavailable/);
  assert.equal(f.storeBegins,flag==='noReadTerminal'?0:1);await assert.rejects(f.operation.run(),/unavailable/);
 });
}
