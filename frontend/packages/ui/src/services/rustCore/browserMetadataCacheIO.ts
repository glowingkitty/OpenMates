/// <reference lib="es2022.object" />
import {boundedOriginalPhysicalDraft,boundedOriginalPhysicalDraftHeader} from './originalPhysicalDraftIOBudget';
import {createRustChatOpenRequest,createRustChatTransaction} from './browserAdapters';
import type {RustChatIORoutingLease} from './browserAdapters';
/** Inactive IO only: execute a Rust-issued metadata plan in existing chats_db.
 * The guard MUST bind the original admitted profile/key/request/lifecycle, never
 * owner labels supplied in JSON. No database open version, repair or upgrade.
 * No encryption, message/draft/status merge, credential ACK or product activation.
 */
import { boundedJson } from './savedReadProtocol';
import { awaitBrowserRead } from './existingSavedChatIO';
const DATABASE='chats_db',STORE='chats',MAX_BYTES=256*1024;
const CIPHERS=['encrypted_title','encrypted_chat_summary','encrypted_share_cta_text','encrypted_chat_tags',
 'encrypted_follow_up_request_suggestions','encrypted_suggested_followup_message','encrypted_icon','encrypted_category',
 'encrypted_active_focus_id','encrypted_focus_phase_state','encrypted_auto_speak_response'];
const WRITES=[...CIPHERS,'title_v','metadata_v'];
const COMPARE=['id','chat_id','user_id','team_id','hashed_team_id','chat_visibility','encrypted_chat_key','key_version','key_fingerprint',
 'title_v','metadata_v','messages_v','created_at','updated_at','last_edited_overall_timestamp','pinned',...CIPHERS];
type Row=Record<string,unknown>;
function record(value:unknown):value is Row{return !!value&&typeof value==='object'&&!Array.isArray(value);}
function exact(value:Row,fields:string[]):boolean{return Object.keys(value).length===fields.length&&fields.every(k=>Object.hasOwn(value,k));}
function integer(value:unknown):value is number{return Number.isSafeInteger(value)&&Number(value)>=0;}
function uuid(value:unknown):value is string{return typeof value==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);}
function normalBounded(value:unknown):string{if(!boundedJson(value))throw Error('unavailable');const encoded=JSON.stringify(value);if(new TextEncoder().encode(encoded).byteLength>MAX_BYTES)throw Error('unavailable');return encoded;}
function predicate(current:Row,expected:Row):boolean{return COMPARE.every(k=>Object.hasOwn(current,k)===Object.hasOwn(expected,k)&&(!Object.hasOwn(expected,k)||current[k]===expected[k]));}
const bounded=normalBounded;
function parse(encoded:string):Row{
 if(new TextEncoder().encode(encoded).byteLength>MAX_BYTES)throw Error('unavailable');
 const p:unknown=JSON.parse(encoded);if(!record(p)||!exact(p,['version','kind','operationId','scope','owner','chatId','database','store','databaseVersion','compareFields','expected','patch'])
 ||p.version!==1||!['capture','compare_and_patch','readback'].includes(String(p.kind))||!uuid(p.operationId)||!uuid(p.owner)||!uuid(p.chatId)
 ||p.database!==DATABASE||p.store!==STORE||!record(p.scope)||!exact(p.scope,['lifecycleGeneration','workspaceEpoch'])
 ||!integer(p.scope.lifecycleGeneration)||p.scope.lifecycleGeneration===0||!integer(p.scope.workspaceEpoch)
 ||!Array.isArray(p.compareFields)||p.compareFields.length!==COMPARE.length||!COMPARE.every((k,i)=>(p.compareFields as unknown[])[i]===k))throw Error('unavailable');
 if(p.kind==='capture'){if(p.databaseVersion!==null||p.expected!==null||p.patch!==null)throw Error('unavailable');}
 else{
  if(!integer(p.databaseVersion)||p.databaseVersion===0||!record(p.expected)||Object.keys(p.expected).some(k=>!COMPARE.includes(k)))throw Error('unavailable');
  if(p.kind==='readback'){if(p.patch!==null)throw Error('unavailable');}
  else if(!record(p.patch)||Object.keys(p.patch).some(k=>!WRITES.includes(k))||Object.entries(p.patch).some(([k,v])=>CIPHERS.includes(k)?v!==null&&typeof v!=='string':!integer(v)))throw Error('unavailable');
 }
 bounded(p);return p;
}
/** Resolves rich IO bytes only after actual transaction oncomplete. The returned
 * flags expressly attest NO native credential durability/cross-DB association.
 */
