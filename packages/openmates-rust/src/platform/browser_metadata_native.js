// Prototype only. Fixed app configuration is module-owned, never a frame grant.
import {captureMetadataConfiguredBackend,readMetadataConfiguredBackend} from 'openmates-native-metadata-configuration';
const get=(p,n)=>Object.getOwnPropertyDescriptor(p,n)?.get;
const target=get(Event.prototype,'target'),eventType=get(Event.prototype,'type'),messageData=get(MessageEvent.prototype,'data'),messagePorts=get(MessageEvent.prototype,'ports');
const idb=typeof WorkerGlobalScope==='undefined'?undefined:get(WorkerGlobalScope.prototype,'indexedDB');
const reqResult=get(IDBRequest.prototype,'result'),reqTx=get(IDBRequest.prototype,'transaction');
const dbName=get(IDBDatabase.prototype,'name'),dbVersion=get(IDBDatabase.prototype,'version'),dbStores=get(IDBDatabase.prototype,'objectStoreNames');
const keyPath=get(IDBObjectStore.prototype,'keyPath'),txDB=get(IDBTransaction.prototype,'db'),txMode=get(IDBTransaction.prototype,'mode'),storeName=get(IDBObjectStore.prototype,'name');
const open=IDBFactory.prototype.open,cmp=IDBFactory.prototype.cmp,begin=IDBDatabase.prototype.transaction,dbClose=IDBDatabase.prototype.close;
const store=IDBTransaction.prototype.objectStore,read=IDBObjectStore.prototype.get,put=IDBObjectStore.prototype.put,abort=IDBTransaction.prototype.abort;
const add=EventTarget.prototype.addEventListener,remove=EventTarget.prototype.removeEventListener;
const contexts=new WeakMap(),operations=new WeakMap(),receipts=new WeakMap();let captured;
const MAX=4*1024*1024,uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v);
const opaque=()=>Object.freeze({checkpoint:()=>undefined});
const own=(v,keys)=>v!==null&&typeof v==='object'&&Object.getPrototypeOf(v)===Object.prototype&&Reflect.ownKeys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k))&&Object.values(Object.getOwnPropertyDescriptors(v)).every(d=>'value'in d&&d.enumerable);
const trusted=(e,t,k)=>{try{return target.call(e)===t&&eventType.call(e)===k&&e.isTrusted===true;}catch{return false;}};
const state=c=>{const s=contexts.get(c);if(!s)throw Error('unavailable');return s;};
const check=s=>{if(s.revoked||s.failed)throw Error('cancelled');};
function revoke(s){if(s.revoked)return;s.revoked=true;for(const fn of [...s.aborters]){try{fn();}catch{}}try{s.notify?.();}catch{}}
function on(t,k,f){add.call(t,k,f);return()=>remove.call(t,k,f);}
function plain(v,seen=new Set()){
 if(v===null||typeof v==='string'||typeof v==='boolean')return v;
 if(typeof v==='number'&&Number.isFinite(v)&&!Object.is(v,-0))return v;
 if(typeof v!=='object'||seen.has(v))throw Error('unavailable');seen.add(v);
 let out;
 if(Array.isArray(v)){
  if(Reflect.ownKeys(v).some(k=>k!=='length'&&!(typeof k==='string'&&/^(0|[1-9][0-9]*)$/.test(k))))throw Error('unavailable');
  out=[];for(let i=0;i<v.length;i++){const d=Object.getOwnPropertyDescriptor(v,String(i));if(!d||!('value'in d))throw Error('unavailable');out.push(plain(d.value,seen));}
 }else{
  if(Object.getPrototypeOf(v)!==Object.prototype)throw Error('unavailable');out={};
  for(const k of Reflect.ownKeys(v).sort()){const d=Object.getOwnPropertyDescriptor(v,k);if(typeof k!=='string'||!d||!('value'in d)||!d.enumerable)throw Error('unavailable');Object.defineProperty(out,k,{value:plain(d.value,seen),enumerable:true,writable:true,configurable:true});}
 }
 return out;
}
function encoded(v){const text=JSON.stringify(plain(v));if(new TextEncoder().encode(text).byteLength>MAX)throw Error('unavailable');return text;}
async function database(s,kind){
 check(s);const field=kind==='user_db'?'profileDB':'chatDB';if(s[field])return s[field];
 const actual=await new Promise((resolve,reject)=>{
  const request=open.call(s.factory,kind);let upgraded=false;
  on(request,'upgradeneeded',e=>{if(!trusted(e,request,'upgradeneeded'))return;upgraded=true;try{const tx=reqTx.call(request);if(tx)abort.call(tx);}catch{}});
  on(request,'blocked',e=>{if(!trusted(e,request,'blocked'))return;/* Real open stays pending; no completion from blocked/cancel. */});
  on(request,'error',e=>{if(trusted(e,request,'error'))reject(Error('unavailable'));});
  on(request,'success',e=>{if(!trusted(e,request,'success'))return;const db=reqResult.call(request);if(upgraded||s.revoked||s.failed){try{dbClose.call(db);}catch{}reject(Error('cancelled'));return;}resolve(db);});
 });
 if(dbName.call(actual)!==kind||!Number.isSafeInteger(dbVersion.call(actual))||dbVersion.call(actual)<1){dbClose.call(actual);throw Error('unavailable');}
 const wanted=kind==='user_db'?'user_data':'chats';if(!dbStores.call(actual).contains(wanted)){dbClose.call(actual);throw Error('unavailable');}
 const negative=e=>{if(trusted(e,actual,eventType.call(e))){revoke(s);try{dbClose.call(actual);}catch{}}};
 on(actual,'versionchange',negative);on(actual,'close',negative);s[field]=actual;return actual;
}
function ownerGuard(s,db,expected){
 let keep=true,first=false,owner,resolveReady,rejectReady,resolveEnd,rejectEnd;
 const ready=new Promise((a,b)=>{resolveReady=a;rejectReady=b;}),terminal=new Promise((a,b)=>{resolveEnd=a;rejectEnd=b;});void ready.catch(()=>{});void terminal.catch(()=>{});
 const tx=begin.call(db,['user_data'],'readonly');let object;
 const cancel=()=>{keep=false;try{abort.call(tx);}catch{}};s.aborters.add(cancel);
 const ended=(e,ok)=>{if(!trusted(e,tx,ok?'complete':'abort'))return;s.aborters.delete(cancel);if(!first)rejectReady(Error('unavailable'));if(ok&&first)resolveEnd();else rejectEnd(Error('cancelled'));};
 on(tx,'complete',e=>ended(e,true));on(tx,'abort',e=>ended(e,false));on(tx,'error',()=>{});
 function next(){
  let request;try{request=read.call(object,'id');if(reqTx.call(request)!==tx)throw Error('unavailable');}catch(error){rejectReady(error);cancel();return;}
  on(request,'error',e=>{if(trusted(e,request,'error'))cancel();});
  on(request,'success',e=>{
   if(!trusted(e,request,'success'))return;
   try{check(s);const actual=reqResult.call(request);if(!uuid(actual)||(expected!==undefined&&actual!==expected))throw Error('cancelled');
    if(!first){owner=actual;first=true;resolveReady(actual);}else if(actual!==owner)throw Error('cancelled');
    if(keep)next();
   }catch{rejectReady(Error('cancelled'));cancel();}
  });
 }
 try{object=store.call(tx,'user_data');if(txDB.call(tx)!==db||txMode.call(tx)!=='readonly'||storeName.call(object)!=='user_data'||keyPath.call(object)!==null)throw Error('unavailable');next();}catch(error){rejectReady(error);cancel();}
 return{ready,terminal,stop(){keep=false;},abort:cancel};
}
function rowTransaction(s,db,plan,write){
 return new Promise((resolve,reject)=>{
  check(s);let value,done=false,failure;
  const tx=begin.call(db,['chats'],write?'readwrite':'readonly');let object;
  const cancel=()=>{try{abort.call(tx);}catch{}};s.aborters.add(cancel);
  const fail=error=>{failure=error;cancel();};
  on(tx,'complete',e=>{if(!trusted(e,tx,'complete'))return;s.aborters.delete(cancel);if(!done||failure||s.revoked||s.failed)reject(failure||Error('cancelled'));else resolve(value);});
  on(tx,'abort',e=>{if(!trusted(e,tx,'abort'))return;s.aborters.delete(cancel);reject(failure||Error('cancelled'));});on(tx,'error',()=>{});
  try{
   object=store.call(tx,'chats');if(txDB.call(tx)!==db||txMode.call(tx)!==(write?'readwrite':'readonly')||storeName.call(object)!=='chats'||keyPath.call(object)!=='chat_id')throw Error('unavailable');
   const request=read.call(object,plan.chat_id);if(reqTx.call(request)!==tx)throw Error('unavailable');
   on(request,'error',e=>{if(trusted(e,request,'error'))fail(Error('unavailable'));});
   on(request,'success',e=>{
    if(!trusted(e,request,'success'))return;
    try{check(s);const raw=reqResult.call(request);value=raw===undefined?null:plain(raw);encoded(value);
     if(!write){done=true;return;}
     if(dbVersion.call(db)!==plan.expected_db_version||encoded(value)!==encoded(plan.before))throw Error('conflict');
     if(!plan.after||plan.after.chat_id!==plan.chat_id)throw Error('unavailable');
     const written=put.call(object,plain(plan.after));if(reqTx.call(written)!==tx)throw Error('unavailable');
     on(written,'error',event=>{if(trusted(event,written,'error'))fail(Error('unavailable'));});
     on(written,'success',event=>{if(trusted(event,written,'success')){value=plain(plan.after);done=true;}});
    }catch(error){fail(error);}
   });
  }catch(error){fail(error);}
 });
}
function operation(s,kind,run){
 check(s);if(s.busy)throw Error('unavailable');s.busy=true;
 const handle=opaque(),entry={s,kind,receipt:null,promise:null};operations.set(handle,entry);
 entry.promise=(async()=>{
  let data,error;
  try{data=await run();check(s);}catch(e){error=e instanceof Error&&e.message==='conflict'?'conflict':s.revoked?'cancelled':'unavailable';}
  const receipt=opaque();receipts.set(receipt,{entry,data,error,consumed:false});entry.receipt=receipt;return receipt;
 })();s.pending.add(entry.promise);void entry.promise.then(()=>s.pending.delete(entry.promise),()=>{});return handle;
}
export function metadataCapture(event){
 if(captured||!(globalThis instanceof DedicatedWorkerGlobalScope)||!trusted(event,globalThis,'message'))throw Error('unavailable');
 const configured=captureMetadataConfiguredBackend(),fixed=readMetadataConfiguredBackend(configured),data=messageData.call(event);
 if(!own(data,['version','operation','artifact','apiUrl','appOrigin','sessionId'])||data.version!==1||data.operation!=='bootstrap_metadata'
  ||data.artifact!==fixed.artifact||data.apiUrl!==fixed.apiUrl||data.appOrigin!==fixed.appOrigin||!uuid(data.sessionId))throw Error('unavailable');
 const factory=idb.call(globalThis);cmp.call(factory,0,0);const context=opaque();
 const s={context,configured,api:fixed.apiUrl,app:fixed.appOrigin,session:data.sessionId,factory,owner:undefined,profileDB:null,chatDB:null,revoked:false,failed:false,busy:false,pending:new Set(),aborters:new Set(),notify:null};
 contexts.set(context,s);captured=context;
 on(globalThis,'message',event=>{if(!trusted(event,globalThis,'message'))return;const data=messageData.call(event);if(own(data,['version','operation','sessionId'])&&data.version===1&&data.operation==='metadata_revoke'&&data.sessionId===s.session)revoke(s);});
 return context;
}
// Same native kernel, separate actual owning-Worker initial bootstrap path.
// The event/factory/configured backend are retained before Client/Worker escape.
export function metadataCaptureStartup(event){
 if(captured||!(globalThis instanceof DedicatedWorkerGlobalScope)||!trusted(event,globalThis,'message'))throw Error('unavailable');
 const configured=captureMetadataConfiguredBackend(),fixed=readMetadataConfiguredBackend(configured),data=messageData.call(event);
 const ports=messagePorts.call(event);
 if(!own(data,['version','operation','artifact','apiUrl','appOrigin','sessionId','expectedPrincipal'])||data.version!==1||data.operation!=='bootstrap_existing_key'
  ||data.artifact!==fixed.artifact||data.apiUrl!==fixed.apiUrl||data.appOrigin!==fixed.appOrigin||data.appOrigin!==globalThis.location.origin||!uuid(data.sessionId)||!uuid(data.expectedPrincipal)||ports.length>1)throw Error('unavailable');
 const factory=idb.call(globalThis);cmp.call(factory,0,0);const context=opaque();
 const s={context,configured,api:fixed.apiUrl,app:fixed.appOrigin,session:data.sessionId,expectedPrincipal:data.expectedPrincipal,factory,owner:undefined,profileDB:null,chatDB:null,revoked:false,failed:false,busy:false,pending:new Set(),aborters:new Set(),notify:null};
 contexts.set(context,s);captured=context;
 on(globalThis,'message',event=>{if(!trusted(event,globalThis,'message'))return;const data=messageData.call(event);if(own(data,['version','operation','sessionId'])&&data.version===1&&data.operation==='metadata_revoke'&&data.sessionId===s.session)revoke(s);});
 return context;
}
export function metadataSelectors(context){const s=state(context);check(s);return[s.api,s.app,s.session];}
export function metadataListenNegative(context,notify){const s=state(context);if(s.notify)throw Error('unavailable');s.notify=notify;if(s.revoked)notify();}
export function metadataCheck(context){const s=state(context);check(s);const fixed=readMetadataConfiguredBackend(s.configured);if(fixed.apiUrl!==s.api||fixed.appOrigin!==s.app)throw Error('cancelled');}
export function metadataRevoke(context){revoke(state(context));}
export function metadataProfile(context,recheck){const s=state(context);if((recheck&&s.owner===undefined)||(!recheck&&s.owner!==undefined))throw Error('unavailable');return operation(s,recheck?'recheck':'profile',async()=>{
 const db=await database(s,'user_db'),guard=ownerGuard(s,db,s.owner??s.expectedPrincipal);let owner;
 try{owner=await guard.ready;guard.stop();await guard.terminal;check(s);}catch(error){guard.abort();await guard.terminal.catch(()=>{});throw error;}
 return{owner,version:dbVersion.call(db)};
});}
export function metadataStart(context,operationId,effect){const s=state(context);if(s.owner===undefined)throw Error('unavailable');if(typeof effect!=='string'||new TextEncoder().encode(effect).byteLength>MAX)throw Error('unavailable');
 const plan=JSON.parse(effect),keys=plan?.operation==='read'?['kind','op_id','owner_id','chat_id','operation']:['kind','op_id','owner_id','chat_id','operation','expected_db_version','before','after'];
 if(!own(plan,keys)||plan.kind!=='openmates-metadata-native-io-v1'||!uuid(plan.op_id)||plan.op_id!==operationId||plan.owner_id!==s.owner||!uuid(plan.chat_id)||!['read','compare_store'].includes(plan.operation))throw Error('unavailable');
 if(plan.operation==='compare_store'&&(!Number.isSafeInteger(plan.expected_db_version)||plan.expected_db_version<1||!(plan.before===null||typeof plan.before==='object')||!plan.after||plan.after.chat_id!==plan.chat_id))throw Error('unavailable');encoded(plan);
 return operation(s,'ticket',async()=>{
  const profile=await database(s,'user_db'),guard=ownerGuard(s,profile,s.owner);let result;
  try{
   await guard.ready;const db=await database(s,'chats_db');check(s);
   result=await rowTransaction(s,db,plan,plan.operation==='compare_store');
   if(plan.operation==='compare_store'){
    const actual=await rowTransaction(s,db,plan,false);if(encoded(actual)!==encoded(plan.after))throw Error('conflict');result=actual;
   }
   guard.stop();await guard.terminal;check(s);
   return encoded({kind:'openmates-metadata-native-result-v1',op_id:plan.op_id,owner_id:s.owner,chat_id:plan.chat_id,db_version:dbVersion.call(db),record:result});
  }catch(error){guard.abort();await guard.terminal.catch(()=>{});throw error;}
 });
}
export function metadataDrive(handle){const entry=operations.get(handle);if(!entry)throw Error('unavailable');return entry.promise;}
export function metadataConsume(context,handle,receipt,kind){
 const s=state(context),entry=operations.get(handle),actual=receipts.get(receipt);check(s);
 if(!entry||entry.s!==s||entry.kind!==kind||actual?.entry!==entry||entry.receipt!==receipt||actual.consumed)throw Error('unavailable');
 if(actual.error){s.failed=true;throw Error(actual.error);}actual.consumed=true;s.busy=false;
 if(kind==='profile'){if(s.owner!==undefined)throw Error('unavailable');s.owner=actual.data.owner;return[actual.data.owner,actual.data.version];}
 if(kind==='recheck'){if(actual.data.owner!==s.owner)throw Error('cancelled');return null;}
 if(kind==='ticket')return actual.data;throw Error('unavailable');
}
export async function metadataCloseCaptured(){
 if(!captured)return;const s=state(captured);revoke(s);
 // pending promises resolve only after actual native terminals. Blocked open
 // stays owned; neither cancellation nor arbitrary error creates close success.
 while(s.pending.size)await Promise.all([...s.pending]);
 for(const db of[s.profileDB,s.chatDB])if(db)dbClose.call(db);
}
export function metadataUnlistenNegative(context,notify){const s=state(context);if(s.notify===notify)s.notify=null;}
export function metadataDeferDrop(callback){queueMicrotask(callback);}
export function metadataCheckProfile(context,owner,version){const s=state(context);check(s);if(s.owner!==owner||!s.profileDB||dbVersion.call(s.profileDB)!==version)throw Error('cancelled');}

