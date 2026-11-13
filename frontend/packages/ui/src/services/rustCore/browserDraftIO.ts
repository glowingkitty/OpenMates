/// <reference lib="es2022.object" />
import {assertRustChatIOPorts,isNativeChatIOEvent} from './browserAdapters';
import type {RustChatIOPorts} from './browserAdapters';
import {parseBrowserDraftPlan,draftProjection,MAX_DRAFT_PACKET_BYTES,DRAFT_WRITES} from './browserDraftProtocol';
import type {BrowserDraftEffectHandler} from './browserDraftProtocol';
/** Existing chats_db/chats + pending_sync_changes only. Executes Rust's closed
 * predicates and ciphertext patch; no crypto, version choice, retry or schema.
 * Transaction complete/readback is the only local durability acknowledgement.
 */
export function createBrowserDraftEffectHandler(ports:RustChatIOPorts,current:()=>void):BrowserDraftEffectHandler{
 assertRustChatIOPorts(ports);
 return createDraftEffectHandler(ports,current);
}
/** IndexedDB surface the closed draft plan executor needs. */
export interface DraftIDBPorts{current():void;open():IDBOpenDBRequest;transaction(database:IDBDatabase,stores:string|string[],mode:IDBTransactionMode):IDBTransaction}
/** The same closed plan executor over a plain IndexedDB port. Used by the shared
 * Rust core Worker's `drafts` unit, which opens the existing chats_db in its
 * own realm (no page routing lease exists there). Page callers use
 * createBrowserDraftEffectHandler, which also asserts the original page lease.
 */