export async function executeBrowserMetadataCachePlan(factory:IDBFactory,encoded:string,signal:AbortSignal,guard:()=>void,routingLease?:RustChatIORoutingLease,originalPhysicalDraft?:true):Promise<string>{
 const bounded=(value:unknown):string=>{if(originalPhysicalDraft){const isHeader=!!value&&typeof value==='object'&&typeof Object.getOwnPropertyDescriptor(value,'chat_id')?.value==='string';if(!(isHeader?boundedOriginalPhysicalDraftHeader:boundedOriginalPhysicalDraft)(value))throw Error('unavailable');return JSON.stringify(value);}return normalBounded(value);};
 const p=parse(encoded);let db:IDBDatabase|null=null,transaction:IDBTransaction|null=null;
 const lifetime=new AbortController();let invalid=false;
 const current=()=>{if(invalid||signal.aborted||lifetime.signal.aborted)throw Error('cancelled');guard();};
 const abort=()=>{invalid=true;lifetime.abort();try{transaction?.abort();}catch{/* Only transaction terminal may settle an issued effect. */}};
 signal.addEventListener('abort',abort,{once:true});const timer=setTimeout(abort,5000);
 try{
  current();if(typeof factory.databases!=='function')throw Error('unavailable');
  const observed=await awaitBrowserRead(factory.databases(),lifetime.signal);current();const version=observed.find(row=>row.name===DATABASE&&integer(row.version)&&Number(row.version)>0)?.version;
  if(version===undefined||p.databaseVersion!==null&&version!==p.databaseVersion)throw Error('unavailable');
  db=await new Promise<IDBDatabase>((resolve,reject)=>{
   const request=routingLease?createRustChatOpenRequest(routingLease,factory):factory.open(DATABASE);let settled=false;
   const fail=()=>{if(!settled){settled=true;lifetime.signal.removeEventListener('abort',fail);reject(Error('unavailable'));}};
   lifetime.signal.addEventListener('abort',fail,{once:true});
   request.onupgradeneeded=()=>{request.transaction?.abort();fail();};request.onblocked=request.onerror=fail;
   request.onsuccess=()=>{const opened=request.result;try{current();if(settled||opened.version!==version)throw Error('unavailable');settled=true;lifetime.signal.removeEventListener('abort',fail);resolve(opened);}catch{opened.close();fail();}};
  });current();db.onversionchange=()=>{abort();db?.close();};
  if(!db.objectStoreNames.contains(STORE))throw Error('unavailable');
  const opened=db;
  return await new Promise<string>((resolve,reject)=>{
   let before:unknown=null,after:unknown=null,failure:unknown=null;
   const fail=(error:unknown)=>{failure??=error;try{transaction!.abort();}catch{/* Terminal handler still owns the issued transaction. */}};
   current();transaction=routingLease?createRustChatTransaction(routingLease,opened,STORE,p.kind==='compare_and_patch'?'readwrite':'readonly'):opened.transaction(STORE,p.kind==='compare_and_patch'?'readwrite':'readonly');
   transaction.onabort=()=>reject(failure??Error('storage_failed'));
   transaction.onerror=()=>{failure??=Error('storage_failed');};
   transaction.oncomplete=()=>{try{current();if(failure)throw failure;
    resolve(bounded({version:1,kind:p.kind,operationId:p.operationId,databaseVersion:opened.version,transactionCommitted:true,credentialAcknowledged:false,crossDatabaseAssociationProven:false,record:after,before}));
   }catch(error){reject(error);}};
   const store=transaction.objectStore(STORE),read=store.get(p.chatId as string);
   read.onerror=()=>fail(read.error);read.onsuccess=()=>{try{
    current();const raw:unknown=read.result;if(!record(raw)||raw.chat_id!==p.chatId)throw Error('unavailable');bounded(raw);
    if(p.kind!=='capture'&&!predicate(raw,p.expected as Row))throw Error('conflict');
    if(p.kind==='compare_and_patch'){
     before=raw;const next={...raw,...p.patch as Row};bounded(next);
     // Refuse an over-budget prospective receipt BEFORE putting any bytes.
     bounded({version:1,kind:p.kind,operationId:p.operationId,databaseVersion:opened.version,transactionCommitted:true,credentialAcknowledged:false,crossDatabaseAssociationProven:false,record:next,before:raw});
     const put=store.put(next);put.onerror=()=>fail(put.error);
     put.onsuccess=()=>{try{current();const back=store.get(p.chatId as string);back.onerror=()=>fail(back.error);back.onsuccess=()=>{try{current();bounded(back.result);after=back.result;}catch(error){fail(error);}};}catch(error){fail(error);}};
    }else after=raw;
   }catch(error){fail(error);}};
  });
 }finally{clearTimeout(timer);signal.removeEventListener('abort',abort);lifetime.abort();db?.close();}
}
