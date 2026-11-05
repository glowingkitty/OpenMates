// contract-test-file: tooling
// INERT protocol IO doubles only. Native root/event gates are fixture-realm
// imports; these tests prove no browser/IDB/physical durability/native receipt.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
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

// Fixture-only native port/event realm. Production has no injection/trust flag.
const events=new WeakMap(),ports=new WeakMap();let intoPage=value=>value;
function delivered(to,data){const event=new Event('message');brands.add(event);events.set(event,data);to.dispatchEvent(event);}
class Port extends EventTarget {
 constructor(){super();ports.set(this,{peer:null,started:false,closed:false,queue:[],fail:false});}
 postMessage(data){const from=ports.get(this);if(!from||from.closed||from.fail)throw Error('fixture_port_closed');const peer=from.peer,state=ports.get(peer);if(!state||state.closed)return;const actual=intoPage(data);queueMicrotask(()=>{if(state.closed)return;if(state.started)delivered(peer,actual);else state.queue.push(actual);});}
 start(){const state=ports.get(this);if(!state)throw Error('foreign_port');state.started=true;for(const data of state.queue.splice(0))queueMicrotask(()=>{if(!state.closed)delivered(this,data);});}
 close(){const state=ports.get(this);if(!state)throw Error('foreign_port');state.closed=true;}
}
class Channel {constructor(){this.port1=new Port();this.port2=new Port();ports.get(this.port1).peer=this.port2;ports.get(this.port2).peer=this.port1;}}
class WorkerFixture extends EventTarget {
 constructor(){super();this.messages=[];this.wire=[];this.remote=null;}
 postMessage(data,options){const transfer=Array.isArray(options)?options:options?.transfer;this.messages.push(data);if(transfer?.length){assert.equal(transfer.length,1);assert.equal(this.remote,null);this.remote=transfer[0];this.remote.addEventListener('message',event=>this.wire.push(events.get(event)));this.remote.start();}}
 send(data){assert.ok(this.remote);this.remote.postMessage(data);}
}
function checkRoot(root,factory){const state=roots.get(root);if(!state?.active||state.factory!==factory)throw Error('invalidated_snapshot');state.current?.();if(!state.active)throw Error('invalidated_snapshot');return state;}
const inventoryFixtures=new WeakMap();
const adapters={
 assertRustChatIOPortsRoot:(ports,root,factory)=>{const entry=inventoryFixtures.get(ports);checkRoot(root,factory);if(!entry||entry.root!==root||entry.factory!==factory)throw Error('invalidated_snapshot');ports.current();checkRoot(root,factory);},
 assertRustChatIORootFactory:(root,factory)=>{checkRoot(root,factory);},
 assertNativeRustChatIORootBinding:(root,issuer,worker,factory)=>{const state=checkRoot(root,factory);if(state.issuer!==issuer||state.worker!==worker)throw Error('invalidated_snapshot');},
 isNativeChatIOEvent:(event,value)=>brands.has(event)&&target.call(event)===value,
 readNativeChatIOMessage:(event,value)=>{if(!brands.has(event)||target.call(event)!==value||event.type!=='message'||!events.has(event))throw Error('invalidated_snapshot');return events.get(event);},
};
const context=vm.createContext({TextEncoder,AbortSignal,AbortController,EventTarget,Event,MessagePort:Port,MessageChannel:Channel,Worker:WorkerFixture,crypto:require('node:crypto').webcrypto,
 IDBFactory:Factory,IDBRequest:Request,IDBDatabase:Database,IDBTransaction:Transaction,IDBObjectStore:Store});
const make=vm.runInContext('(value)=>JSON.parse(value)',context);intoPage=value=>make(JSON.stringify(value));
function load(name,requireModule){const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../..',name+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const execute=vm.runInContext('(function(module,exports,require){'+code+'\n})',context);const module={exports:{}};execute(module,module.exports,requireModule);return module.exports;}
const physical=load('browserRecoveryCheckpointStorage',name=>{assert.equal(name,'./browserAdapters');return adapters;});
const api=load('browserRecoveryTransport',name=>name==='./browserAdapters'?adapters:name==='./browserRecoveryCheckpointStorage'?physical:name==='./browserDraftInventoryIO'?{createBrowserDraftInventoryIO:(ports,current)=>{const entry=inventoryFixtures.get(ports);if(!entry)throw Error('original_inventory_fixture_required');return entry.create(current);}}:name==='./protocol'?{MAX_PENDING_REQUESTS:100}:(()=>{throw Error(name)})());
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup(){const data=new Map([['id',OWNER],['legacy-unrelated',{encrypted:'unchanged'}]]),factory=new Factory(data),worker=new WorkerFixture(),root=Object.freeze({fixtureOnly:true}),issuer=Object.freeze({fixtureOnly:true});roots.set(root,{factory,worker,issuer,active:true});
 const bootstrap=api.createBrowserRecoveryBootstrap(worker,factory);api.postBrowserRecoveryBootstrap(bootstrap,{version:1,operation:'bootstrap_existing_key'});api.bindBrowserRecoveryRoot(bootstrap,issuer,root);
 return{api,physical,bootstrap,data,factory,worker,root,issuer,get contextId(){return worker.wire.find(v=>v?.admitted)?.admitted.contextId;},send(value){worker.send(value);},
 open(index=0){const request=factories.get(factory).opens[index];assert.ok(request,'native-open fixture expected');emit(request,'success');const db=requests.get(request).value;return{db,get tx(){return databases.get(db).tx[0];}};},
 step(tx){const state=transactions.get(tx),next=state.requests.shift();assert.ok(next,'actual IO fixture request');if(next.kind==='put'){state.data.set(next.key,next.value);requests.get(next.request).value=next.key;}else requests.get(next.request).value=next.kind==='getKey'?(state.data.has(next.key)?next.key:undefined):state.data.get(next.key);emit(next.request,'success');return next;},
 all(tx){while(transactions.get(tx).requests.length)this.step(tx);},invalidate(){roots.get(root).active=false;},
 };}
function effect(operation='compare_and_put',id=OP,expected=null){return operation==='read'?{version:1,operation,operationId:id,owner:OWNER}:{version:1,operation,operationId:id,owner:OWNER,expected,next:NEXT};}
function request(f,sequence=1,plan=effect()){f.send({version:1,contextId:f.contextId,sequence,operationId:plan.operationId,effect:plan});}
async function closeFixture(f){f.send({version:1,contextId:f.contextId,close:true});await tick();await api.closeAndDrainBrowserRecoveryTransport(f.bootstrap);}
module.exports={inventoryFixtures,api,setup,effect,request,closeFixture,tick,emit,ports,events,brands,factories,requests,databases,transactions,roots,OWNER,OP,KEY,OLD,NEXT,Port,WorkerFixture,make};
