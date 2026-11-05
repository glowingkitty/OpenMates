// contract-test-file: tooling
// INERT protocol IO doubles only. Native root/event gates are fixture-realm
// imports; these tests prove no browser/IDB/physical durability/native receipt.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const toolRequire=require('node:module').createRequire(process.env.OPENMATES_TOOLING_PACKAGE||__filename);
const ts=toolRequire('typescript');
const OWNER='11111111-1111-4111-8111-111111111111',OP='22222222-2222-4222-8222-222222222222';
const KEY='openmates_rust_pending_recovery_v1',OLD='{"version":1,"ciphertext":"old-encrypted-record"}',NEXT='{"version":1,"ciphertext":"new-encrypted-record"}';
const brands=new WeakSet(),requests=new WeakMap(),databases=new WeakMap(),transactions=new WeakMap(),stores=new WeakMap(),factories=new WeakMap(),roots=new WeakMap();
const target=Object.getOwnPropertyDescriptor(Event.prototype,'target').get;
function emit(value,kind,native=true){const event=new Event(kind);if(native)brands.add(event);value.dispatchEvent(event);}
class Request extends EventTarget {constructor(tx=null){super();requests.set(this,{value:undefined,tx});}get result(){return requests.get(this).value;}get transaction(){return requests.get(this).tx;}}
class Database extends EventTarget {
 constructor(data){super();databases.set(this,{data,closed:0,tx:[],name:'user_db',hasStore:true});}
 get name(){return databases.get(this).name;}get objectStoreNames(){return{contains:name=>name==='user_data'&&databases.get(this).hasStore};}
 transaction(names,mode){assert.deepEqual([...names],['user_data']);const tx=new Transaction(this,mode);databases.get(this).tx.push(tx);return tx;}
 close(){databases.get(this).closed++;}
}
class Transaction extends EventTarget {
 constructor(db,mode){super();transactions.set(this,{db,mode,data:new Map(databases.get(db).data),requests:[],abortRequested:0,ended:false});}
 objectStore(name){assert.equal(name,'user_data');return new Store(this);}
 abort(){const state=transactions.get(this);if(state.ended)throw Error('already_terminal');state.abortRequested++;}
 complete(){const state=transactions.get(this);state.ended=true;if(state.mode==='readwrite'){const data=databases.get(state.db).data;data.clear();for(const[k,v]of state.data)data.set(k,v);}emit(this,'complete');this.oncomplete?.();}
 abortTerminal(){transactions.get(this).ended=true;emit(this,'abort');}
}
class Store {
 constructor(tx){stores.set(this,tx);}get keyPath(){return null;}
 get(key){return queued(this,'get',key);}getKey(key){return queued(this,'getKey',key);}put(value,key){return queued(this,'put',key,value);}
}
function queued(store,kind,key,value){const tx=stores.get(store),request=new Request(tx);transactions.get(tx).requests.push({request,kind,key,value});return request;}
class Factory {constructor(data){factories.set(this,{data,opens:[]});}open(name){assert.equal(name,'user_db');const state=factories.get(this),request=new Request(),db=new Database(state.data);requests.get(request).value=db;state.opens.push(request);return request;}}
const source=fs.readFileSync(path.join(__dirname,'..','browserRecoveryCheckpointStorage.ts'),'utf8');
const javascript=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},reportDiagnostics:true});
assert.equal((javascript.diagnostics||[]).length,0);
const context=vm.createContext({module:{exports:{}},exports:{},TextEncoder,AbortSignal,EventTarget,Event,
 IDBFactory:Factory,IDBRequest:Request,IDBDatabase:Database,IDBTransaction:Transaction,IDBObjectStore:Store,
 require:name=>{assert.equal(name,'./browserAdapters');return{
  assertRustChatIORootFactory:(root,factory)=>{const state=roots.get(root);if(!state?.active||state.factory!==factory)throw Error('fixture_root_rejected');},
  isNativeChatIOEvent:(event,value)=>brands.has(event)&&target.call(event)===value,
 };}});context.exports=context.module.exports;vm.runInContext(javascript.outputText,context,{filename:'inert-checkpoint-storage.js'});
