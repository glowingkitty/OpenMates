// contract-test-file: tooling
// Actual Host/adapters with explicit native-event doubles only. No product,
// browser, IndexedDB, Worker, WASM, network or inference execution.
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{webcrypto}=require('node:crypto'),ts=require('typescript');
const core=path.resolve(__dirname,'../..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'native-chat-io-pure-'));
for(const n of ['ownedLocalReadProtocol','browserAdapters','profileCacheProtocol','workerHost','protocol','browserCacheProtocol','sendProtocol','savedReadProtocol','credentialCasProtocol','browserCredentialStorage','browserDraftProtocol','browserDraftTransport']) fs.writeFileSync(path.join(tmp,n+'.js'),ts.transpileModule(fs.readFileSync(path.join(core,n+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);
process.on('exit',()=>fs.rmSync(tmp,{recursive:true,force:true}));
const {loadAdapters,FixtureNativeEvent}=require('./nativeEventRealm.cjs');
const api=loadAdapters(path.join(tmp,'browserAdapters.js'));
loadAdapters(path.join(tmp,'browserDraftTransport.js'));
const {BrowserCoreWorkerHost}=require(path.join(tmp,'workerHost.js'));
const OWNER='11111111-1111-4111-8111-111111111111',CHAT='22222222-2222-4222-8222-222222222222';
const held=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
class NativeDouble extends EventTarget {
 listeners=new Map();
 addEventListener(type,fn,opts){super.addEventListener(type,fn,opts);const set=this.listeners.get(type)??new Set();set.add(fn);this.listeners.set(type,set);}
 removeEventListener(type,fn,opts){super.removeEventListener(type,fn,opts);this.listeners.get(type)?.delete(fn);}
 native(type,data,target=this){const event=new FixtureNativeEvent(type,data,target);for(const fn of [...(this.listeners.get(type)??[])])fn(event);return event;}
}
class Tx extends NativeDouble {error=null;abortCalls=0;abort(){this.abortCalls++;}objectStore(){return{clear(){}};}}
class Database extends NativeDouble {version=1;name='chats_db';objectStoreNames={contains:()=>true};created=[];closed=false;transaction(){const tx=new Tx();this.created.push(tx);return tx;}close(){this.closed=true;}}
class Factory {requests=[];open(name){assert.equal(name,'chats_db');const request=new NativeDouble();request.result=new Database();this.requests.push(request);return request;}}
class WorkerDouble extends NativeDouble {messages=[];terminated=false;postMessage(body){this.messages.push(body);}terminate(){this.terminated=true;}}
async function fixture({syntheticRestore=false}={}){
 const worker=new WorkerDouble(),factory=new Factory();
 const issuer=api.openNativeRustChatIOFactory(worker,factory,new FixtureNativeEvent('message',{version:1,ready:true},worker));
 const host=new BrowserCoreWorkerHost(worker,undefined,OWNER,issuer),controller=new AbortController();
 const key=await webcrypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);globalThis.CryptoKey=key.constructor;
 const restore=host.request({operation:'restore_existing',key,profile:{principal:OWNER,hashedEmail:null,userEmailSalt:null},persistence:'memory_only'},controller.signal);
 const message=worker.messages.at(-1),status={handle:'original-native-root',principal:OWNER,generation:1,persistence:'memory_only',localReadOnly:false};
 const response={version:1,id:message.id,ok:true,status};
 if(syntheticRestore)worker.dispatchEvent(new MessageEvent('message',{data:response}));else worker.native('message',response);
 await restore;let current=true;const guard=()=>{if(!current)throw Error('invalidated_snapshot');};
 const legacy=new Database(),gate=new api.LegacyChatDatabaseGate();gate.bind(legacy);await gate.retireAndDrain(legacy,guard);
 return{worker,factory,host,gate,guard,legacy,controller,status,issuer,invalidate(){current=false;},root(){return host.openChatIORoot(factory,guard);}};
}
function connection(f,lease){const request=api.createRustChatOpenRequest(lease,f.factory);request.native('success');return request.result;}

module.exports={api,BrowserCoreWorkerHost,fixture,connection,held,tick,Factory,Database,Tx,WorkerDouble,NativeDouble,OWNER,CHAT,tmp,core,ts,FixtureNativeEvent};