// Distinct recovered assistant-message effect. Existing metadata IO bounds and
// record/store rules above remain unchanged. Rust owns crypto and merge policy.
const replyMax=64*1024*1024,replyRowMax=16*1024*1024;
const replyIndex=IDBObjectStore.prototype.index,replyCursor=IDBIndex.prototype.openCursor,replyContinue=IDBCursor.prototype.continue;
const replyCursorValue=get(IDBCursorWithValue.prototype,'value'),replyIndexName=get(IDBIndex.prototype,'name'),replyIndexKey=get(IDBIndex.prototype,'keyPath');
const replyBound=IDBKeyRange.bound;
function replyEncoded(v,limit=replyMax){const text=JSON.stringify(plain(v));if(new TextEncoder().encode(text).byteLength>limit)throw Error('unavailable');return text;}
function replyTransaction(s,db,plan,write){
 return new Promise((resolve,reject)=>{
  check(s);let object,chats,snapshot,metaReady=false,rowReady=false,done=false,failure;
  const tx=begin.call(db,['chats','messages'],write?'readwrite':'readonly');
  const cancel=()=>{try{abort.call(tx);}catch{}};s.aborters.add(cancel);
  const fail=error=>{failure=error;cancel();};
  on(tx,'complete',e=>{if(!trusted(e,tx,'complete'))return;s.aborters.delete(cancel);if(!done||failure||s.revoked||s.failed)reject(failure||Error('cancelled'));else resolve(snapshot);});
  on(tx,'abort',e=>{if(!trusted(e,tx,'abort'))return;s.aborters.delete(cancel);reject(failure||Error('cancelled'));});on(tx,'error',()=>{});
  function finish(){
   if(!metaReady||!rowReady)return;
   try{
    check(s);replyEncoded(snapshot);
    if(!write){done=true;return;}
    if(dbVersion.call(db)!==plan.expected_db_version||replyEncoded(snapshot)!==replyEncoded(plan.before))throw Error('conflict');
    replyEncoded(plan.after,replyRowMax);
    const request=put.call(object,plain(plan.after));if(reqTx.call(request)!==tx)throw Error('unavailable');
    on(request,'error',e=>{if(trusted(e,request,'error'))fail(Error('unavailable'));});
    on(request,'success',e=>{if(trusted(e,request,'success')){snapshot.record=plain(plan.after);done=true;}});
   }catch(error){fail(error);}
  }
  function candidates(){
   if(snapshot.record!==null){rowReady=true;finish();return;}
   const idx=replyIndex.call(object,'chat_id_created_at');
   if(replyIndexName.call(idx)!=='chat_id_created_at'||JSON.stringify(replyIndexKey.call(idx))!==JSON.stringify(['chat_id','created_at']))throw Error('unavailable');
   const range=replyBound.call(IDBKeyRange,[plan.chat_id,plan.created_at-60],[plan.chat_id,plan.created_at+60],true,true);
   const request=replyCursor.call(idx,range,'next');if(reqTx.call(request)!==tx)throw Error('unavailable');let bytes=0,count=0;
   on(request,'error',e=>{if(trusted(e,request,'error'))fail(Error('unavailable'));});
   on(request,'success',e=>{
    if(!trusted(e,request,'success'))return;
    try{check(s);const cursor=reqResult.call(request);if(cursor===null){rowReady=true;finish();return;}
     if(++count>10000)throw Error('unavailable');const raw=plain(replyCursorValue.call(cursor));
     if(raw.chat_id!==plan.chat_id)throw Error('unavailable');const encoded=replyEncoded(raw,replyRowMax);
     if(raw.role==='assistant'){bytes+=new TextEncoder().encode(encoded).byteLength;if(bytes>replyRowMax)throw Error('unavailable');snapshot.candidates.push(raw);}
     replyContinue.call(cursor);
    }catch(error){fail(error);}
   });
  }
  try{
   chats=store.call(tx,'chats');object=store.call(tx,'messages');
   if(txDB.call(tx)!==db||txMode.call(tx)!==(write?'readwrite':'readonly')||storeName.call(chats)!=='chats'||keyPath.call(chats)!=='chat_id'||storeName.call(object)!=='messages'||keyPath.call(object)!=='message_id')throw Error('unavailable');
   snapshot={metadata:null,record:null,candidates:[]};
   const metadata=read.call(chats,plan.chat_id);if(reqTx.call(metadata)!==tx)throw Error('unavailable');
   on(metadata,'error',e=>{if(trusted(e,metadata,'error'))fail(Error('unavailable'));});
   on(metadata,'success',e=>{if(!trusted(e,metadata,'success'))return;try{check(s);const value=reqResult.call(metadata);if(!value||value.chat_id!==plan.chat_id)throw Error('unavailable');snapshot.metadata=plain(value);replyEncoded(snapshot.metadata,replyRowMax);metaReady=true;finish();}catch(error){fail(error);}});
   const message=read.call(object,plan.message_id);if(reqTx.call(message)!==tx)throw Error('unavailable');
   on(message,'error',e=>{if(trusted(e,message,'error'))fail(Error('unavailable'));});
   on(message,'success',e=>{if(!trusted(e,message,'success'))return;try{check(s);const value=reqResult.call(message);snapshot.record=value===undefined?null:plain(value);replyEncoded(snapshot.record,replyRowMax);candidates();}catch(error){fail(error);}});
  }catch(error){fail(error);}
 });
}
export function metadataReplyStart(context,operationId,effect){
 const s=state(context);check(s);if(s.owner===undefined||typeof effect!=='string'||new TextEncoder().encode(effect).byteLength>replyMax)throw Error('unavailable');
 const plan=JSON.parse(effect),keys=['kind','op_id','owner_id','chat_id','message_id','created_at','operation'];
 if(plan?.operation==='compare_store')keys.push('expected_db_version','before','after');
 if(!own(plan,keys)||plan.kind!=='openmates-recovery-reply-native-io-v1'||!uuid(plan.op_id)||operationId!==plan.op_id||plan.owner_id!==s.owner||!uuid(plan.chat_id)||!uuid(plan.message_id)||!Number.isSafeInteger(plan.created_at)||plan.created_at<0||plan.created_at>Number.MAX_SAFE_INTEGER-60||!['read','compare_store'].includes(plan.operation))throw Error('unavailable');
 if(plan.operation==='compare_store'&&(!Number.isSafeInteger(plan.expected_db_version)||plan.expected_db_version<1||!own(plan.before,['metadata','record','candidates'])||!plan.after||plan.after.message_id!==plan.message_id||plan.after.chat_id!==plan.chat_id||plan.after.role!=='assistant'))throw Error('unavailable');replyEncoded(plan);
 if(plan.operation==='compare_store')replyEncoded(plan.after,replyRowMax);
 return operation(s,'ticket',async()=>{
  const profile=await database(s,'user_db'),guard=ownerGuard(s,profile,s.owner);let actual;
  try{
   await guard.ready;const db=await database(s,'chats_db');check(s);
   actual=await replyTransaction(s,db,plan,plan.operation==='compare_store');
   if(plan.operation==='compare_store'){
    actual=await replyTransaction(s,db,plan,false);
    if(replyEncoded(actual.record)!==replyEncoded(plan.after)||replyEncoded(actual.metadata)!==replyEncoded(plan.before.metadata))throw Error('conflict');
   }
   guard.stop();await guard.terminal;check(s);
   return replyEncoded({kind:'openmates-recovery-reply-native-result-v1',op_id:plan.op_id,owner_id:s.owner,chat_id:plan.chat_id,message_id:plan.message_id,db_version:dbVersion.call(db),observation:actual});
  }catch(error){guard.abort();await guard.terminal.catch(()=>{});throw error;}
 });
}

