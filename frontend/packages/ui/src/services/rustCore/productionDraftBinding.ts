import {MAX_DRAFT_MARKDOWN_BYTES,validBrowserDraftResult,validBrowserDraftRestore} from './browserDraftProtocol';
import type {BrowserDraftHostPort,BrowserDraftEffectHandler,BrowserDraftResult,BrowserDraftRestore} from './browserDraftProtocol';
import type {SavedChatSelection} from './selectedSavedChat';
import type {SessionStatus} from './protocol';
export interface DraftEditorSession {
 save(input:{chatId:string;markdown:string},signal:AbortSignal,publishLocal:(result:BrowserDraftResult)=>void):Promise<void>;
 restore(chatId:string,signal:AbortSignal,publish:(result:BrowserDraftRestore)=>void):Promise<void>;
 close():Promise<void>;
}
const fields=['ownerId','chatId','teamId','workspaceEpoch','selectionGeneration','revision'] as const;
/** ORIGINAL admitted facade supplies these ports. Copies of status, owner JSON
 * or a guard callback confer no Rust authority; the actual Host/core resource
 * independently validates every request and final opaque publication.
 */
export function createProductionDraftBinding(input:{host:BrowserDraftHostPort;status:Readonly<SessionStatus>;signal:AbortSignal;
 current():void;verifyOriginal():Promise<void>;currentSelection():SavedChatSelection;profileGeneration:number;
 io:{createEffects(current:()=>void):BrowserDraftEffectHandler;clockSeconds():number}}):DraftEditorSession{
 // Capture the ORIGINAL facade ports before any asynchronous work. No later
 // mutation of the caller's input object may swap the Host/witness/IO factory.
 input=Object.freeze({host:Object.freeze({requestDraft:input.host.requestDraft.bind(input.host)}),status:Object.freeze({...input.status}),signal:input.signal,
  current:input.current.bind(input),verifyOriginal:input.verifyOriginal.bind(input),currentSelection:input.currentSelection.bind(input),profileGeneration:input.profileGeneration,
  io:Object.freeze({createEffects:input.io.createEffects.bind(input.io),clockSeconds:input.io.clockSeconds.bind(input.io)})});
 const root=new AbortController(),pending=new Set<Promise<void>>();let closed=false,closing:Promise<void>|null=null,tail=Promise.resolve(),drainFailure:unknown=null;
 const rootCurrent=()=>{if(closed||input.signal.aborted||root.signal.aborted)throw Error('invalidated_snapshot');input.current();};
 const abort=()=>{void close().catch(()=>undefined);};
 const own=(task:Promise<void>)=>{pending.add(task);void task.catch(()=>undefined).finally(()=>pending.delete(task));};
 const selected=(id:string)=>{rootCurrent();const selection=Object.freeze({...input.currentSelection()});if(selection.chatId!==id||selection.ownerId!==input.status.principal||selection.teamId!==null)throw Error('invalidated_snapshot');return selection;};
 const check=(selection:Readonly<SavedChatSelection>,signal:AbortSignal)=>{rootCurrent();if(signal.aborted||fields.some(field=>selection[field]!==input.currentSelection()[field]))throw Error('invalidated_snapshot');};
 const verify=async(selection:Readonly<SavedChatSelection>,signal:AbortSignal)=>{check(selection,signal);await input.verifyOriginal();check(selection,signal);};
 const handler=()=>input.io.createEffects(rootCurrent);
 const drain=async(effect:BrowserDraftEffectHandler)=>{try{await effect.close();}catch(error){drainFailure=error;throw error;}};
 const body=()=>({handle:input.status.handle,generation:input.status.generation,expectedPrincipal:input.status.principal});
 const signalFor=(source:AbortSignal)=>{const controller=new AbortController(),stop=()=>controller.abort();for(const s of[source,root.signal]){s.addEventListener('abort',stop,{once:true});if(s.aborted)stop();}return {signal:controller.signal,release(){for(const s of[source,root.signal])s.removeEventListener('abort',stop);}};};
 function save(value:{chatId:string;markdown:string},signal:AbortSignal,publishLocal:(result:BrowserDraftResult)=>void):Promise<void>{
  let selection:Readonly<SavedChatSelection>,bytes:Uint8Array;try{selection=selected(value.chatId);bytes=new TextEncoder().encode(value.markdown);if(bytes.length>MAX_DRAFT_MARKDOWN_BYTES)throw Error('draft_bounds');}catch(error){return Promise.reject(error);}
  let resolve!:()=>void,reject!:(error:unknown)=>void;const local=new Promise<void>((done,fail)=>{resolve=done;reject=fail;});
  const task=tail.catch(()=>undefined).then(async()=>{
   const linked=signalFor(signal);let localDone=false,resourceId:string|null=null,syncStarted=false;
   try{
    await verify(selection,linked.signal);const effect=handler();let reply;
    try{reply=await input.host.requestDraft({...body(),operation:'prepare_local_draft',chatId:selection.chatId,markdown:bytes,scope:{lifecycleGeneration:input.profileGeneration,workspaceEpoch:selection.workspaceEpoch},nowSeconds:input.io.clockSeconds()},linked.signal,effect);}finally{try{bytes.fill(0);}catch{/* Transferred request buffer may already be detached. */}await drain(effect);}
    if(reply.kind==='local')resourceId=reply.resourceId;
    await verify(selection,linked.signal);if(reply.kind!=='local'||!validBrowserDraftResult(reply.result)||reply.result.chatId!==selection.chatId||reply.result.remoteSynced)throw Error('invalid_draft_reply');
    // No await between final original witness/selection fence and local UI ack.
    check(selection,linked.signal);publishLocal(reply.result);localDone=true;resolve();
    const syncEffects=handler();syncStarted=true;try{const synced=await input.host.requestDraft({...body(),operation:'sync_draft',resourceId:reply.resourceId},linked.signal,syncEffects);
     await verify(selection,linked.signal);if(synced.kind!=='synced'||!validBrowserDraftResult(synced.result)||synced.result.chatId!==selection.chatId)throw Error('invalid_draft_reply');
    }finally{await drain(syncEffects);}
   }catch(error){
    if(error instanceof Error&&['draft_io_drain_failed','draft_worker_failed'].includes(error.message))drainFailure=error;
    if(resourceId&&!syncStarted&&!closed){try{const cleanup=handler();try{await input.host.requestDraft({...body(),operation:'close_draft',resourceId},root.signal,cleanup);}finally{await drain(cleanup);}}catch{/* Root shutdown retains its own exact resource registry. */}}
    if(!localDone)reject(error);/* Local ciphertext+intent remain durable on remote refusal. */
   }
   finally{try{bytes.fill(0);}catch{/* Transferred request buffer may already be detached. */}linked.release();}
  });tail=task;own(task);return local;
 }
 function restore(chatId:string,signal:AbortSignal,publish:(result:BrowserDraftRestore)=>void):Promise<void>{
  let selection:Readonly<SavedChatSelection>;try{selection=selected(chatId);}catch(error){return Promise.reject(error);}
  const task=tail.catch(()=>undefined).then(async()=>{const linked=signalFor(signal),effect=handler();let reply;try{
   await verify(selection,linked.signal);
   try{reply=await input.host.requestDraft({...body(),operation:'restore_local_draft',chatId,scope:{lifecycleGeneration:input.profileGeneration,workspaceEpoch:selection.workspaceEpoch}},linked.signal,effect);}finally{await drain(effect);}
   await verify(selection,linked.signal);if(reply.kind!=='restored'||!validBrowserDraftRestore(reply.result)||reply.result.chatId!==chatId)throw Error('invalid_draft_reply');
   check(selection,linked.signal);publish(reply.result);
  }finally{if(reply?.kind==='restored'){reply.result.markdown='';reply.result.preview=null;}linked.release();}});tail=task;own(task);return task;
 }
 function close():Promise<void>{if(closing)return closing;closed=true;root.abort();input.signal.removeEventListener('abort',abort);
  closing=Promise.allSettled([...pending]).then(()=>{if(drainFailure!==null)throw drainFailure;});return closing;}
 input.signal.addEventListener('abort',abort,{once:true});if(input.signal.aborted)abort();
 return Object.freeze({save,restore,close});
}
