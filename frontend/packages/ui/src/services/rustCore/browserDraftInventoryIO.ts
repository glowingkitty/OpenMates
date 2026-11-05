/// <reference lib="es2022.object" />
import {assertRustChatIOPorts,assertRustChatIOPortsNegative,isNativeChatIOEvent} from './browserAdapters';
import type {RustChatIOPorts} from './browserAdapters';
/** Closed readonly DATA adapter. Rust owns draft selection/merge/version/crypto.
 * Native cursor EOF is one transaction observation, not an atomic inventory,
 * store absence/deletion, credential durability or whole-hint completion.
 */
const KIND='read_original_draft_inventory_page',REREAD_KIND='reread_original_draft_inventory_row',ROWS=20,BYTES=2*1024*1024,KEY_BYTES=4096;
const FIELDS=['chat_id','id','user_id','owner_id','hashed_user_id','team_id','hashed_team_id','chat_visibility','encrypted_chat_key','key_version','key_fingerprint','messages_v','draft_v','cleared_draft_v','encrypted_draft_md','encrypted_draft_preview','updated_at','last_edited_overall_timestamp','is_anonymous','is_shared','is_private'] as const;
const NUMBERS=new Set<string>(['key_version','messages_v','draft_v','cleared_draft_v','updated_at','last_edited_overall_timestamp']);
const FLAGS=new Set<string>(['is_anonymous','is_shared','is_private']);
const encoder=new TextEncoder();
type PagePlan={version:1;kind:typeof KIND;operationId:string;page:number;after:string|null;maxRows:20;maxBytes:number};
type RowPlan={version:1;kind:typeof REREAD_KIND;operationId:string;page:number;chatId:string};
type Plan=PagePlan|RowPlan;
const uuid=(value:unknown):value is string=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
function parse(encoded:string):Plan{
 if(encoder.encode(encoded).byteLength>6*KEY_BYTES+1024)throw Error('draft_inventory_plan');
 let p:Record<string,unknown>;try{p=JSON.parse(encoded) as Record<string,unknown>;}catch{throw Error('draft_inventory_plan');}
 if(!p||typeof p!=='object'||Array.isArray(p)||p.version!==1||!uuid(p.operationId)||typeof p.page!=='number'||!Number.isSafeInteger(p.page)||p.page<1)throw Error('draft_inventory_plan');
 const keys=p.kind===KIND?['version','kind','operationId','page','after','maxRows','maxBytes']:p.kind===REREAD_KIND?['version','kind','operationId','page','chatId']:[];
 if(!keys.length||Object.keys(p).length!==keys.length||!keys.every(key=>Object.hasOwn(p,key)))throw Error('draft_inventory_plan');
 if(p.kind===KIND){if(p.maxRows!==ROWS||p.maxBytes!==BYTES||(p.after!==null&&(typeof p.after!=='string'||encoder.encode(p.after).byteLength>KEY_BYTES)))throw Error('draft_inventory_plan');}
 else if(!uuid(p.chatId))throw Error('draft_inventory_plan');
 return p as unknown as Plan;
}
function project(value:unknown,key:string):Record<string,unknown>{
 if(!value||typeof value!=='object'||Array.isArray(value))throw Error('draft_inventory_record');
 const chat=Object.getOwnPropertyDescriptor(value,'chat_id');if(!chat||!Object.hasOwn(chat,'value')||chat.value!==key)throw Error('draft_inventory_record_key');
 const projection:Record<string,unknown>={};for(const field of FIELDS){const descriptor=Object.getOwnPropertyDescriptor(value,field);if(!descriptor)continue;if(!Object.hasOwn(descriptor,'value'))throw Error('draft_inventory_accessor');const item=descriptor.value;if(item===undefined)continue;if(item!==null){if(NUMBERS.has(field)){if(!Number.isSafeInteger(item)||item<0)throw Error('draft_inventory_value');}else if(FLAGS.has(field)){if(typeof item!=='boolean')throw Error('draft_inventory_value');}else if(typeof item!=='string')throw Error('draft_inventory_value');}projection[field]=item;}
 return projection;
}
function getter(proto:object,key:string):(this:unknown)=>unknown{
 const found=Object.getOwnPropertyDescriptor(proto,key)?.get;if(!found)throw Error('draft_inventory_platform');return found;
}
export interface BrowserDraftInventoryIO {execute(encoded:string,signal:AbortSignal):Promise<string>;close():Promise<void>}
export function createBrowserDraftInventoryIO(ports:RustChatIOPorts,current:()=>void):BrowserDraftInventoryIO{
 assertRustChatIOPorts(ports);
 // Capture real platform methods/getters before the first IO/await. Their native
 // internal-slot checks reject object copies and mismatched cursor/request DBs.
 const getResult=getter(IDBRequest.prototype,'result'),getRequestTransaction=getter(IDBRequest.prototype,'transaction'),getRequestSource=getter(IDBRequest.prototype,'source');
 const getVersion=getter(IDBDatabase.prototype,'version'),getStoreName=getter(IDBObjectStore.prototype,'name'),getKeyPath=getter(IDBObjectStore.prototype,'keyPath');
 const getCursorKey=getter(IDBCursor.prototype,'key'),getCursorSource=getter(IDBCursor.prototype,'source'),getCursorValue=getter(IDBCursorWithValue.prototype,'value');
 const getLower=getter(IDBKeyRange.prototype,'lower'),getUpper=getter(IDBKeyRange.prototype,'upper'),getLowerOpen=getter(IDBKeyRange.prototype,'lowerOpen');
 const lower=IDBKeyRange.lowerBound,objectStore=IDBTransaction.prototype.objectStore,openCursor=IDBObjectStore.prototype.openCursor,getRow=IDBObjectStore.prototype.get,advance=IDBCursor.prototype.continue;
 const seen=new WeakSet<Event>(),lifetime=new AbortController(),pending=new Set<Promise<string>>();let closed=false;
 const native=(event:Event,target:EventTarget)=>{if(!isNativeChatIOEvent(event,target)||seen.has(event))throw Error('draft_inventory_native_event');seen.add(event);};
 const guard=(signal:AbortSignal)=>{if(closed||lifetime.signal.aborted||signal.aborted)throw Error('cancelled');assertRustChatIOPorts(ports);ports.current();current();if(closed||lifetime.signal.aborted||signal.aborted)throw Error('cancelled');ports.current();assertRustChatIOPortsNegative(ports);};
 return {execute(encoded,signal){
  let plan:Plan;try{plan=parse(encoded);guard(signal);}catch{return Promise.reject(Error('draft_inventory_plan_or_scope'));}
  let start:()=>void=()=>{throw Error('draft_inventory_start');};
  const task:Promise<string>=new Promise<string>((resolve,reject)=>{start=()=>{
   let db:IDBDatabase|null=null,tx:IDBTransaction|null=null,openSettled=false,finished=false,failure:Error|null=null;
   let databaseVersion=0,lastKey=plan.kind===KIND?plan.after:null,exhausted=false,rowBytes=0,rereadRow='null';const rows:string[]=[];
   const release=()=>{signal.removeEventListener('abort',abort);lifetime.signal.removeEventListener('abort',abort);db?.close();};
   const settle=()=>{if(finished)return;finished=true;release();if(failure){reject(failure);return;}try{guard(signal);const out=envelope(rows.join(','),lastKey,exhausted);if(encoder.encode(out).byteLength>BYTES)throw Error('draft_inventory_bytes');guard(signal);resolve(out);}catch{reject(Error('draft_inventory_scope_or_bytes'));}};
   const fail=(code:string)=>{failure??=Error(code);try{tx?.abort();}catch{/* Already terminal: its actual event still settles. */}if(!tx&&openSettled)settle();};
   const abort=()=>fail('cancelled');
   const envelope=(encodedRows:string,key:string|null,end:boolean)=>{const head=JSON.stringify({version:1,kind:plan.kind,operationId:plan.operationId,page:plan.page,databaseVersion}).slice(0,-1);return plan.kind===REREAD_KIND?head+',"row":'+rereadRow+',"transactionCommitted":true}':head+',"rows":['+encodedRows+'],"lastKey":'+JSON.stringify(key)+',"cursorExhausted":'+String(end)+',"transactionCommitted":true}';};
   signal.addEventListener('abort',abort,{once:true});lifetime.signal.addEventListener('abort',abort,{once:true});
   let request:IDBOpenDBRequest;
   try{guard(signal);request=ports.open();}catch{openSettled=true;fail('draft_inventory_open');return;}
   request.onblocked=event=>{try{native(event,request);}catch{/* Negative only. */}fail('draft_inventory_blocked');};
   request.onupgradeneeded=event=>{try{native(event,request);(getRequestTransaction.call(request) as IDBTransaction|null)?.abort();}catch{/* No schema upgrade fallback. */}fail('draft_inventory_existing_database');};
   request.onerror=event=>{try{native(event,request);}catch{fail('draft_inventory_native_event');return;}openSettled=true;fail('draft_inventory_open');};
   request.onsuccess=event=>{
    try{
     native(event,request);openSettled=true;db=getResult.call(request) as IDBDatabase;
     if(failure){settle();return;}guard(signal);databaseVersion=getVersion.call(db) as number;if(!Number.isSafeInteger(databaseVersion)||databaseVersion<1)throw Error('draft_inventory_database_version');
     tx=ports.transaction(db,'chats','readonly');const owned=tx;
     owned.onabort=event=>{try{native(event,owned);}catch{fail('draft_inventory_native_event');return;}failure??=Error('draft_inventory_aborted');settle();};
     owned.onerror=()=>fail('draft_inventory_transaction');
     owned.oncomplete=event=>{try{native(event,owned);}catch{fail('draft_inventory_native_event');return;}try{guard(signal);}catch{failure??=Error('cancelled');}settle();};
     const store=objectStore.call(owned,'chats');if(getStoreName.call(store)!=='chats'||getKeyPath.call(store)!=='chat_id')throw Error('draft_inventory_schema');
     if(plan.kind===REREAD_KIND){
      const selected=plan.chatId,read=getRow.call(store,selected);
      if(getRequestTransaction.call(read)!==owned||getRequestSource.call(read)!==store)throw Error('draft_inventory_request');
      read.onerror=()=>fail('draft_inventory_reread');
      read.onsuccess=event=>{try{native(event,read);guard(signal);if(getRequestTransaction.call(read)!==owned||getRequestSource.call(read)!==store)throw Error('draft_inventory_request');const value=getResult.call(read);rereadRow=value===undefined||value===null?'null':JSON.stringify(project(value,selected));if(encoder.encode(envelope('',null,false)).byteLength>BYTES){fail('draft_inventory_row_oversized');return;}}catch{fail('draft_inventory_reread_data');}};
      return;
     }
     let range:IDBKeyRange|undefined;
     if(plan.after!==null){range=lower.call(IDBKeyRange,plan.after,true);if(getLower.call(range)!==plan.after||getUpper.call(range)!==undefined||getLowerOpen.call(range)!==true)throw Error('draft_inventory_range');}
     const cursorRequest=openCursor.call(store,range,'next');
     if(getRequestTransaction.call(cursorRequest)!==owned||getRequestSource.call(cursorRequest)!==store)throw Error('draft_inventory_request');
     cursorRequest.onerror=()=>fail('draft_inventory_cursor');
     cursorRequest.onsuccess=event=>{
      try{
       native(event,cursorRequest);guard(signal);if(getRequestTransaction.call(cursorRequest)!==owned||getRequestSource.call(cursorRequest)!==store)throw Error('draft_inventory_request');
       const cursor=getResult.call(cursorRequest) as IDBCursorWithValue|null;
       if(cursor===null){exhausted=true;return;}
       if(getCursorSource.call(cursor)!==store)throw Error('draft_inventory_cursor');const key=getCursorKey.call(cursor);
       if(typeof key!=='string'||encoder.encode(key).byteLength>KEY_BYTES||(lastKey!==null&&key<=lastKey))throw Error('draft_inventory_key');
       const projection=project(getCursorValue.call(cursor),key);
       const row=JSON.stringify(projection),size=encoder.encode(row).byteLength,base=encoder.encode(envelope('',key,false)).byteLength;
       if(base+rowBytes+size+(rows.length?rows.length:0)>BYTES){if(rows.length===0){fail('draft_inventory_row_oversized');return;}return;}
       rows.push(row);rowBytes+=size;lastKey=key;
       // Cutoff never consumes/advances past an omitted row and never labels
       // EOF. A later genuine ticket resumes strictly after last emitted key.
       if(rows.length<ROWS)advance.call(cursor);
      }catch{fail('draft_inventory_cursor_data');}
     };
    }catch{fail('draft_inventory_open_or_scope');}
   };
  };});
  pending.add(task);void task.then(()=>pending.delete(task),()=>pending.delete(task));start();return task;
 },close(){closed=true;lifetime.abort();return Promise.allSettled([...pending]).then(()=>undefined);}};
}
