/** SDK-required partial until native/cross-SDK CI acceptance. Direct bindings only. */
import {SessionClientError,type SessionCacheChatPublication,type SessionChat} from './sdkSession.js';
import type {SessionDurableStore,SessionChatRefresh,SessionChatDurableReceipt} from './sdkEssential.js';
export type NativeFirstPage={
 firstPageOpen(id:string,includeSecrets:boolean,includePrivateOutput:boolean):Promise<string>;
 firstPageNext(id:string):Promise<string>;
 firstPageReceipt(id:string,stageId:string,receipt:string):void;
 firstPageCapacity(id:string,stageId:string,accepted:boolean):void;
 firstPageClose(id:string):void;
};
export type SessionFirstPagePublication={kind:'first_page';source:'first_page';chat:SessionChat;cached:true;refreshing:true;history_complete:false;has_more_before:true;pii_restoration:'page_local'};
export type SessionFirstPageStore=SessionDurableStore&{admitFirstPage(input:{scope:SessionChatRefresh['scope'];checkpointJsonBytes:number}):Promise<boolean>};
export type SessionFirstPageOptions={includeSecrets:true;includePrivateOutput:true;onFirstPage:(page:SessionFirstPagePublication)=>void|Promise<void>;signal?:AbortSignal};
type Invoke=<T>(operation:()=>Promise<T>)=>Promise<T>;
type Stage=SessionChatRefresh&{kind:'stage';source:'first_page'|'canonical'|'cache_settled'|'cached_offline'};
function protocol():never{throw new SessionClientError('protocol','Invalid first-page continuation event.');}
export async function readChatWithFirstPage(native:NativeFirstPage,invoke:Invoke,current:()=>boolean,chatId:string,store:SessionFirstPageStore,options:SessionFirstPageOptions):Promise<SessionCacheChatPublication>{
 if(options?.includeSecrets!==true||options?.includePrivateOutput!==true||typeof options?.onFirstPage!=='function'||typeof store?.admitFirstPage!=='function'||typeof store?.generation!=='function'||typeof store?.compareAndSwap!=='function')throw new SessionClientError('invalid_argument','Supply explicit credential/private-output consent, durable store and first-page callback.');
 let id:string|undefined;let closed=false;let firstSeen=false;let pendingSource:Stage['source']|undefined;let capacitySeen=false;let capacityAccepted=false;
 const close=()=>{closed=true;if(id)try{native.firstPageClose(id);}catch{/* Only this owned operation; already completed is harmless. */}};
 const valid=()=>{if(closed||options.signal?.aborted||!current())throw new SessionClientError('cancelled','The first-page read is no longer current.');};
 options.signal?.addEventListener('abort',close,{once:true});
 try{
  valid();const opened=JSON.parse(await invoke(()=>native.firstPageOpen(chatId,true,true)));if(typeof opened.id!=='string')protocol();id=opened.id;valid();
  while(true){
   valid();const event=JSON.parse(await invoke(()=>native.firstPageNext(id!)));valid();
   if(event.kind==='capacity'){
    if(capacitySeen||firstSeen||pendingSource!==undefined||typeof event.id!=='string'||!Number.isSafeInteger(event.checkpoint_json_bytes)||event.checkpoint_json_bytes<0||!event.scope||typeof event.scope.api_url!=='string'||typeof event.scope.account_id!=='string')protocol();
    capacitySeen=true;
    const accepted=await store.admitFirstPage({scope:event.scope,checkpointJsonBytes:event.checkpoint_json_bytes});valid();
    if(typeof accepted!=='boolean')protocol();capacityAccepted=accepted;
    await invoke(async()=>native.firstPageCapacity(id!,event.id,accepted));valid();continue;
   }
   if(event.kind==='stage'){
    const stage=event as Stage;
    if(pendingSource!==undefined||typeof stage.id!=='string'||typeof stage.checkpoint_json!=='string'||typeof stage.credentials_json!=='string'||typeof stage.ciphertext_sha256!=='string'||!Number.isSafeInteger(stage.credential_revision)||!stage.scope||typeof stage.scope.api_url!=='string'||typeof stage.scope.account_id!=='string'||!['first_page','canonical','cache_settled','cached_offline'].includes(stage.source))protocol();
    if(stage.source==='first_page'&&(!capacitySeen||!capacityAccepted||firstSeen))protocol();
    const expectedVersion=await store.generation(stage.scope);valid();
    const receipt=await store.compareAndSwap({scope:stage.scope,expectedVersion,nextVersion:stage.id,checkpointJson:stage.checkpoint_json,credentialsJson:stage.credentials_json,ciphertextSha256:stage.ciphertext_sha256,credentialRevision:stage.credential_revision});valid();
    if(receipt.stored!==true)throw new SessionClientError('conflict','The durable chat scope changed before persistence.');
    // Forward only the ACTUAL writer's exact receipt, never DTO-derived ACKs.
    const actual:SessionChatDurableReceipt={ciphertext_sha256:receipt.ciphertext_sha256,credential_revision:receipt.credential_revision};
    await invoke(async()=>native.firstPageReceipt(id!,stage.id,JSON.stringify(actual)));valid();pendingSource=stage.source;continue;
   }
   if(event.kind==='first_page'){
    if(pendingSource!=='first_page'||firstSeen||event.source!=='first_page'||event.chat?.id!==chatId||event.cached!==true||event.refreshing!==true||event.history_complete!==false||event.has_more_before!==true||event.pii_restoration!=='page_local')protocol();
    pendingSource=undefined;firstSeen=true;
    await options.onFirstPage(event as SessionFirstPagePublication);valid();
    // Only this next pull allows the original Rust reader to request older IO.
    continue;
   }
   if(event.kind==='completed'){
    if(pendingSource===undefined||pendingSource==='first_page'||event.source!==pendingSource||event.chat?.id!==chatId||event.refreshing!==false||!Array.isArray(event.chat?.messages))protocol();
    if(event.source==='canonical'?(event.cached!==false||event.history_complete!==true||event.pii_restoration!=='all_user_rows'||event.has_more_before!==false):(event.cached!==true||event.history_complete!==false||event.pii_restoration!==(event.source==='cache_settled'?'all_cached_user_rows':'page_local')))protocol();
    valid();return event as SessionCacheChatPublication;
   }
   protocol();
  }
 }finally{options.signal?.removeEventListener('abort',close);close();}
}
