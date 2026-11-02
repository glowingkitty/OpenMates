// contract-test-file: tooling
/** Actual thin scheduler, inert resource doubles; not Rust/native runtime proof.
 * Pending Main ownership is retained through success, cancellation and unknown.
 * The Personal scheduler remains unchanged and is loaded as the dependency.
 */
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ts=require(process.env.OPENMATES_TEST_TYPESCRIPT||'typescript');
const root=process.env.OPENMATES_TEST_RUST_CORE_ROOT||path.resolve(__dirname,'..');
const loaded=new Map();function load(name){if(loaded.has(name))return loaded.get(name);const out={};loaded.set(name,out);new vm.Script('(function(exports,require){'+ts.transpileModule(fs.readFileSync(path.join(root,name+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText+'})').runInThisContext()(out,id=>{assert.ok(id.startsWith('./'));return load(id.slice(2))});return out;}
const {OwnedMainMetadataStore}=load('mainMetadataStoreOperation'),{OwnedRecoveredReplyStore}=load('recoveredReplyStoreOperation'),deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};},tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({missingTerminal=false}={}){
 const client={},io=deferred(),events=[];let phase=false,negative=false,metadataComplete=false,replyComplete=false,freed=0,finished=0;
 const check=c=>{assert.equal(c,client);assert.equal(phase,true);if(negative)throw Error('cancelled');};
 const stored={ensure_current:check,free(){freed++;}},terminal={native_io_quiescent:()=>true,free(){freed++;}};
 const meta=new OwnedMainMetadataStore(client,{ensure_current:check,begin_main_metadata_local_store(c){check(c);return{ensure_current:check,async drive(){assert.equal(phase,false);metadataComplete=true;},finish(c){check(c);assert.equal(metadataComplete,true);return stored;},terminal:()=>terminal,free(){freed++;}}}}, {cancel(){negative=true}},runPhase,()=>{if(negative)throw Error('cancelled')});
 const nativeControl={ensure_current:check,cancel(){negative=true;events.push('native-negative')},free(){freed++;}};
 const recovery={ensure_current:check,begin_recovered_reply_local_store(c,actual){check(c);assert.equal(actual,stored);events.push('reply-begin');return{ensure_current:check,control:()=>nativeControl,async drive(){assert.equal(phase,false);events.push('reply-drive');await io.promise;replyComplete=true;if(negative)throw Error('cancelled');},finish(c){check(c);assert.equal(replyComplete,true);finished++;return{ensure_current:check,free(){freed++;}}},terminal:()=>missingTerminal?undefined:terminal,free(){freed++;}}}};
 const reply=new OwnedRecoveredReplyStore(client,recovery,meta,{cancel(){negative=true;events.push('original-negative')}},runPhase,()=>{if(negative)throw Error('cancelled')});
 async function runPhase(fn){assert.equal(phase,false);phase=true;try{return await fn();}finally{phase=false;}}
 return{meta,reply,io,events,runPhase,expire(){negative=true},get freed(){return freed},get finished(){return finished}};
}
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
test('reply cannot begin without same completed metadata proof; no native dispatch or retry',async()=>{
 const f=fixture();await assert.rejects(f.reply.run(),/unavailable/);assert.deepEqual(f.events,[]);await f.meta.run();await assert.rejects(f.reply.run(),/unavailable/);assert.equal(f.freed,0);
});
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
test('same metadata opaque proof precedes actual detached reply drive and typed partial finish',async()=>{
 const f=fixture();await f.meta.run();const running=f.reply.run();await tick();assert.deepEqual(f.events,['reply-begin','reply-drive']);assert.equal(f.finished,0);f.io.resolve();await running;assert.equal(f.finished,1);assert.equal(f.freed,0);await f.runPhase(async()=>f.reply.ensure_current());
 for(const name of ['free','retire','releaseAfterRecoveryRetired','nativeIoQuiescent'])assert.equal(f.reply[name],undefined);await assert.rejects(f.reply.run(),/unavailable/);
});
// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,chats.persistence.client-encrypted
test('separate native control cancels a held original invocation without freeing or finishing',async()=>{
 const f=fixture();await f.meta.run();const run=f.reply.run(),refused=assert.rejects(run,/cancelled/);await tick();f.reply.cancel();assert.deepEqual(f.events.slice(-2),['native-negative','original-negative']);assert.equal(f.finished,0);assert.equal(f.freed,0);f.io.resolve();await refused;assert.equal(f.finished,0);assert.equal(f.freed,0);
});
// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,chats.persistence.client-encrypted
test('unknown original reply IO retains all resources, no proof event or rearm',async()=>{
 const f=fixture();await f.meta.run();const run=f.reply.run(),refused=assert.rejects(run,/unknown/);await tick();f.io.reject(Error('unknown'));await refused;assert.equal(f.finished,0);assert.equal(f.freed,0);assert.throws(()=>f.reply.ensure_current(),/unavailable/);await assert.rejects(f.reply.run(),/unavailable/);
});
// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,chats.persistence.client-encrypted
test('missing actual native terminal cannot publish a reply proof despite finish return',async()=>{
 const f=fixture({missingTerminal:true});await f.meta.run();const run=f.reply.run(),refused=assert.rejects(run,/unavailable/);await tick();f.io.resolve();await refused;assert.equal(f.freed,0);assert.throws(()=>f.reply.ensure_current(),/unavailable/);
});
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,chats.persistence.client-encrypted
test('original scope revocation after native IO prevents reply finish and metadata reuse',async()=>{
 const f=fixture();await f.meta.run();const run=f.reply.run(),refused=assert.rejects(run,/cancelled/);await tick();f.expire();f.io.resolve();await refused;assert.equal(f.finished,0);assert.equal(f.freed,0);assert.throws(()=>f.meta.ensure_current(),/cancelled/);
});