export function createDraftEffectHandler(ports:DraftIDBPorts,current:()=>void):BrowserDraftEffectHandler{
 const usedEvents=new WeakSet<Event>();
 const native=(event:Event,target:EventTarget)=>{if(!isNativeChatIOEvent(event,target)||usedEvents.has(event))throw Error('draft_native_event_required');usedEvents.add(event);};
 const same=(a:unknown,b:unknown):boolean=>{
  if(a===b)return true;if(!a||!b||typeof a!=='object'||typeof b!=='object')return false;
  const x=a as Record<string,unknown>,y=b as Record<string,unknown>,keys=Object.keys(x);
  return keys.length===Object.keys(y).length&&keys.every(k=>Object.hasOwn(y,k)&&same(x[k],y[k]));
 };
 const lifetime=new AbortController(),pending=new Set<Promise<string>>();let closed=false;
 const guard=(signal:AbortSignal)=>{if(closed||lifetime.signal.aborted||signal.aborted)throw Error('cancelled');ports.current();current();};
 return {current,execute(encoded,signal){
  if(closed||signal.aborted)return Promise.reject(Error('cancelled'));
  const task:Promise<string>=(async()=>{
   const p=parseBrowserDraftPlan(encoded);guard(signal);
   return await new Promise<string>((resolve,reject)=>{
    let db:IDBDatabase|null=null,tx:IDBTransaction|null=null,terminal=false,aborted=false,value='';
    const release=()=>{signal.removeEventListener('abort',abort);lifetime.signal.removeEventListener('abort',abort);db?.close();};
    const fail=(error:unknown)=>{if(terminal)return;aborted=true;try{tx?.abort();}catch{/* Terminal handler still owns release. */}if(!tx){terminal=true;release();reject(error);}else value='';};
    const abort=()=>fail(Error('cancelled'));
    const open=ports.open();open.onupgradeneeded=()=>{open.transaction?.abort();fail(Error('unexpected_upgrade'));};open.onerror=open.onblocked=()=>fail(Error('existing_database_required'));
    signal.addEventListener('abort',abort,{once:true});lifetime.signal.addEventListener('abort',abort,{once:true});
    if(signal.aborted||lifetime.signal.aborted)abort();
    open.onsuccess=(event)=>{
     try{native(event,open);}catch(error){fail(error);return;}
     db=open.result;if(terminal){db.close();return;}
     try{guard(signal);if(aborted||!db.objectStoreNames.contains('chats')||!db.objectStoreNames.contains('pending_sync_changes'))throw Error('existing_stores_required');
      tx=ports.transaction(db,['chats','pending_sync_changes'],p.kind==='store_draft'||p.kind==='ack_draft'?'readwrite':'readonly');
      tx.onabort=(event)=>{if(terminal)return;try{native(event,tx!);}catch(error){fail(error);return;}terminal=true;release();reject(Error('draft_transaction_aborted'));};
      tx.onerror=()=>{/* Abort/complete owns the terminal, never request success. */};
      tx.oncomplete=(event)=>{if(terminal)return;try{native(event,tx!);}catch(error){fail(error);return;}terminal=true;try{guard(signal);if(aborted||!value)throw Error('draft_transaction_incomplete');release();resolve(value);}catch(error){release();reject(error);}};
      const chats=tx.objectStore('chats'),queue=tx.objectStore('pending_sync_changes');if(chats.keyPath!=='chat_id'||queue.keyPath!=='change_id')throw Error('existing_keypaths_required');
      let row:Record<string,unknown>|undefined,maximum=0,loaded=0,count=0,change:unknown=null;
      const packet=()=>{guard(signal);const result=JSON.stringify({version:1,kind:p.kind,operationId:p.operationId,chatId:p.chatId,row:row?draftProjection(row):null,queueMaximum:maximum,change,transactionCommitted:true});if(new TextEncoder().encode(result).length>MAX_DRAFT_PACKET_BYTES)throw Error('draft_packet_bounds');value=result;};
      const ready=()=>{if(++loaded!==2)return;try{
       guard(signal);if(!row||row.chat_id!==p.chatId)throw Error('existing_chat_required');
       if(p.kind==='capture_draft'){packet();return;}
       if(!same(draftProjection(row),p.expected))throw Error('draft_conflict');
       const expected=p.change!;
       const readChange=()=>{const request=queue.get(expected.change_id);request.onerror=()=>fail(request.error);request.onsuccess=(event)=>{try{native(event,request);guard(signal);change=request.result??null;
        if(p.kind!=='ack_draft'&&!same(change,expected))throw Error('draft_intent_readback');
        if(p.kind==='ack_draft'&&change!==null)throw Error('draft_intent_not_removed');packet();}catch(error){fail(error);}};};
       if(p.kind==='store_draft'){
        if(maximum!==p.queueMaximum)throw Error('draft_queue_conflict');
        const next={...row};for(const field of DRAFT_WRITES)next[field]=p.patch![field];
        const put=chats.put(next),add=queue.add(expected);let writes=0;
        const back=(event:Event)=>{try{const target=event.target;if(target!==put&&target!==add)throw Error('draft_native_event_required');native(event,target);}catch(error){fail(error);return;}if(++writes!==2)return;const request=chats.get(p.chatId);request.onerror=()=>fail(request.error);request.onsuccess=(event)=>{try{native(event,request);guard(signal);row=request.result;if(!row||!same(draftProjection(row),draftProjection(next)))throw Error('draft_row_readback');readChange();}catch(error){fail(error);}};};
        put.onerror=()=>fail(put.error);add.onerror=()=>fail(add.error);put.onsuccess=add.onsuccess=back;
       }else if(p.kind==='ack_draft'){
        const request=queue.get(expected.change_id);request.onerror=()=>fail(request.error);request.onsuccess=(event)=>{try{native(event,request);guard(signal);if(!same(request.result,expected))throw Error('draft_intent_conflict');const remove=queue.delete(expected.change_id);remove.onerror=()=>fail(remove.error);remove.onsuccess=(event)=>{try{native(event,remove);readChange();}catch(error){fail(error);}};}catch(error){fail(error);}};
       }else readChange();
      }catch(error){fail(error);}};
      const request=chats.get(p.chatId);request.onerror=()=>fail(request.error);request.onsuccess=(event)=>{try{native(event,request);row=request.result;ready();}catch(error){fail(error);}};
      const cursor=queue.openCursor();cursor.onerror=()=>fail(cursor.error);cursor.onsuccess=(event)=>{try{native(event,cursor);guard(signal);const item=cursor.result;if(!item){ready();return;}
       if(++count>10000)throw Error('draft_queue_bounds');const order=item.value?.queue_order;if(order!==undefined&&(!Number.isSafeInteger(order)||order<1))throw Error('draft_queue_order');maximum=Math.max(maximum,order??0);item.continue();}catch(error){fail(error);}};
     }catch(error){fail(error);}
    };
   });
  })().finally(()=>pending.delete(task));pending.add(task);return task;
 },async close(){closed=true;lifetime.abort();await Promise.allSettled([...pending]);}};
}