const{createBrowserRecoveryCheckpointStorage}=context.module.exports,make=vm.runInContext('(value)=>JSON.parse(value)',context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function effect(operation='compare_and_put',expected=null){return make(JSON.stringify(operation==='read'?{version:1,operation,operationId:OP,owner:OWNER}:{version:1,operation,operationId:OP,owner:OWNER,expected,next:NEXT}));}
function fixture(value=effect(),previous=null){
 const data=new Map([['id',OWNER],['legacy-unrelated',{encrypted:'must-stay'}]]);if(previous!==null)data.set(KEY,previous);
 const factory=new Factory(data),root=Object.freeze({fixtureOnly:true}),state={current:true};roots.set(root,{factory,active:true});
 const storage=createBrowserRecoveryCheckpointStorage({factory,root,current:()=>{if(!state.current)throw Error('fixture_stale');}}),signal=new AbortController();
 const pending=storage.execute(value,signal.signal);let settled=false;void pending.then(()=>{settled=true;},()=>{settled=true;});
 const open=factories.get(factory).opens[0],db=open?requests.get(open).value:null;
 const f={data,factory,root,state,storage,signal,pending,value,open,db,get settled(){return settled;},get tx(){return databases.get(db).tx[0];},
  opened(){emit(open,'success');return f.tx;},
  step(){const state=transactions.get(f.tx),next=state.requests.shift();assert.ok(next,'actual fixture request expected');
   if(next.kind==='put'){assert.equal(next.key,KEY);state.data.set(next.key,next.value);requests.get(next.request).value=next.key;}
   else requests.get(next.request).value=next.kind==='getKey'?(state.data.has(next.key)?next.key:undefined):state.data.get(next.key);
   emit(next.request,'success');return next;
  },all(){while(transactions.get(f.tx).requests.length)f.step();},
 };return f;
}
test('full put/readback must precede real fixture terminal; oneuse same-effect brand preserves unrelated rows',async()=>{
 const f=fixture();f.opened();f.all();assert.equal(f.settled,false);assert.equal(f.data.has(KEY),false);
 f.tx.oncomplete=()=>{};f.tx.complete();const token=await f.pending;
 assert.equal(f.data.get(KEY),NEXT);assert.deepEqual(f.data.get('legacy-unrelated'),{encrypted:'must-stay'});
 assert.throws(()=>structuredClone(token));assert.equal(f.storage.consume(token,f.value),NEXT);
 assert.throws(()=>f.storage.consume(token,f.value),/unavailable/);assert.equal(databases.get(f.db).closed,1);await f.storage.close();
});
test('existing exact predecessor CAS succeeds; conflict waits actual abort and leaves full prior data',async()=>{
 const good=fixture(effect('compare_and_put',OLD),OLD);good.opened();good.all();good.tx.complete();assert.equal(good.storage.consume(await good.pending,good.value),NEXT);
 const bad=fixture(effect('compare_and_put',null),OLD);bad.opened();bad.all();assert.ok(transactions.get(bad.tx).abortRequested);await tick();assert.equal(bad.settled,false);
 bad.tx.abortTerminal();await assert.rejects(bad.pending,/conflict/);assert.equal(bad.data.get(KEY),OLD);await bad.storage.close();
});
test('owner mismatch and malformed existing value never write and wait actual transaction abort',async()=>{
 for(const scenario of ['owner','record']){const f=fixture(effect(),scenario==='record'?{ciphertext:'not-full-record-string'}:null);if(scenario==='owner')f.data.set('id','other-owner');
  f.opened();f.all();assert.equal(f.settled,false);assert.ok(transactions.get(f.tx).abortRequested);f.tx.abortTerminal();await assert.rejects(f.pending,/unavailable/);assert.notEqual(f.data.get(KEY),NEXT);}
});
test('request error is not terminal and a forged complete cannot mint a physical token',async()=>{
 const a=fixture();a.opened();const failed=transactions.get(a.tx).requests[0].request;emit(failed,'error');await tick();assert.equal(a.settled,false);a.tx.abortTerminal();await assert.rejects(a.pending,/unavailable/);
 const b=fixture();b.opened();b.all();emit(b.tx,'complete',false);await tick();assert.equal(b.settled,false);b.tx.abortTerminal();await assert.rejects(b.pending,/unavailable/);assert.equal(b.data.has(KEY),false);
});
test('native getter ignores result shadowing; read requires actual complete and opaque object identity',async()=>{
 const f=fixture(effect('read'),OLD);Object.defineProperty(f.open,'result',{value:{name:'wrong'}});f.opened();f.all();assert.equal(f.settled,false);f.tx.complete();const token=await f.pending;
 assert.throws(()=>f.storage.consume(token,effect('read')),/unavailable/);assert.throws(()=>f.storage.consume(token,f.value),/unavailable/);
 const g=fixture(effect('read'));g.opened();g.all();g.tx.complete();assert.equal(g.storage.consume(await g.pending,g.value),null);
});
test('cancel and close synchronously revoke but drain only actual abort or racing commit',async()=>{
 for(const complete of [false,true]){const f=fixture();f.opened();f.all();f.signal.abort();let drained=false;const closing=f.storage.close().then(()=>{drained=true;});
  assert.ok(transactions.get(f.tx).abortRequested);await tick();assert.equal(drained,false);assert.equal(f.settled,false);
  if(complete)f.tx.complete();else f.tx.abortTerminal();await assert.rejects(f.pending,/cancelled/);await closing;assert.equal(drained,true);}
 const late=fixture();let drained=false;const close=late.storage.close().then(()=>{drained=true;});await tick();assert.equal(drained,false);late.opened();await assert.rejects(late.pending,/unavailable/);await close;assert.equal(databases.get(late.db).tx.length,0);
});
test('closed own-data framing rejects accessors/unknown keys/budget overflow before any native open',async()=>{
 const valid=fixture();valid.opened();valid.all();valid.tx.complete();await valid.pending;
 for(const value of [make(JSON.stringify({...effect(),unknown:true})),make(JSON.stringify({...effect(),next:'x'.repeat(32*1024*1024+1)}))]){
  const count=factories.get(valid.factory).opens.length;await assert.rejects(valid.storage.execute(value,valid.signal.signal),/unavailable/);assert.equal(factories.get(valid.factory).opens.length,count);}
 const accessor=effect();Object.defineProperty(accessor,'owner',{get:()=>{throw Error('must-not-run');},enumerable:true});await assert.rejects(valid.storage.execute(accessor,valid.signal.signal),/unavailable/);
});
test('guard invalidation remains refused even if restored before actual native terminal',async()=>{
 const f=fixture();f.opened();f.state.current=false;f.step();f.state.current=true;assert.equal(f.settled,false);f.tx.complete();await assert.rejects(f.pending,/unavailable/);
});
test('put success is insufficient: a different FULL readback refuses before actual abort',async()=>{
 const f=fixture();f.opened();f.step();f.step();const put=f.step();assert.equal(put.kind,'put');
 const next=transactions.get(f.tx).requests[0];assert.equal(next.kind,'get');assert.equal(next.key,KEY);
 transactions.get(f.tx).data.set(KEY,'different-written-record');f.step();assert.ok(transactions.get(f.tx).abortRequested);await tick();assert.equal(f.settled,false);
 f.tx.abortTerminal();await assert.rejects(f.pending,/conflict/);assert.equal(f.data.has(KEY),false);
});
test('upgrade/open failure and versionchange require exact original terminal drain with no schema creation',async()=>{
 const f=fixture();const upgrade=new Transaction(f.db,'versionchange');requests.get(f.open).tx=upgrade;emit(f.open,'upgradeneeded');assert.ok(transactions.get(upgrade).abortRequested);
 emit(f.open,'error');await tick();assert.equal(f.settled,false);upgrade.abortTerminal();await assert.rejects(f.pending,/unavailable/);assert.equal(databases.get(f.db).tx.length,0);assert.equal(databases.get(f.db).closed,1);
 const g=fixture();g.opened();emit(g.db,'versionchange');await tick();assert.equal(g.settled,false);assert.ok(transactions.get(g.tx).abortRequested);g.tx.abortTerminal();await assert.rejects(g.pending,/unavailable/);
});
