/// <reference lib="es2022.object" />
import {createRustChatOpenRequest,createRustChatTransaction} from './browserAdapters';
import type {RustChatIORoutingLease} from './browserAdapters';
/** Inactive executor: closed Rust monitor candidate plans, existing DB only. */
import {awaitBrowserRead} from './existingSavedChatIO';
import {browserMessageCacheTransactionProtocol as shared} from './browserMessageCacheIO';
type Row=Record<string,unknown>;
const {META,FIELDS,CIPHERS,WRITES,record,exact,integer,uuid,bounded,projection,equal,flags,rowPredicate,insertRow,metadataInsert}=shared;
const DELETE_FIELDS=['id','message_id','client_message_id','chat_id','created_at','role','status','key_version','has_thinking','thinking_token_count','queue_revision',...CIPHERS];
const physical=(v:unknown):v is string=>typeof v==='string'&&v.length>0;
function patchShape(v:unknown,id:string,chat:unknown,old:unknown):boolean {
 if(!record(v)||v.messageId!==id)return false;
 if(old===null){if(exact(v,['messageId','retainCandidateId']))return physical(v.retainCandidateId);return exact(v,['messageId','insert'])&&insertRow(v.insert,id,chat,true);}
 return exact(v,['messageId','set','remove'])&&record(v.set)&&Object.entries(v.set).every(([k,x])=>WRITES.includes(k)&&(CIPHERS.includes(k)?x===null||typeof x==='string':k==='status'?['synced','delivered'].includes(String(x)):k==='has_thinking'?x===null||typeof x==='boolean':k==='pending_turn_preflight_v1'?x===1:x===null||integer(x)))&&Array.isArray(v.remove)&&v.remove.length<=1&&v.remove.every(k=>k==='pending_turn_preflight_v1'&&!Object.hasOwn(v.set as Row,k));
}
function parse(encoded:string):Row {
 if(new TextEncoder().encode(encoded).length>256*1024)throw Error('unavailable');const p:unknown=JSON.parse(encoded);bounded(p);
 if(!record(p)||!exact(p,['version','kind','operationId','scope','owner','chatId','database','stores','databaseVersion','messageIds','metadataFields','messageFields','candidateQueries','metadataInsert','expectedMetadata','expectedRows','expectedCandidates','patches','candidateDeletes'])||p.version!==1||!['capture_monitor_candidates','compare_and_replace_monitor_candidates'].includes(String(p.kind))||!uuid(p.operationId)||!uuid(p.owner)||!uuid(p.chatId)||p.database!=='chats_db'||!record(p.scope)||!exact(p.scope,['lifecycleGeneration','workspaceEpoch'])||!integer(p.scope.lifecycleGeneration)||p.scope.lifecycleGeneration===0||!integer(p.scope.workspaceEpoch)||!metadataInsert(p.metadataInsert,p.chatId))throw Error('unavailable');
 for(const [actual,expected] of [[p.stores,['chats','messages']],[p.metadataFields,META],[p.messageFields,FIELDS]] as [unknown,readonly string[]][]){if(!Array.isArray(actual)||actual.length!==expected.length||expected.some((v,i)=>actual[i]!==v))throw Error('unavailable');}
 if(!Array.isArray(p.messageIds)||p.messageIds.length>20||p.messageIds.some((id,i,a)=>!physical(id)||i>0&&a[i-1]>=id)||!Array.isArray(p.candidateQueries)||p.candidateQueries.length>20)throw Error('unavailable');
 if(p.candidateQueries.some((q,i,a)=>!record(q)||!exact(q,['messageId','encryptedContent','createdAt'])||!(p.messageIds as unknown[]).includes(q.messageId)||!physical(q.encryptedContent)||!integer(q.createdAt)||i>0&&String((a[i-1] as Row).messageId)>=String(q.messageId)))throw Error('unavailable');
 if(p.kind==='capture_monitor_candidates'){if(p.databaseVersion!==null||p.expectedMetadata!==null||p.expectedRows!==null||p.expectedCandidates!==null||p.patches!==null||p.candidateDeletes!==null)throw Error('unavailable');return p;}
 if(!integer(p.databaseVersion)||p.databaseVersion===0||!(p.expectedMetadata===null||projection(p.expectedMetadata,META))||!Array.isArray(p.expectedRows)||p.expectedRows.length!==p.messageIds.length||!p.expectedRows.every(v=>v===null||rowPredicate(v))||!Array.isArray(p.patches)||p.patches.length!==p.messageIds.length||!p.patches.every((v,i)=>patchShape(v,(p.messageIds as string[])[i],p.chatId,(p.expectedRows as unknown[])[i])))throw Error('unavailable');
 if(!Array.isArray(p.expectedCandidates)||p.expectedCandidates.length!==p.candidateQueries.length||p.expectedCandidates.some((f,i)=>!record(f)||!exact(f,['messageId','rows'])||f.messageId!==(p.candidateQueries as Row[])[i].messageId||!Array.isArray(f.rows)||!f.rows.every(rowPredicate)))throw Error('unavailable');
 if(!Array.isArray(p.candidateDeletes)||p.candidateDeletes.length>20||p.candidateDeletes.some((d,i,a)=>!record(d)||!exact(d,['messageId','replacementMessageId'])||!physical(d.messageId)||!physical(d.replacementMessageId)||d.messageId===d.replacementMessageId||(p.messageIds as unknown[]).includes(d.messageId)||a.slice(0,i).some(v=>record(v)&&v.messageId===d.messageId)))throw Error('unavailable');
 for(const patch of p.patches as Row[]){const frame=(p.expectedCandidates as Row[]).find(f=>f.messageId===patch.messageId);if(patch.retainCandidateId!==undefined&&(!frame||!(frame.rows as Row[]).some(r=>(r.fields as Row).message_id===patch.retainCandidateId)))throw Error('unavailable');}
 for(const d of p.candidateDeletes as Row[]){const patch=(p.patches as Row[]).find(v=>v.messageId===d.replacementMessageId),frame=(p.expectedCandidates as Row[]).find(v=>v.messageId===d.replacementMessageId);if(!patch||!record(patch.insert)||patch.insert.role!=='assistant'||!frame||!(frame.rows as Row[]).some(v=>(v.fields as Row).message_id===d.messageId))throw Error('unavailable');}
 return p;
}
function matches(raw:Row,q:Row,chat:unknown):boolean {
 if(raw.chat_id!==chat||raw.role!=='assistant'||raw.message_id===q.messageId||raw.encrypted_content!==q.encryptedContent)return false;
 if(!physical(raw.message_id)||!integer(raw.created_at))throw Error('unavailable');
 return Math.abs(Number(raw.created_at)-Number(q.createdAt))<60;
}
function frames(queries:Row[],active:boolean[],universe:Map<string,Row>,chat:unknown):Row[]{return queries.map((q,i)=>({messageId:q.messageId,rows:active[i]?[...universe.values()].filter(r=>matches(r,q,chat)).sort((a,b)=>Number(a.created_at)-Number(b.created_at)||(String(a.message_id)<String(b.message_id)?-1:String(a.message_id)>String(b.message_id)?1:0)):[]}));}
function guardDelete(raw:Row,insert:Row,chat:unknown):void {
 if(raw.chat_id!==chat||!['synced','delivered'].includes(String(raw.status))||raw.role!=='assistant'||insert.role!=='assistant'||raw.message_id===insert.message_id||raw.encrypted_content!==insert.encrypted_content||!integer(raw.created_at)||!integer(insert.created_at)||Math.abs(Number(raw.created_at)-Number(insert.created_at))>=60||Object.keys(raw).some(k=>!DELETE_FIELDS.includes(k)))throw Error('conflict');
 for(const field of ['key_version','queue_revision'])if(Object.hasOwn(raw,field)&&raw[field]!==null&&(!integer(raw[field])||!integer(insert[field])||Number(insert[field])<Number(raw[field])))throw Error('conflict');
}
export async function executeBrowserAssistantReplacementPlan(factory:IDBFactory,encoded:string,signal:AbortSignal,guard:()=>void,routingLease?:RustChatIORoutingLease):Promise<string>{
 const p=parse(encoded),ids=p.messageIds as string[],queries=p.candidateQueries as Row[],write=p.kind==='compare_and_replace_monitor_candidates';
 let db:IDBDatabase|null=null,tx:IDBTransaction|null=null,invalid=false;const lifetime=new AbortController();
 const current=()=>{if(invalid||signal.aborted||lifetime.signal.aborted)throw Error('cancelled');guard();};
 const abort=()=>{invalid=true;lifetime.abort();try{tx?.abort();}catch{/* terminal owns settlement */}};
 signal.addEventListener('abort',abort,{once:true});const timer=setTimeout(abort,5000);
 try {
  current();if(typeof factory.databases!=='function')throw Error('unavailable');const databases=await awaitBrowserRead(factory.databases(),lifetime.signal);current();const version=databases.find(v=>v.name==='chats_db'&&integer(v.version)&&Number(v.version)>0)?.version;
  if(version===undefined||p.databaseVersion!==null&&version!==p.databaseVersion)throw Error('unavailable');
  db=await new Promise<IDBDatabase>((resolve,reject)=>{let settled=false;const request=routingLease?createRustChatOpenRequest(routingLease,factory):factory.open('chats_db');const fail=()=>{if(!settled){settled=true;lifetime.signal.removeEventListener('abort',fail);reject(Error('unavailable'));}};lifetime.signal.addEventListener('abort',fail,{once:true});request.onupgradeneeded=()=>{request.transaction?.abort();fail();};request.onerror=request.onblocked=fail;request.onsuccess=()=>{const opened=request.result;try{current();if(settled||opened.version!==version)throw Error('unavailable');settled=true;lifetime.signal.removeEventListener('abort',fail);resolve(opened);}catch{opened.close();fail();}};});
  current();db.onversionchange=()=>{abort();db?.close();};if(['chats','messages'].some(name=>!db!.objectStoreNames.contains(name)))throw Error('unavailable');const opened=db;
  return await new Promise<string>((resolve,reject)=>{
   const rows:unknown[]=[];
   let failure:unknown=null,metadata:unknown=null,before:unknown=null,candidates:Row[]=queries.map(q=>({messageId:q.messageId,rows:[]})),beforeCandidates:unknown=null,deleted:unknown[]=[],remaining=ids.length+1,ready=false;
   const packet=()=>({version:1,kind:p.kind,operationId:p.operationId,databaseVersion:opened.version,transactionCommitted:true,credentialAcknowledged:false,crossDatabaseAssociationProven:false,metadata,rows,before,candidates,beforeCandidates,deleted});
   const fail=(e:unknown)=>{failure??=e;try{tx!.abort();}catch{/* terminal owns settlement */}};
   current();tx=routingLease?createRustChatTransaction(routingLease,opened,['chats','messages'],write?'readwrite':'readonly'):opened.transaction(['chats','messages'],write?'readwrite':'readonly');
   tx.onabort=()=>{try{current();}catch(e){failure??=e;}reject(failure??Error('storage_failed'));};tx.onerror=()=>{failure??=Error('storage_failed');};tx.oncomplete=()=>{try{current();if(failure)throw failure;if(!ready)throw Error('unavailable');resolve(bounded(packet()));}catch(e){reject(e);}};
   const chats=tx.objectStore('chats'),messages=tx.objectStore('messages');
   const planWrites=()=>{
    current();if(!write){bounded(packet());ready=true;return;}
    if(p.expectedMetadata===null){if(metadata!==null)throw Error('conflict');}else if(!record(metadata)||!equal(metadata,p.expectedMetadata as Row,META))throw Error('conflict');
    rows.forEach((raw,i)=>{const expected=(p.expectedRows as unknown[])[i];if(expected===null){if(raw!==null)throw Error('conflict');}else if(!record(raw)||!record(expected)||!equal(raw,expected.fields as Row,FIELDS)||Object.entries(flags(raw)).some(([k,v])=>expected[k]!==v))throw Error('conflict');});
    candidates.forEach((frame,i)=>{const actual=frame.rows as Row[],expected=((p.expectedCandidates as Row[])[i].rows as Row[]);if(actual.length!==expected.length)throw Error('conflict');actual.forEach((raw,j)=>{if(!equal(raw,expected[j].fields as Row,FIELDS)||Object.entries(flags(raw)).some(([k,v])=>expected[j][k]!==v))throw Error('conflict');});});
    before=[...rows];beforeCandidates=candidates.map(f=>({messageId:f.messageId,rows:[...(f.rows as Row[])]}));
    const universe=new Map<string,Row>();for(const frame of candidates)for(const row of frame.rows as Row[])universe.set(row.message_id as string,row);
    const next=rows.map((raw,i)=>{const patch=(p.patches as Row[])[i];if(raw===null){if(patch.retainCandidateId!==undefined)return null;return patch.insert as Row;}const row=raw as Row,set=patch.set as Row,remove=patch.remove as string[];if(!Object.keys(set).length&&!remove.length)return row;const f=flags(row);if(!f.callJournalShapeValid||f.callEntriesNonempty||!f.plaintextAbsentOrNull||!f.largePayloadAbsent)throw Error('conflict');const result={...row,...set};remove.forEach(k=>delete result[k]);return result;});
    for(const d of p.candidateDeletes as Row[]){const original=universe.get(d.messageId as string),replacement=(p.patches as Row[]).find(v=>v.messageId===d.replacementMessageId)?.insert;if(!original||!record(replacement))throw Error('conflict');guardDelete(original,replacement,p.chatId);universe.delete(d.messageId as string);}
    next.forEach(r=>{if(r)universe.set(r.message_id as string,r);});
    const active=queries.map(q=>rows[ids.indexOf(q.messageId as string)]===null),expectedAfterCandidates=frames(queries,active,universe,p.chatId),createHeader=metadata===null;
    const nextMetadata=createHeader?p.metadataInsert:metadata;
    // Complete pre/post/candidate/deletion receipt budget BEFORE first mutation.
    bounded({...packet(),metadata:nextMetadata,rows:next,candidates:expectedAfterCandidates,deleted:p.candidateDeletes});
    let pending=0;const done=()=>{if(--pending===0){bounded(packet());ready=true;}};
    if(createHeader){pending++;current();const add=chats.add(nextMetadata);add.onerror=()=>fail(add.error);add.onsuccess=()=>{try{current();const back=chats.get(p.chatId as string);back.onerror=()=>fail(back.error);back.onsuccess=()=>{try{current();if(!metadataInsert(back.result,p.chatId)||JSON.stringify(back.result)!==JSON.stringify(p.metadataInsert))throw Error('unavailable');metadata=back.result;done();}catch(e){fail(e);}};}catch(e){fail(e);}};}
    for(const d of p.candidateDeletes as Row[]){pending++;current();const request=messages.delete(d.messageId as string);request.onerror=()=>fail(request.error);request.onsuccess=()=>{try{current();const back=messages.get(d.messageId as string);back.onerror=()=>fail(back.error);back.onsuccess=()=>{try{current();if(back.result!==undefined)throw Error('unavailable');deleted.push(d);done();}catch(e){fail(e);}};}catch(e){fail(e);}};}
    next.forEach((value,i)=>{if(value===rows[i])return;pending++;current();const request=rows[i]===null?messages.add(value):messages.put(value);request.onerror=()=>fail(request.error);request.onsuccess=()=>{try{current();const back=messages.get(ids[i]);back.onerror=()=>fail(back.error);back.onsuccess=()=>{try{current();if(!record(back.result)||back.result.message_id!==ids[i]||JSON.stringify(back.result)!==JSON.stringify(value))throw Error('unavailable');rows[i]=back.result;done();}catch(e){fail(e);}};}catch(e){fail(e);}};});
    candidates=expectedAfterCandidates;deleted=[];if(!pending)ready=true;
   };
   const loaded=()=>{if(--remaining)return;current();if(metadata!==null&&(!record(metadata)||metadata.chat_id!==p.chatId))throw Error('unavailable');
    const active=queries.map(q=>rows[ids.indexOf(q.messageId as string)]===null);if(!active.some(Boolean)){planWrites();return;}
    const index=messages.index('chat_id_created_at');if(!Array.isArray(index.keyPath)||index.keyPath.length!==2||index.keyPath[0]!=='chat_id'||index.keyPath[1]!=='created_at')throw Error('unavailable');
    const request=index.openCursor(IDBKeyRange.bound([p.chatId,-Infinity],[p.chatId,Infinity]));request.onerror=()=>fail(request.error);request.onsuccess=()=>{try{current();const item=request.result;if(!item){planWrites();return;}const row=item.value;if(!record(row)||row.chat_id!==p.chatId)throw Error('unavailable');queries.forEach((q,i)=>{if(active[i]&&matches(row,q,p.chatId))(candidates[i].rows as Row[]).push(row);});bounded(packet());item.continue();}catch(e){fail(e);}};
   };
   const get=(store:IDBObjectStore,key:string,index:number|null)=>{const request=store.get(key);request.onerror=()=>fail(request.error);request.onsuccess=()=>{try{current();const raw=request.result;if(raw!==undefined&&(!record(raw)||index!==null&&raw.message_id!==key))throw Error('unavailable');if(index===null)metadata=raw??null;else rows[index]=raw??null;loaded();}catch(e){fail(e);}};};
   try{if(chats.keyPath!=='chat_id'||messages.keyPath!=='message_id')throw Error('unavailable');get(chats,p.chatId as string,null);ids.forEach((id,i)=>get(messages,id,i));}catch(e){fail(e);}
  });
 }finally{clearTimeout(timer);signal.removeEventListener('abort',abort);lifetime.abort();db?.close();}
}