// Separate selected canonical root-code embed facet. Same original context,
// factory/profile and native ledger; no output/journal/ACK interpretation.
const mainEmbedGetAll=IDBIndex.prototype.getAll;
function mainEmbedTransaction(s,db,plan,write){
 return new Promise((resolve,reject)=>{
  check(s);let snapshot={metadata:null,record:null,keys:null,key_targets:[null,null]},remaining=5,done=false,failure;
  const tx=begin.call(db,['chats','embeds','embed_keys'],write?'readwrite':'readonly');
  const cancel=()=>{try{abort.call(tx);}catch{}};s.aborters.add(cancel);
  const fail=error=>{failure=error;cancel();};
  on(tx,'complete',event=>{if(!trusted(event,tx,'complete'))return;s.aborters.delete(cancel);if(!done||failure||s.revoked||s.failed)reject(failure||Error('cancelled'));else resolve(snapshot);});
  on(tx,'abort',event=>{if(!trusted(event,tx,'abort'))return;s.aborters.delete(cancel);reject(failure||Error('cancelled'));});on(tx,'error',()=>{});
  let embeds,keys;
  function complete(){
   if(--remaining!==0)return;
   try{
    check(s);replyEncoded(snapshot);
    if(!write){done=true;return;}
    if(dbVersion.call(db)!==plan.expected_db_version||replyEncoded(snapshot)!==replyEncoded(plan.before))throw Error('conflict');
    // Complete planned aggregate is bounded BEFORE any mutation, independent
    // of the broader effect/proof envelope limits.
    replyEncoded(plan.after,replyRowMax);
    let writes=1+plan.after.keys.length;
    const saved=()=>{if(--writes===0)done=true;};
    for(const [object,row] of [[embeds,plan.after.record],...plan.after.keys.map(row=>[keys,row])]){
     const request=put.call(object,plain(row));if(reqTx.call(request)!==tx)throw Error('unavailable');
     on(request,'error',event=>{if(trusted(event,request,'error'))fail(Error('unavailable'));});
     on(request,'success',event=>{if(trusted(event,request,'success'))saved();});
    }
   }catch(error){fail(error);}
  }
  function request(object,key,assign){
   const pending=read.call(object,key);if(reqTx.call(pending)!==tx)throw Error('unavailable');
   on(pending,'error',event=>{if(trusted(event,pending,'error'))fail(Error('unavailable'));});
   on(pending,'success',event=>{if(!trusted(event,pending,'success'))return;try{check(s);const actual=reqResult.call(pending),row=actual===undefined?null:plain(actual);replyEncoded(row,replyRowMax);assign(row);complete();}catch(error){fail(error);}});
  }
  try{
   const chats=store.call(tx,'chats');embeds=store.call(tx,'embeds');keys=store.call(tx,'embed_keys');
   if(txDB.call(tx)!==db||txMode.call(tx)!==(write?'readwrite':'readonly')||storeName.call(chats)!=='chats'||keyPath.call(chats)!=='chat_id'
    ||storeName.call(embeds)!=='embeds'||keyPath.call(embeds)!=='contentRef'||storeName.call(keys)!=='embed_keys'||keyPath.call(keys)!=='id')throw Error('unavailable');
   request(chats,plan.chat_id,row=>{if(!row||row.chat_id!==plan.chat_id)throw Error('unavailable');snapshot.metadata=row;});
   request(embeds,'embed:'+plan.embed_id,row=>{snapshot.record=row;});
   for(let index=0;index<2;index++)request(keys,plan.key_ids[index],row=>{snapshot.key_targets[index]=row;});
   const idx=replyIndex.call(keys,'hashed_embed_id');if(replyIndexName.call(idx)!=='hashed_embed_id'||replyIndexKey.call(idx)!=='hashed_embed_id')throw Error('unavailable');
   const pending=mainEmbedGetAll.call(idx,plan.hashed_embed_id,1025);if(reqTx.call(pending)!==tx)throw Error('unavailable');
   on(pending,'error',event=>{if(trusted(event,pending,'error'))fail(Error('unavailable'));});
   on(pending,'success',event=>{if(!trusted(event,pending,'success'))return;try{check(s);const actual=plain(reqResult.call(pending));if(!Array.isArray(actual)||actual.length>1024||actual.some(row=>row.hashed_embed_id!==plan.hashed_embed_id))throw Error('unavailable');replyEncoded(actual,replyRowMax);snapshot.keys=actual;complete();}catch(error){fail(error);}});
  }catch(error){fail(error);}
 });
}
export function metadataMainCodeEmbedStart(context,operationId,effect){
 const s=state(context);check(s);if(s.owner===undefined||typeof effect!=='string'||new TextEncoder().encode(effect).byteLength>replyMax)throw Error('unavailable');
 const plan=JSON.parse(effect),fields=['kind','op_id','owner_id','chat_id','embed_id','hashed_embed_id','key_ids','operation'];
 if(plan?.operation==='compare_store')fields.push('expected_db_version','before','after');
 const hash=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
 if(!own(plan,fields)||plan.kind!=='openmates-main-code-embed-native-io-v1'||!uuid(plan.op_id)||operationId!==plan.op_id||plan.owner_id!==s.owner||!uuid(plan.chat_id)||!uuid(plan.embed_id)||!hash(plan.hashed_embed_id)
  ||!Array.isArray(plan.key_ids)||plan.key_ids.length!==2||plan.key_ids[0]!==plan.hashed_embed_id+':master:null'||typeof plan.key_ids[1]!=='string'||plan.key_ids[1].length!==134||!plan.key_ids[1].startsWith(plan.hashed_embed_id+':chat:')||!hash(plan.key_ids[1].slice(-64))||!['read','compare_store'].includes(plan.operation))throw Error('unavailable');
 if(plan.operation==='compare_store'){
  if(!Number.isSafeInteger(plan.expected_db_version)||plan.expected_db_version<1||!own(plan.before,['metadata','record','keys','key_targets'])||!own(plan.after,['record','keys'])
   ||!plan.after.record||plan.after.record.contentRef!=='embed:'+plan.embed_id||plan.after.record.embed_id!==plan.embed_id||plan.after.record.type!=='code'
   ||!Array.isArray(plan.after.keys)||plan.after.keys.length!==2||plan.after.keys.some(row=>row.hashed_embed_id!==plan.hashed_embed_id||!plan.key_ids.includes(row.id))||new Set(plan.after.keys.map(row=>row.id)).size!==2)throw Error('unavailable');
  replyEncoded(plan.after,replyRowMax);
 }
 replyEncoded(plan);
 return operation(s,'ticket',async()=>{
  const profile=await database(s,'user_db'),guard=ownerGuard(s,profile,s.owner);let actual;
  try{
   await guard.ready;const db=await database(s,'chats_db');check(s);
   actual=await mainEmbedTransaction(s,db,plan,plan.operation==='compare_store');
   if(plan.operation==='compare_store'){
    actual=await mainEmbedTransaction(s,db,plan,false);
    if(replyEncoded(actual.record)!==replyEncoded(plan.after.record)||replyEncoded(actual.keys)!==replyEncoded(plan.after.keys)||replyEncoded(actual.metadata)!==replyEncoded(plan.before.metadata))throw Error('conflict');
   }
   guard.stop();await guard.terminal;check(s);
   return replyEncoded({kind:'openmates-main-code-embed-native-result-v1',op_id:plan.op_id,owner_id:s.owner,chat_id:plan.chat_id,embed_id:plan.embed_id,db_version:dbVersion.call(db),observation:actual});
  }catch(error){guard.abort();await guard.terminal.catch(()=>{});throw error;}
 });
}
