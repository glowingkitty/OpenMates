/// <reference lib="es2022.object" />
import {validFirstSessionTerminal} from "./protocol";
import {validProfileCacheInvalidation} from './profileCacheProtocol';
import type {SessionStatus} from './protocol';
import {createOwnedLocalReadState,beginOwnedLocalRead,completeOwnedLocalRead,ownedLocalReadReady,ownedLocalReadFallbackReady} from './ownedLocalReadProtocol';
import {MAX_INITIAL_SYNC_REQUEST_MS} from './protocol';
import {validBrowserCacheRecoveryProgress} from './browserCacheProtocol';
import type {BrowserRecoveryBootstrap} from './browserRecoveryTransport';
import {createBrowserDraftHostChannel} from './browserDraftTransport';
import type {BrowserDraftRequest,BrowserDraftReply,BrowserDraftEffectHandler} from './browserDraftProtocol';
import { readNativeChatIOMessage, observeRustChatIORootInvalidation, assertRustChatIORootResource, enrollNativeRustChatIORoot, assertNativeRustChatIOFactory, revokeRustChatIORoot, recordNativeRustChatRestoreAdmission, revokeNativeRustChatIOFactory } from './browserAdapters';
import type { NativeRustChatIOFactory, RustChatIORoot, RustChatIOPorts } from './browserAdapters';
import {advanceBrowserCachePlan,browserCachePlansComplete,validBrowserCacheEffect,validBrowserCacheReply,validBrowserCachePrepared,validBrowserCacheDrained,validBrowserCacheSelected,validBrowserCacheSourceEvidence,retainedKindMatches,validBrowserOwnedCacheTerminal,sameBrowserOwnedCacheIdentity} from './browserCacheProtocol';
import type {BrowserCacheScope,BrowserCacheEffectHandler,BrowserOwnedCacheIdentity} from './browserCacheProtocol';
import { advanceLocalReadPlan, validLocalCursorEffect, validLocalCursorReply } from "./protocol";
import type { LocalCursorEffectHandler } from "./protocol";
import {openAuthRefreshEffectLease} from "./browserAdapters";
import {validCredentialEffectMessage,validCredentialIOResult,credentialIOError} from "./credentialCasProtocol";
import { validSendEvent } from "./sendProtocol";
import { MAX_PENDING_REQUESTS, MAX_REQUEST_MS, MAX_PASSWORD_REQUEST_MS, clearPasswordRequest, clearExistingKeyRequest, validRequest, validResponse } from "./protocol";
import type { SendTerminalDisposition } from "./sendProtocol";
import type { CoreResponse } from "./protocol";

import type {RequestBody,Pending,BrowserSelectedCacheProgress,BrowserCredentialEffectHandler} from "./workerHostTypes";
/** Same test as `!response.ok`, expressed as a guard that also narrows without strictNullChecks. */
function failedResponse(response:CoreResponse):response is Extract<CoreResponse,{ok:false}>{return !response.ok;}
export type {BrowserCredentialEffectHandler,BrowserSelectedCacheProgress} from "./workerHostTypes";

/** Inactive, page-owned transport only. Session decisions stay entirely in Rust.
 * No SharedWorker, automatic retry, cookies, fetch, key export or reducer here.
 */
export class BrowserCoreWorkerHost {
  private readonly worker: Worker;
  private readonly drafts:ReturnType<typeof createBrowserDraftHostChannel>;
  private readonly pending = new Map<number, Pending>();
  private lastInitialDispatch=0;
  private readonly sends = new Map<string, { handle: string; generation: number; chatId: string | undefined }>();
  private readonly terminals = new WeakMap<object,{handle:string;generation:number;operationId:string;value:SendTerminalDisposition}>();
  private readonly deferredNativeFinals=new WeakMap<MessageEvent<unknown>,{raw:CoreResponse;snapshot:CoreResponse}>();
  /** Exact original Worker response only. Copied JSON/status/error strings never
   * become a retained-session proof; this transport correlation is one-use. */
  consumeSendTerminal(response:CoreResponse,handle:string,generation:number,operationId:string):SendTerminalDisposition|null {
    const original=this.terminals.get(response);
    if(!original||this.closed||original.handle!==handle||original.generation!==generation||original.operationId!==operationId)return null;
    this.terminals.delete(response);return original.value;
  }
  private nextId = 1;
  private closed = false;
  private existingKeyMode = false;
  private nativeRestoreEvent: MessageEvent<unknown> | null = null;
  private readonly profileCacheAbsences=new WeakMap<object,{handle:string;generation:number;owner:string;chatId:string;scope:BrowserCacheScope}>();
  private profileCacheNegative=false;
  private profileCacheRestoreStatus:Readonly<SessionStatus>|null=null;
  private readonly profileCacheListeners=new Set<()=>void>();
  /** Negative check/correlation only; the original native resource separately
   * owns every read and all profile/key/admission decisions. */
  assertProfileCacheCurrent(status:Readonly<SessionStatus>):void {
    const original=this.profileCacheRestoreStatus;
    if(this.closed||this.profileCacheNegative||!original||!this.nativeRestoreEvent||!this.existingKeyMode
      ||this.expectedPrincipal!==original.principal||(['handle','generation','principal','persistence','localReadOnly'] as const).some(k=>status[k]!==original[k]))throw Error('invalidated_snapshot');
    const response=readNativeChatIOMessage(this.nativeRestoreEvent,this.worker);
    if(!validResponse(response)||!response.ok||!response.status||(['handle','generation','principal','persistence','localReadOnly'] as const).some(k=>response.status![k]!==original[k]))throw Error('invalidated_snapshot');
  }
  subscribeProfileCacheInvalidation(status:Readonly<SessionStatus>,callback:()=>void):()=>void {
    this.assertProfileCacheCurrent(status);
    if(typeof callback!=='function')throw Error('invalid_request');
    this.profileCacheListeners.add(callback);
    return()=>{this.profileCacheListeners.delete(callback);};
  }
  private invalidateProfileCache():void {
    if(this.profileCacheNegative)return;
    this.profileCacheNegative=true;
    const listeners=[...this.profileCacheListeners];this.profileCacheListeners.clear();
    for(const callback of listeners)try{callback();}catch{/* Notify every negative observer without private logging. */}
  }
  /** One-use correlation of an actual Core-consumed absence after BOTH original
   * native/Worker terminals. It grants no authentication, cold IO or storage. */
  consumeProfileCacheAbsence(reply:CoreResponse,status:Readonly<SessionStatus>,chatId:string,scope:Readonly<BrowserCacheScope>):boolean {
    const original=this.profileCacheAbsences.get(reply);this.profileCacheAbsences.delete(reply);
    try{this.assertProfileCacheCurrent(status);}catch{return false;}
    return !!original&&original.handle===status.handle&&original.generation===status.generation&&original.owner===status.principal&&original.chatId===chatId
      &&original.scope.lifecycleGeneration===scope.lifecycleGeneration&&original.scope.workspaceEpoch===scope.workspaceEpoch;
  }
  private profileCacheInvalidated(frame:unknown,event:MessageEvent<unknown>):void {
    try{
      if(!validProfileCacheInvalidation(frame)||readNativeChatIOMessage(event,this.worker)!==frame)throw Error('unavailable');
      const original=this.profileCacheRestoreStatus,negative=frame.profileCacheInvalidated;
      if(!original||!this.nativeRestoreEvent||this.expectedPrincipal!==original.principal||negative.owner!==original.principal
        ||negative.handle!==original.handle||negative.generation!==original.generation)throw Error('unavailable');
      this.invalidateProfileCache();
    }catch{this.close('unavailable');}
  }
  private firstCloseWait:{promise:Promise<void>;resolve:()=>void;reject:(error:unknown)=>void;reason:'session_expired'|'cancelled'|'deadline'|'unavailable'}|null=null;
  /** Negative only. A caller timeout/abort cannot attest original task return. */
  cancelFirstSession():void {
    for(const [id,pending] of this.pending)if(pending.firstSession)this.stopFirstSession(id,'cancelled');
  }
  private stopFirstSession(id:number,reason:'cancelled'|'deadline'|'unavailable'):void {
    const operation=this.pending.get(id)?.firstSession;if(!operation||operation.stopReason)return;
    operation.stopReason=reason;this.firstSessionAdmission=null;
    try{this.worker.postMessage({version:1,id,firstSessionStop:{requestId:id}});}catch{
      // Unknown transport/native progress stays held. No close/reject/ACK may
      // release the Page's original serialized auth operation/WebLock.
    }
  }
  private firstSessionTerminal(frame:unknown,event:MessageEvent<unknown>):void {
    const id=typeof frame==='object'&&frame!==null&&'id' in frame?Number(frame.id):0;
    const pending=this.pending.get(id),operation=pending?.firstSession;
    try{
      if(!operation||!validFirstSessionTerminal(frame)||readNativeChatIOMessage(event,this.worker)!==frame||operation.terminal)throw Error('unavailable');
      operation.terminal=true;this.finishFirstSession(id,pending!);
    }catch{if(operation)this.stopFirstSession(id,'unavailable');else this.close('unavailable');}
  }
  private finishFirstSession(id:number,pending:Pending):void {
    const operation=pending.firstSession;
    if(!operation?.terminal||!operation.response||!operation.event)return;
    const data=operation.response,event=operation.event;let failure:Error|null=null;
    try{
      if(readNativeChatIOMessage(event,this.worker)!==data||JSON.stringify(data)!==operation.serialized)throw Error('unavailable');
      if(operation.stopReason)throw Error(operation.stopReason);
      if(data.ok){
        if(!data.firstSession)throw Error('unavailable');
        if(operation.dataOnly&&data.status)throw Error('unavailable');
        if(data.status){
          if(data.firstSession.httpStatus!==200||data.firstSession.data?.success!==true||data.status.principal!==operation.principal
            ||data.status.principal!==this.expectedPrincipal||data.status.persistence!=='memory_only'||typeof data.status.localReadOnly!=='boolean'||!this.nativeChatIssuer)throw Error('unavailable');
          recordNativeRustChatRestoreAdmission(this.nativeChatIssuer,this.worker,event,data.id);
          this.existingKeyMode=true;this.nativeRestoreEvent=event;this.profileCacheRestoreStatus=Object.freeze({...data.status});
          this.firstSessionAdmission={response:data,event,serialized:JSON.stringify(data)};
        }
      }
    }catch(error){failure=error instanceof Error?error:Error('unavailable');}
    // BOTH original native response and typed original-task return observed.
    // This releases only this RPC; no HTTP/global/native-drain claim is made.
    this.pending.delete(id);clearTimeout(pending.timer);pending.dispose();
    if(failure)pending.reject(failure);else pending.resolve(data);
    const closing=this.firstCloseWait;this.firstCloseWait=null;
    if(closing)void this.closeAndDrain(closing.reason).then(closing.resolve,closing.reject);
    else if(failure?.message==='unavailable')this.close('unavailable');
  }
  private firstSessionDispatched=false;
  private firstSessionDataOnlyDispatched=false;
  private firstSessionAdmission:{response:CoreResponse;event:MessageEvent<unknown>;serialized:string}|null=null;
  /** One-use correlation with the actual original native reply. UI response
   * data/status/copies cannot manufacture admission or enroll another Host. */
  consumeFirstSessionAdmission():CoreResponse|null {
    const original=this.firstSessionAdmission;this.firstSessionAdmission=null;
    if(!original||this.closed||this.nativeRestoreEvent!==original.event)return null;
    try{
      if(readNativeChatIOMessage(original.event,this.worker)!==original.response||JSON.stringify(original.response)!==original.serialized
        ||!original.response.ok||!original.response.status||!original.response.firstSession)return null;
      this.assertProfileCacheCurrent(original.response.status);return original.response;
    }catch{return null;}
  }
  private recoveryRootAdmission:MessageEvent<unknown>|null=null;
  private recoveryRestoreRequested=false;
  private recoveryRetired=false;
  private recoveryDrain:Promise<void>|null=null;
  private retireRecoveryTransport():Promise<void>|null{
    if(!this.recoveryBootstrap)return null;
    if(!this.recoveryRetired){this.recoveryRetired=true;this.recoveryBootstrap.revoke();}
    return this.recoveryDrain??=this.recoveryBootstrap.closeAndDrain();
  }
  private readonly nativeChatRoots = new Set<RustChatIORoot>();
  private readonly nativeRootAdmissions = new WeakMap<object, MessageEvent<unknown>>();
  assertChatIORootResource(root: RustChatIORoot): void {
    if (this.closed || !this.nativeChatRoots.has(root) || this.nativeRootAdmissions.get(root) !== this.nativeRestoreEvent) throw Error('invalidated_snapshot');
    assertRustChatIORootResource(root);
  }
  private closing: Promise<void> | null = null;

  /** Optional per-original-resource platform routing. Native admission does not
   * replace the session's original witness/key/context checks. */
  openChatIORoot(factory: IDBFactory, originalCurrent: () => void): RustChatIORoot {
    if (!this.nativeChatIssuer || !this.nativeRestoreEvent || this.closed || !this.existingKeyMode) throw Error('invalidated_snapshot');
    const admission = this.nativeRestoreEvent, originalWorker = this.worker;
    const current = () => {
      if (this.closed || this.worker !== originalWorker || this.nativeRestoreEvent !== admission || !this.existingKeyMode) throw Error('invalidated_snapshot');
      originalCurrent();
    };
    assertNativeRustChatIOFactory(this.nativeChatIssuer, originalWorker, factory);
    const root = enrollNativeRustChatIORoot({issuer:this.nativeChatIssuer,worker:originalWorker,factory,current,
      closeAndDrain:()=>this.closeAndDrain()}, admission);
    this.nativeChatRoots.add(root); this.nativeRootAdmissions.set(root, admission);
    // A trusted original connection negative must clear idle private children,
    // even when no further action/IO/currentness check occurs.
    observeRustChatIORootInvalidation(root,()=>this.invalidateProfileCache());
    if(this.recoveryBootstrap&&!this.recoveryRetired){
      if(this.recoveryRootAdmission&&this.recoveryRootAdmission!==admission)throw Error('invalidated_snapshot');
      if(!this.recoveryRootAdmission){this.recoveryBootstrap.bindRoot(this.nativeChatIssuer,root);this.recoveryRootAdmission=admission;}
    }
    return root;
  }

  /** Only sealed actual ports minted by this original Root's routing lease. */
  bindRecoveryInventoryPorts(ports:RustChatIOPorts):void{
    if(this.closed)throw Error('invalidated_snapshot');
    if(this.recoveryBootstrap&&!this.recoveryRetired)this.recoveryBootstrap.bindInventoryPorts(ports);
  }

  private readonly credentialEffects:BrowserCredentialEffectHandler|null;
  constructor(worker: Worker,effects?:(issuer:object)=>BrowserCredentialEffectHandler,private readonly expectedPrincipal:string|null=null,private readonly nativeChatIssuer?:NativeRustChatIOFactory,private readonly recoveryBootstrap?:BrowserRecoveryBootstrap) {
    if(expectedPrincipal!==null&&!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(expectedPrincipal)){worker.terminate();throw Error("invalid_request");}
    try{this.credentialEffects=effects?effects(this):null;}catch{worker.terminate();throw Error("session_expired");}
    this.worker = worker;
    this.drafts=createBrowserDraftHostChannel({worker,expectedPrincipal:this.expectedPrincipal,current:()=>{if(this.closed)throw Error("session_expired");},fatal:()=>this.close("unavailable")});
    worker.addEventListener("message", this.receive);
    worker.addEventListener("messageerror", this.fail);
    worker.addEventListener("error", this.fail);
  }

  /** Draft requests retain actual opaque Rust resources on this SAME Host. */
  requestDraft(body:BrowserDraftRequest,signal:AbortSignal,effects:BrowserDraftEffectHandler):Promise<BrowserDraftReply>{
    return this.drafts.requestDraft(body,signal,effects);
  }

  request(body: RequestBody, signal: AbortSignal, timeoutMs = MAX_REQUEST_MS, localEffects?: LocalCursorEffectHandler, cacheEffects?:BrowserCacheEffectHandler, selectedProgress?:BrowserSelectedCacheProgress): Promise<CoreResponse> {
    // Credentials are consumed even on local refusal; none enter Pending.
    const reject=(reason:string)=>{clearPasswordRequest(body);clearExistingKeyRequest(body);return Promise.reject(new Error(reason));};
    if(this.firstSessionDataOnlyDispatched)return reject("unavailable");
    if (this.closed||this.firstCloseWait) return reject("session_expired");
    if(typeof body!=="object"||body===null||Object.values(Object.getOwnPropertyDescriptors(body)).some(descriptor=>!("value"in descriptor)))return reject("invalid_request");
    if (signal.aborted) return reject("cancelled");
    if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > (body.operation === "login_password" ? MAX_PASSWORD_REQUEST_MS : body.operation==='run_initial_sync'?MAX_INITIAL_SYNC_REQUEST_MS:MAX_REQUEST_MS)
      || this.pending.size >= MAX_PENDING_REQUESTS || this.nextId >= Number.MAX_SAFE_INTEGER) {
      return reject("invalid_request");
    }
    if(Object.hasOwn(body,'ownedCache'))return reject('invalid_request');
    const id = this.nextId++;
    const ownedCache=body.operation==='read_cold_retained_saved_chat'||body.operation==='read_cache_monitor_update'&&!!selectedProgress;
    const message:unknown = { ...body, version: 1, id,...(ownedCache?{ownedCache:true}:{}) };
    if (!validRequest(message)) return reject("invalid_request");
    if((message.operation==="restore_existing"||message.operation==="restore_local"||message.operation==='check_first_session')&&(this.expectedPrincipal===null||message.profile.principal!==this.expectedPrincipal))return reject("invalid_request");
    if(message.operation==='check_first_session_data'&&this.expectedPrincipal===null)return reject('invalid_request');
    if(this.expectedPrincipal!==null&&(message.operation==="restore"||message.operation==="login_password"))return reject("unavailable");
    if((message.operation==="read_local_chat"||message.operation==="read_local_saved_chat"||message.operation==="read_local_saved_chat_cursor"||message.operation==="read_online_cached_saved_chat"||message.operation==="read_local_checkpoint_summary")
      && (!this.existingKeyMode||this.expectedPrincipal!==message.expectedPrincipal))return reject("unavailable");
    if((message.operation==="read_local_saved_chat_cursor"||message.operation==="read_online_cached_saved_chat"||message.operation==="read_local_checkpoint_summary")&&!localEffects)return reject("unavailable");
    if(message.operation!=="read_local_saved_chat_cursor"&&message.operation!=="read_online_cached_saved_chat"&&message.operation!=="read_local_checkpoint_summary"&&localEffects)return reject("invalid_request");
    const cacheOperation=message.operation==='restore_cached_metadata'||message.operation==='read_cached_chat_items'||(message.operation==='read_retained_saved_chat'||message.operation==='read_cold_retained_saved_chat'||message.operation==='read_monitored_retained_saved_chat'||message.operation==='read_cache_monitor_update');
    if(cacheOperation&&!cacheEffects||!cacheOperation&&cacheEffects)return reject('invalid_request');
    if(selectedProgress&&(message.operation!=='read_cache_monitor_update'||typeof selectedProgress.onSelected!=='function'||typeof selectedProgress.createContinuationEffects!=='function'))return reject('invalid_request');
    const progressOwner=selectedProgress?Object.freeze({onSelected:selectedProgress.onSelected.bind(selectedProgress),createContinuationEffects:selectedProgress.createContinuationEffects.bind(selectedProgress)}):undefined;
    const ownedIdentity:BrowserOwnedCacheIdentity|undefined=ownedCache&&(message.operation==='read_cold_retained_saved_chat'||message.operation==='read_cache_monitor_update')?{operation:message.operation,handle:message.handle,generation:message.generation,owner:message.expectedPrincipal,chatId:message.chatId,...('monitorId'in message?{monitorId:message.monitorId}:{})}:undefined;
    const profileCache=message.operation==='read_cold_retained_saved_chat'&&message.profileCache===true;
    if(profileCache){try{const original=this.profileCacheRestoreStatus;if(!original||message.handle!==original.handle||message.generation!==original.generation||message.expectedPrincipal!==original.principal)throw Error('invalidated_snapshot');this.assertProfileCacheCurrent(original);}catch{return reject('unavailable');}}
    const cacheCurrent=cacheEffects?()=>{if(profileCache)this.assertProfileCacheCurrent(this.profileCacheRestoreStatus!);cacheEffects.current();}:undefined;
    if(this.closed)return reject('session_expired');
    if(signal.aborted)return reject('cancelled');
    if(cacheOperation&&this.expectedPrincipal!==null&&message.expectedPrincipal!==this.expectedPrincipal)return reject('unavailable');
    if(message.operation==="rotate_credentials"&&!this.credentialEffects)return reject("unavailable");
    if (message.operation === "invalidate" || message.operation === "cancel") {
      this.close();
      return Promise.resolve({ version: 1, id, ok: true, status: null });
    }
    let expectedSend: Pending["expectedSend"];
    if (message.operation === "start_new_send") expectedSend = { handle: message.handle, generation: message.generation, chatId:undefined, kind:"started" };
    if (message.operation === "start_send") expectedSend = { handle: message.handle, generation: message.generation, chatId: message.chatId, kind: "started" };
    if (message.operation === "next_send_event" || message.operation === "cancel_send" || message.operation === "close_send") {
      const owned = this.sends.get(message.operationId);
      if (!owned || owned.handle !== message.handle || owned.generation !== message.generation) return reject("session_expired");
      expectedSend = { ...owned, operationId: message.operationId, kind: message.operation === "next_send_event" ? "event" : message.operation === "cancel_send" ? "cancel_requested" : "closed" };
    }
    return new Promise((resolve, reject) => {
      // Auth/restore cancellation still destroys the dedicated Worker. An
      // explicitly owned read stops only its original Rust resource and drains.
      const cancel = () => (message.operation==='check_first_session'||message.operation==='check_first_session_data')?this.stopFirstSession(id,'cancelled'):ownedCache?this.stopOwnedCache(id,'cancelled'):message.operation==='run_initial_sync'?this.stopInitialSync(id,'cancelled'):this.close("cancelled");
      const timer = setTimeout(() => (message.operation==='check_first_session'||message.operation==='check_first_session_data')?this.stopFirstSession(id,'deadline'):ownedCache?this.stopOwnedCache(id,'deadline'):message.operation==='run_initial_sync'?this.stopInitialSync(id,'deadline'):this.close("deadline"), timeoutMs);
      const dispose = () => signal.removeEventListener("abort", cancel);
      this.pending.set(id, { resolve, reject, timer, dispose, expectedSend,
        ...((message.operation==='restore_cached_metadata'||message.operation==='read_cached_chat_items'||(message.operation==='read_retained_saved_chat'||message.operation==='read_cold_retained_saved_chat'||message.operation==='read_monitored_retained_saved_chat'||message.operation==='read_cache_monitor_update'))?{cache:{
          operation:message.operation,handle:message.handle,generation:message.generation,owner:message.expectedPrincipal,
          ids:'chatId' in message?[message.chatId]:[...message.chatIds],
          ...(message.operation==='read_cache_monitor_update'?{monitorId:message.monitorId}:{}),
          ...(message.operation==='read_cached_chat_items'?{}:{scope:{...message.scope}}),handler:cacheEffects!,controller:new AbortController(),
          state:{effects:0,rows:new Map()},...(message.operation==='read_cold_retained_saved_chat'&&(message.localFirst||message.profileCache)?{localRead:createOwnedLocalReadState(),...(message.profileCache?{profileCache:true as const}:{})}:{}),effectId:0,inFlight:false,terminal:Promise.resolve(),draining:false,drained:false,publicationId:null,originalCurrent:cacheCurrent!,...(progressOwner?{progressOwner}:{}),...(ownedIdentity?{ownedIdentity,dispatched:false}:{})}}:{}),
        ...((message.operation==="read_local_saved_chat_cursor"||message.operation==="read_online_cached_saved_chat"||message.operation==="read_local_checkpoint_summary")?{localCursor:{selector:message.operation==="read_local_checkpoint_summary"?{direction:"checkpoint_summary" as const,checkpointId:message.checkpointId}:structuredClone(message.selector),planState:{effects:0,payloadRows:0},handler:localEffects!,controller:new AbortController(),effectId:0,inFlight:false,terminal:Promise.resolve()}}:{}),
        ...(message.operation==="read_local_checkpoint_summary"?{expectedCheckpoint:{handle:message.handle,generation:message.generation,principal:message.expectedPrincipal,chatId:message.chatId,checkpointId:message.checkpointId}}:{}),
        ...((message.operation==="read_local_chat"||message.operation==="read_local_saved_chat"||message.operation==="read_local_saved_chat_cursor")?{expectedLocal:{handle:message.handle,generation:message.generation,principal:message.expectedPrincipal,chatId:message.chatId,saved:message.operation!=="read_local_chat"}}:{}),
        ...(message.operation==="read_online_cached_saved_chat"?{expectedLocal:{handle:message.handle,generation:message.generation,principal:message.expectedPrincipal,chatId:message.chatId,saved:true,online:true as const}}:{}),
        ...(message.operation==='run_initial_sync'?{expectedInitialSync:{handle:message.handle,generation:message.generation,owner:message.expectedPrincipal}}:{}),
        ...((message.operation==='start_cache_monitor'||message.operation==='wait_cache_monitor'||message.operation==='stop_cache_monitor')?{expectedMonitor:{handle:message.handle,generation:message.generation,owner:message.expectedPrincipal,operation:message.operation,...('monitorId' in message?{id:message.monitorId}:{})}}:{}),
        ...(message.operation === "login_password" ? {passwordLogin:true as const} : {}),
        ...(message.operation === "restore_existing" ? {existingKeyRestore:{principal:message.profile.principal}} : message.operation === "restore_local" ? {existingKeyRestore:{principal:message.profile.principal,local:true as const}} : {}),
        ...(message.operation === 'check_first_session' ? {firstSession:{principal:message.profile.principal}} : message.operation==='check_first_session_data'?{firstSession:{principal:this.expectedPrincipal!,dataOnly:true as const}}:{}),
        ...(message.operation==="rotate_credentials"?{credentialCas:{handle:message.handle,generation:message.generation,scope:message.scope,signal,effectId:0,inFlight:false}}:{}),
        ...((message.operation==="prepare_credentials"||message.operation==="validate_credentials")?{expectedSnapshot:{handle:message.handle,generation:message.generation,...(message.operation==="validate_credentials"?{exact:JSON.stringify(message.snapshot)}:{})}}:{}),
        ...((message.operation === "open_chat" || message.operation === "reconnect_chat" || message.operation === "read_saved_chat" || message.operation === "read_saved_chat_page")
          ? { expectedChat: { handle: message.handle, generation: message.generation, chatId: message.chatId,
            kind: message.operation === "read_saved_chat" || message.operation === "read_saved_chat_page" ? "savedRead" as const : "chat" as const } } : {}) });
      signal.addEventListener("abort", cancel, { once: true });
      try {
        if(signal.aborted){cancel();return;}
        if(message.operation==='check_first_session'||message.operation==='check_first_session_data'){
          if(this.firstSessionDispatched){const pending=this.pending.get(id)!;this.pending.delete(id);clearTimeout(pending.timer);pending.dispose();reject(Error('unavailable'));return;}
          this.firstSessionDispatched=true;
          if(message.operation==='check_first_session_data')this.firstSessionDataOnlyDispatched=true;
        }
        if(ownedCache)this.pending.get(id)!.cache!.dispatched=true;
        const transfer=message.operation==="login_password"
          ? [message.password.buffer as ArrayBuffer,...(message.tfa?[message.tfa.buffer as ArrayBuffer]:[])]:[];
        if(this.recoveryBootstrap&&(message.operation==='restore_existing'||message.operation==='check_first_session')){
          // A second actually-dispatched restore cannot acquire the first
          // native port, even when the first restore failed or Page Root was
          // not yet bound. Retain its actual drain; ordinary RPC stays intact.
          if(this.recoveryRestoreRequested){const terminal=this.retireRecoveryTransport();void terminal?.catch(()=>{});}
          this.recoveryRestoreRequested=true;
        }
        this.worker.postMessage(message,transfer);
        if(message.operation==='run_initial_sync')this.lastInitialDispatch=id;
      } catch { this.close("unavailable"); }
      finally { clearPasswordRequest(message); clearPasswordRequest(body);clearExistingKeyRequest(message);clearExistingKeyRequest(body); }
    });
  }

  /** A dispatch fact from this actual Host postMessage, never actor readiness,
   * authentication, persistence or IO completion. No await precedes B release. */
  startInitialSync(handle:string,generation:number,owner:string,signal:AbortSignal):Readonly<{completion:Promise<CoreResponse>}>{
    const before=this.lastInitialDispatch;
    const completion=this.request({operation:'run_initial_sync',handle,generation,expectedPrincipal:owner},signal,MAX_INITIAL_SYNC_REQUEST_MS);
    if(this.lastInitialDispatch===before){void completion.catch(()=>{});throw Error('unavailable');}
    return Object.freeze({completion});
  }
  private stopInitialSync(id:number,reason:'cancelled'|'deadline'):void{
    const pending=this.pending.get(id),original=pending?.expectedInitialSync;
    if(this.closed||!pending||!original||original.stopReason)return;
    original.stopReason=reason;clearTimeout(pending.timer);pending.dispose();
    // Keep the pending original until its actual future returns. This rejects
    // the caller only; no successor/drain/Worker-close fact is manufactured.
    pending.reject(Error(reason));
    try{this.worker.postMessage({version:1,id,initialSyncStop:{handle:original.handle,generation:original.generation,owner:original.owner}});}catch{this.close('unavailable');}
  }

  /** Call on pagehide, logout, account switch, generation expiry or cross-tab invalidation. */
  close(reason: "session_expired" | "cancelled" | "deadline" | "unavailable" = "session_expired"): void {
    void this.closeAndDrain(reason).catch(() => undefined);
  }

  closeAndDrain(reason: "session_expired" | "cancelled" | "deadline" | "unavailable" = "session_expired"): Promise<void> {
    if (this.closing) return this.closing;
    if(this.firstCloseWait)return this.firstCloseWait.promise;
    const first=[...this.pending.entries()].find(([,pending])=>pending.firstSession);
    if(first){
      let resolve!:()=>void,reject!:(error:unknown)=>void;
      const promise=new Promise<void>((a,b)=>{resolve=a;reject=b;});
      this.firstCloseWait={promise,resolve,reject,reason};
      this.stopFirstSession(first[0],reason==='deadline'?'deadline':'cancelled');
      return promise;
    }
    let resolveDrain!: () => void, rejectDrain!: (error: unknown) => void;
    this.closing = new Promise<void>((resolve, reject) => { resolveDrain = resolve; rejectDrain = reject; });
    // Private Page endpoint is revoked before original root/issuer retirement.
    // Its actual port/Page terminals must settle BEFORE Worker termination.
    const recoveryDrain=this.retireRecoveryTransport();
    // Revoke routing synchronously. Native IO drains are awaited by the outer
    // adapter root, never recursively from this Host drain.
    if(this.nativeChatIssuer)revokeNativeRustChatIOFactory(this.nativeChatIssuer,this.worker);
    for (const root of this.nativeChatRoots) revokeRustChatIORoot(root);
    this.nativeRestoreEvent = null;
    this.closed = true;
    this.firstSessionAdmission=null;
    this.invalidateProfileCache();
    this.worker.removeEventListener("message", this.receive);
    this.worker.removeEventListener("messageerror", this.fail);
    this.worker.removeEventListener("error", this.fail);
    const draftPending=this.drafts.hasPending(),draftDrain=this.drafts.close();
    const requests=[...this.pending.values()];this.pending.clear();this.sends.clear();
    const settle=()=>{this.worker.terminate();for(const request of requests){clearTimeout(request.timer);request.dispose();request.reject(new Error(reason));}};
    const active=requests.filter(request=>request.credentialCas);
    const cache=requests.flatMap(request=>request.cache?[request.cache]:[]);
    for(const operation of cache)operation.controller.abort();
    const local = requests.flatMap(request => request.localCursor ? [request.localCursor] : []);
    for (const operation of local) operation.controller.abort();
    if(!active.length&&!local.length&&!cache.length&&!draftPending&&!recoveryDrain){settle();void draftDrain.then(resolveDrain,rejectDrain);return this.closing;}
    // Termination releases the Worker WebLock. First invalidate local leases
    // and drain every Page IO terminal; never let a late CAS outlive the lock.
    const drain=[draftDrain,...(recoveryDrain?[recoveryDrain]:[]),...cache.flatMap(operation=>[operation.terminal,Promise.resolve().then(()=>operation.handler.close())]),...local.map(operation=>operation.terminal),...active.map(request=>Promise.resolve().then(()=>request.credentialCas!.lease?.close())),...(active.length?[Promise.resolve().then(()=>this.credentialEffects?.close())]:[])];
    void Promise.allSettled(drain).then(results => {
      settle();
      const failed = results.find(result => result.status === 'rejected');
      if (failed?.status === 'rejected') rejectDrain(failed.reason); else resolveDrain();
    });
    return this.closing;
  }

  private localEffect(message: unknown): void {
    if (!validLocalCursorEffect(message)) { this.close("unavailable"); return; }
    const pending = this.pending.get(message.id), operation = pending?.localCursor, expected = pending?.expectedCheckpoint??pending?.expectedLocal;
    const plan = message.localReadEffect;
    if (!operation || !expected || operation.inFlight || message.effectId !== operation.effectId + 1
      || operation.operationId !== undefined && operation.operationId !== plan.operationId
      || plan.owner !== expected.principal || plan.chatId !== expected.chatId) {
      this.close("unavailable"); return;
    }
    try { operation.planState=advanceLocalReadPlan(operation.planState,plan,operation.selector); }
    catch { this.close("unavailable"); return; }
    operation.operationId = plan.operationId; operation.effectId = message.effectId; operation.inFlight = true;
    // Install the terminal before executing user/platform callbacks: close() may
    // run synchronously inside them and must still drain this exact operation.
    operation.terminal = Promise.resolve().then(async () => {
      let localReadReply: unknown;
      try {
        if (this.closed || this.pending.get(message.id) !== pending || operation.controller.signal.aborted) return;
        operation.handler.current();
        const packet = await operation.handler.execute(plan, operation.controller.signal);
        operation.handler.current();
        if (typeof packet !== "string" || new TextEncoder().encode(packet).byteLength > plan.maxPacketBytes) throw Error("unavailable");
        localReadReply = { ok: true, operationId: plan.operationId, packet };
      } catch (error) {
        const reason = error instanceof Error && ["cancelled","unavailable","invalidated_snapshot","storage_failed"].includes(error.message) ? error.message : "invalidated_snapshot";
        localReadReply = { ok: false, operationId: plan.operationId, error: reason };
      } finally { operation.inFlight = false; }
      if (this.closed || this.pending.get(message.id) !== pending || operation.controller.signal.aborted) return;
      const reply = {version:1,id:message.id,effectId:message.effectId,localReadReply};
      if (!validLocalCursorReply(reply)) { this.close("unavailable"); return; }
      this.worker.postMessage(reply);
    }).catch(() => { if (this.pending.get(message.id) === pending) this.close("unavailable"); });
  }

  /** Retain this pending slot until real Page and original native terminals. */
  private stopOwnedCache(id:number,reason:'cancelled'|'deadline'):void {
    const pending=this.pending.get(id),operation=pending?.cache;
    if(this.closed||!pending||!operation?.ownedIdentity||operation.stopReason)return;
    operation.stopReason=reason;clearTimeout(pending.timer);pending.dispose();operation.controller.abort();
    // Capture already-started callbacks before close; callbacks cannot post new
    // private work after abort, but must return their actual IO terminal reply.
    operation.stopDrain=operation.terminal.then(()=>operation.handler.close());
    void operation.stopDrain.then(()=>this.postStoppedPageDrain(id,pending),()=>this.close('unavailable'));
    if(operation.dispatched!==false){try{this.worker.postMessage({version:1,id,cacheStop:{...operation.ownedIdentity}});}catch{this.close('unavailable');return;}}
    this.settleStoppedCache(id,pending);
  }
  private postStoppedPageDrain(id:number,pending:Pending):void {
    const operation=pending.cache;if(this.closed||this.pending.get(id)!==pending||!operation?.stopReason||!operation.publicationId||operation.drained||operation.stoppedDrainSent===operation.publicationId)return;
    operation.stoppedDrainSent=operation.publicationId;
    try{this.worker.postMessage({version:1,id,cacheDrained:{publicationId:operation.publicationId}});}catch{this.close('unavailable');}
  }
  private settleStoppedCache(id:number,pending:Pending):void {
    const operation=pending.cache;if(!operation?.stopReason||!operation.workerTerminal&&operation.dispatched!==false)return;
    void operation.stopDrain!.then(()=>{
      if(this.closed||this.pending.get(id)!==pending)return;
      clearTimeout(pending.timer);pending.dispose();this.pending.delete(id);pending.reject(Error(operation.stopReason));
    },()=>this.close('unavailable'));
  }
  private cacheTerminal(message:unknown,event:MessageEvent<unknown>):void {
    if(!validBrowserOwnedCacheTerminal(message)){this.close('unavailable');return;}
    const pending=this.pending.get(message.id),operation=pending?.cache;
    try{if(readNativeChatIOMessage(event,this.worker)!==message||!pending||!operation?.ownedIdentity||operation.workerTerminal
      ||!sameBrowserOwnedCacheIdentity(operation.ownedIdentity,message.cacheTerminal))throw Error('unavailable');}
    catch{this.close('unavailable');return;}
    if(message.state!=='drained'){this.close('unavailable');return;}
    operation!.workerTerminal=true;
    if(operation!.stopReason){this.settleStoppedCache(message.id,pending!);return;}
    const final=operation!.finalEvent;if(final){operation!.finalEvent=undefined;this.receive(final);}
  }

  private cacheEffect(message:unknown,event?:MessageEvent<unknown>):void {
    if(!validBrowserCacheEffect(message)){this.close('unavailable');return;}
    const pending=this.pending.get(message.id),operation=pending?.cache;
    if(!operation||operation.operation==='read_cached_chat_items'||!operation.scope){this.close('unavailable');return;}
    if(operation.inFlight||operation.draining||message.effectId!==operation.effectId+1){this.close('unavailable');return;}
    if(operation.stopReason){
      try{if(!event||readNativeChatIOMessage(event,this.worker)!==message)throw Error('unavailable');}catch{this.close('unavailable');return;}
      // No physical IO starts after stop. Returning a negative is not a drain
      // receipt; the original Rust future still has to finish independently.
      operation.effectId=message.effectId;this.worker.postMessage({version:1,id:message.id,effectId:message.effectId,cacheReply:{ok:false,error:'cancelled'},...(message.cacheDraftBudget?{cacheDraftBudget:message.cacheDraftBudget}:{})});return;
    }
    const marked='cacheStage' in message;
    if(marked||message.cacheDraftBudget||operation.stage){
      try{if(!event||readNativeChatIOMessage(event,this.worker)!==message)throw Error('invalidated_snapshot');operation.originalCurrent();}
      catch{this.close('unavailable');return;}
    }
    if(operation.progressPending){
      if(marked||operation.queuedContinuation){this.close('unavailable');return;}
      operation.queuedContinuation=true;
      operation.terminal=operation.progress!.then(()=>{
        operation.queuedContinuation=false;
        if(!this.closed&&this.pending.get(message.id)===pending&&(!operation.controller.signal.aborted||operation.stopReason))this.cacheEffect(message,event);
      });return;
    }
    if(marked&&message.cacheStage==='owned_local'){
      if(!operation.localRead||operation.operation!=='read_cold_retained_saved_chat'||operation.stage&&operation.stage!=='owned_local'||message.cacheDraftBudget){this.close('unavailable');return;}
      operation.stage='owned_local';
    }else if(marked){
      if(operation.profileCache){this.close('unavailable');return;}
      if(operation.localRead&&operation.stage!=='owned_selected'&&!ownedLocalReadFallbackReady(operation.localRead)){this.close('unavailable');return;}
      if(message.cacheStage!=='owned_selected'||operation.stage==='metadata'||operation.selectedProgressReceived
        ||!['read_cold_retained_saved_chat','read_cache_monitor_update'].includes(operation.operation)
        ||operation.operation==='read_cache_monitor_update'&&!operation.progressOwner){this.close('unavailable');return;}
      operation.stage='owned_selected';
    }else if(operation.profileCache){this.close('unavailable');return;
    }else if(operation.stage==='owned_selected'){
      if(!operation.selectedProgressReceived||!operation.drained||!operation.progressOwner){this.close('unavailable');return;}
      // Reopen only in response to this actual original native metadata effect.
      // The selected native continuation stays owned by the SAME pending RPC.
      try{
        const current=()=>{if(this.closed||this.pending.get(message.id)!==pending||operation.controller.signal.aborted)throw Error('invalidated_snapshot');operation.originalCurrent();};
        current();operation.handler=operation.progressOwner.createContinuationEffects(current);current();operation.handler.current();
      }catch{this.close('unavailable');return;}
      operation.stage='metadata';operation.state={effects:0,rows:new Map()};
      operation.drained=false;operation.draining=false;operation.publicationId=null;operation.preparedNative=false;
    }
    if(operation.inFlight||operation.draining||operation.drained||message.effectId!==operation.effectId+1){this.close('unavailable');return;}
    try{operation.handler.current();if(operation.stage==='owned_local'){beginOwnedLocalRead(operation.localRead!,message.cacheEffect,{owner:operation.owner,chatId:operation.ids[0]});}else advanceBrowserCachePlan(operation.state,message.cacheEffect,{operation:operation.stage==='owned_selected'?'read_owned_selected_message_cache':operation.operation,owner:operation.owner,ids:operation.ids,scope:operation.scope});}
    catch{this.close('unavailable');return;}
    operation.effectId=message.effectId;operation.inFlight=true;
    operation.terminal=Promise.resolve().then(async()=>{
      let cacheReply:unknown;
      try{if(this.closed||this.pending.get(message.id)!==pending)return;
        if(operation.controller.signal.aborted)throw Error('cancelled');operation.handler.current();const packet=await operation.handler.execute(message.cacheEffect,operation.controller.signal,message.cacheDraftBudget?true:undefined,operation.stage==='owned_local'?true:undefined);operation.handler.current();
        if(operation.stage==='owned_local')completeOwnedLocalRead(operation.localRead!,packet);
        if(typeof packet!=='string'||new TextEncoder().encode(packet).byteLength>(message.cacheDraftBudget?4*1024*1024:256*1024))throw Error('unavailable');cacheReply={ok:true,packet};
      }catch(error){cacheReply={ok:false,error:error instanceof Error&&error.message==='cancelled'?'cancelled':'unavailable'};}
      finally{operation.inFlight=false;}
      if(this.closed||this.pending.get(message.id)!==pending)return;
      if(operation.stopReason)cacheReply={ok:false,error:'cancelled'};
      const reply={version:1,id:message.id,effectId:message.effectId,cacheReply,...(message.cacheDraftBudget?{cacheDraftBudget:message.cacheDraftBudget}:{})};if(!validBrowserCacheReply(reply)){this.close('unavailable');return;}
      this.worker.postMessage(reply);
    }).catch(()=>{if(this.pending.get(message.id)===pending)this.close('unavailable');});
  }

  private cachePrepared(message:unknown,event?:MessageEvent<unknown>):void {
    if(!validBrowserCachePrepared(message)){this.close('unavailable');return;}
    const pending=this.pending.get(message.id),operation=pending?.cache;
    if(operation?.stopReason){
      try{if(!event||readNativeChatIOMessage(event,this.worker)!==message)throw Error('unavailable');}catch{this.close('unavailable');return;}
      if(operation.publicationId!==null&&operation.publicationId!==message.cachePrepared.publicationId){this.close('unavailable');return;}
      operation.publicationId=message.cachePrepared.publicationId;
      void operation.stopDrain!.then(()=>this.postStoppedPageDrain(message.id,pending!),()=>this.close('unavailable'));return;
    }
    if(!operation||!['read_cache_monitor_update','read_cold_retained_saved_chat','read_monitored_retained_saved_chat'].includes(operation.operation)
      ||operation.inFlight||operation.draining||operation.drained||operation.publicationId!==null
      ||!(operation.stage==='owned_local'?!!operation.localRead&&ownedLocalReadReady(operation.localRead):browserCachePlansComplete(operation.state,operation.stage==='owned_selected'?'read_owned_selected_message_cache':operation.operation,operation.ids))){this.close('unavailable');return;}
    let native=false;try{native=!!event&&readNativeChatIOMessage(event,this.worker)===message;}catch{/* Ordinary legacy transport remains unchanged. */}
    if(operation.stage&&!native){this.close('unavailable');return;}
    operation.preparedNative=native;
    operation.publicationId=message.cachePrepared.publicationId;operation.draining=true;
    // Install terminal before the actual close: invalidation must drain exactly
    // this operation before any Worker termination releases its auth lock.
    operation.terminal=Promise.resolve().then(async()=>{
      if(this.closed||this.pending.get(message.id)!==pending||operation.controller.signal.aborted)return;
      await operation.handler.close();operation.handler.current();
      if(this.closed||this.pending.get(message.id)!==pending||operation.controller.signal.aborted)return;
      operation.drained=true;operation.draining=false;
      const reply={version:1,id:message.id,cacheDrained:{publicationId:operation.publicationId}};
      if(!validBrowserCacheDrained(reply)){this.close('unavailable');return;}
      this.worker.postMessage(reply);
    }).catch(()=>{if(this.pending.get(message.id)===pending)this.close('unavailable');});
  }

  private cacheRecoveryProgress(message:unknown,event:MessageEvent<unknown>):void{
    if(!validBrowserCacheRecoveryProgress(message)){this.close('unavailable');return;}
    const operation=this.pending.get(message.id)?.cache;
    try{
      if(readNativeChatIOMessage(event,this.worker)!==message||!operation||!operation.selectedProgressReceived
        ||operation.stage!=='metadata'||!operation.drained||operation.inFlight||operation.draining)throw Error('invalidated_snapshot');
      operation.originalCurrent();operation.handler.current();
      // All progress values are observational DATA from the original Worker.
      // Main metadata and selected reply remain partial/pending; no value conveys transcript
      // durability, a JS receipt, readiness or whole-hint authority.
      // Deliberately nonfinal. No request resolve, source rebase, completion,
      // receipt construction, retry or ACK follows this observational DATA.
    }catch{this.close('unavailable');}
  }

  private cacheSelected(message:unknown,event:MessageEvent<unknown>):void{
    if(!validBrowserCacheSelected(message)){this.close('unavailable');return;}
    const pending=this.pending.get(message.id),operation=pending?.cache;
    if(operation?.stopReason){try{if(readNativeChatIOMessage(event,this.worker)!==message)throw Error('unavailable');}catch{this.close('unavailable');}return;}
    try{
      if(readNativeChatIOMessage(event,this.worker)!==message||!operation||operation.operation!=='read_cache_monitor_update'
        ||operation.stage!=='owned_selected'||!operation.progressOwner||!operation.preparedNative||!operation.drained
        ||operation.draining||operation.inFlight||operation.selectedProgressReceived||operation.publicationId!==message.cacheSelected.publicationId
        ||message.cacheSelected.selected.chat.id!==operation.ids[0]
        ||!browserCachePlansComplete(operation.state,'read_owned_selected_message_cache',operation.ids))throw Error('invalidated_snapshot');
      operation.originalCurrent();operation.handler.current();
    }catch{this.close('unavailable');return;}
    const actual=operation!,owner=actual.progressOwner!;
    // Payload copies are DATA only. The original native event/pending resource
    // above remains the sole transport correlation; no DTO becomes authority.
    const data=structuredClone(message.cacheSelected);
    actual.selectedProgressReceived=true;actual.progressPending=true;
    actual.progress=Promise.resolve().then(async()=>{
      if(this.closed||this.pending.get(message.id)!==pending||actual.controller.signal.aborted)return;
      actual.originalCurrent();actual.handler.current();
      await owner.onSelected(data.selected,data.sourceEvidence);
      actual.originalCurrent();actual.handler.current();
    }).catch(error=>{
      actual.progressFailure=error instanceof Error?error:Error('publication_failed');
      if(!this.closed&&this.pending.get(message.id)===pending&&!actual.stopReason&&actual.monitorId){
        // Negative control for this EXACT original monitor wakes a bounded
        // native holder. It is neither a hint ACK nor a replacement read owner.
        // Do not await a nested RPC in the progress terminal: Host teardown
        // rejects pending replies only after this terminal has drained.
        actual.progressStop=this.request({operation:'stop_cache_monitor',handle:actual.handle,
          generation:actual.generation,expectedPrincipal:actual.owner,monitorId:actual.monitorId},new AbortController().signal);
        void actual.progressStop.catch(()=>undefined);
      }
    }).finally(()=>{actual.progressPending=false;});
    actual.terminal=actual.progress;
  }

  private async effect(message:unknown):Promise<void>{
    if(!validCredentialEffectMessage(message)){this.close("unavailable");return;}
    const pending=this.pending.get(message.id),cas=pending?.credentialCas,handler=this.credentialEffects;
    if(!cas||!handler||cas.inFlight||message.effectId!==cas.effectId+1||cas.operationId!==undefined&&cas.operationId!==message.hostEffect.operationId){this.close("unavailable");return;}
    try{
      handler.current();cas.operationId=message.hostEffect.operationId;cas.effectId=message.effectId;cas.inFlight=true;
      cas.lease??=openAuthRefreshEffectLease(this,cas.operationId,cas.signal,()=>{if(this.closed||this.pending.get(message.id)!==pending)throw Error("session_expired");handler.current();});
      let reply:unknown;
      try{const result=await handler.execute(message.hostEffect,cas.lease.lease,cas.signal);if(!validCredentialIOResult(result)||result.operationId!==cas.operationId)throw Error("invalid_request");reply={ok:true,result};}
      catch(error){reply={ok:false,error:error instanceof Error&&credentialIOError(error.message)?error.message:"invalidated_snapshot"};}
      cas.inFlight=false;
      if(!this.closed&&this.pending.get(message.id)===pending)this.worker.postMessage({version:1,id:message.id,effectId:message.effectId,hostReply:reply});
    }catch{this.close("unavailable");}
  }

  private readonly fail = (): void => {this.drafts.fail();this.close("unavailable");};
  private readonly receive = (event: MessageEvent<unknown>): void => {
    if(this.drafts.ownsEvent(event))return;
    if (this.closed) return;
    const frame=this.deferredNativeFinals.get(event)?.snapshot??event.data;
    if(typeof frame==='object'&&frame!==null&&'firstSessionTerminal' in frame){this.firstSessionTerminal(frame,event);return;}
    if(typeof frame==='object'&&frame!==null&&'profileCacheInvalidated' in frame){this.profileCacheInvalidated(frame,event);return;}
    if(typeof frame==="object"&&frame!==null&&"localReadEffect" in frame){this.localEffect(frame);return;}
    if(typeof frame==="object"&&frame!==null&&"hostEffect" in frame){void this.effect(frame);return;}
    if(typeof frame==='object'&&frame!==null&&'cacheEffect' in frame){this.cacheEffect(frame,event);return;}
    if(typeof frame==='object'&&frame!==null&&'cachePrepared' in frame){this.cachePrepared(frame,event);return;}
    if(typeof frame==='object'&&frame!==null&&'cacheTerminal' in frame){this.cacheTerminal(frame,event);return;}
    if(typeof frame==='object'&&frame!==null&&'cacheSelected' in frame){this.cacheSelected(frame,event);return;}
    if(typeof frame==='object'&&frame!==null&&'cacheRecoveryProgress' in frame){this.cacheRecoveryProgress(frame,event);return;}
    if (!validResponse(frame)) { this.close("unavailable"); return; }
    const pending = this.pending.get(frame.id);
    if (!pending) { this.close("unavailable"); return; }
    let response:CoreResponse=frame;
    if(pending.cache?.ownedIdentity){
      try{let captured=this.deferredNativeFinals.get(event);
        if(!captured){if(readNativeChatIOMessage(event,this.worker)!==frame)throw Error('unavailable');
          captured={raw:frame,snapshot:structuredClone(frame)};this.deferredNativeFinals.set(event,captured);}
        response=captured.snapshot;
      }catch{this.close('unavailable');return;}
    }
    const data=response;
    if(pending.firstSession){
      try{
        if(readNativeChatIOMessage(event,this.worker)!==frame||pending.firstSession.response)throw Error('unavailable');
        if(data.ok&&!data.firstSession)throw Error('unavailable');
        pending.firstSession.response=data;pending.firstSession.event=event;pending.firstSession.serialized=JSON.stringify(data);
        this.finishFirstSession(data.id,pending);
      }catch{this.stopFirstSession(data.id,'unavailable');}
      return;
    }else if(data.ok&&'firstSession' in data){this.close('unavailable');return;}
    if(pending.existingKeyRestore && data.ok){
      const status=data.status;
      if(!status||status.principal!==pending.existingKeyRestore.principal||status.persistence!=="memory_only"||typeof status.localReadOnly!=="boolean"
        ||pending.existingKeyRestore.local&&status.localReadOnly!==true){
        this.close("unavailable");return;
      }
      this.existingKeyMode=true;
      // Recording is optional and never changes legacy/fake-transport behavior.
      // Only the original trusted event from the factory-owned native Worker
      // can later enroll a routing root; copied responses remain insufficient.
      if(!pending.existingKeyRestore.local && this.nativeChatIssuer && event.isTrusted === true && event.target === this.worker){
        try{recordNativeRustChatRestoreAdmission(this.nativeChatIssuer,this.worker,event,data.id);this.nativeRestoreEvent=event;this.profileCacheRestoreStatus=Object.freeze({...status});}
        catch{/* Untrusted/fabricated transport can never enroll optional IO. */}
      }
    }
    if(this.existingKeyMode&&data.ok&&data.status
      &&(typeof data.status.localReadOnly!=="boolean"||data.status.principal!==this.expectedPrincipal)){
      this.close("unavailable");return;
    }
    if (pending.passwordLogin && data.ok && (!data.status || data.status.persistence!=="memory_only")) {
      this.close("unavailable"); return;
    }
    if (!pending.passwordLogin && failedResponse(data) && ["authentication_failed","two_factor_required"].includes(data.error)) {
      this.close("unavailable"); return;
    }
    if(pending.expectedInitialSync&&data.ok){
      const expected=pending.expectedInitialSync;
      if(!data.initialSync||!data.status||data.status.handle!==expected.handle||data.status.generation!==expected.generation||data.status.principal!==expected.owner||data.status.localReadOnly===true){this.close('unavailable');return;}
    }
    if(!pending.expectedInitialSync&&data.ok&&'initialSync' in data){this.close('unavailable');return;}
    if(pending.expectedMonitor&&data.ok){
      const expected=pending.expectedMonitor,reply=data;
      if((expected.operation!=='stop_cache_monitor'&&(!reply.status||reply.status.handle!==expected.handle||reply.status.generation!==expected.generation||reply.status.principal!==expected.owner||reply.status.localReadOnly===true))
        ||!reply.cacheMonitor||expected.id!==undefined&&reply.cacheMonitor.id!==expected.id
        ||!(expected.operation==='start_cache_monitor'?reply.cacheMonitor.state==='started':expected.operation==='stop_cache_monitor'?reply.cacheMonitor.state==='closed':['ready','idle'].includes(reply.cacheMonitor.state))){this.close('unavailable');return;}
    }
    if(!pending.expectedMonitor&&data.ok&&'cacheMonitor' in data){this.close('unavailable');return;}
    if(pending.cache){
      const operation=pending.cache,reply=data;
      if(operation.ownedIdentity&&operation.stopReason){this.settleStoppedCache(reply.id,pending);return;}
      if(operation.progressPending){
        if(operation.queuedContinuation){this.close('unavailable');return;}
        operation.queuedContinuation=true;
        operation.terminal=operation.progress!.then(()=>{operation.queuedContinuation=false;if(!this.closed&&this.pending.get(reply.id)===pending)this.receive(event);});return;
      }
      if(operation.stage){
        try{if(readNativeChatIOMessage(event,this.worker)!==(this.deferredNativeFinals.get(event)?.raw??reply))throw Error('invalidated_snapshot');operation.originalCurrent();}
        catch{this.close('unavailable');return;}
      }
      if(reply.ok&&('cacheSourceEvidence' in reply)){
        if(operation.operation!=='read_cold_retained_saved_chat'||operation.stage!=='owned_selected'||!operation.preparedNative
          ||!validBrowserCacheSourceEvidence(reply.cacheSourceEvidence)){this.close('unavailable');return;}
      }else if(reply.ok&&operation.operation==='read_cold_retained_saved_chat'&&operation.stage==='owned_selected'){
        this.close('unavailable');return;
      }
      if(reply.ok&&operation.selectedProgressReceived&&operation.stage!=='metadata'){this.close('unavailable');return;}
      if(operation.inFlight||reply.ok&&(!(operation.stage==='owned_local'?!!operation.localRead&&ownedLocalReadReady(operation.localRead):browserCachePlansComplete(operation.state,operation.stage==='owned_selected'?'read_owned_selected_message_cache':operation.operation,operation.ids))||!reply.status
        ||reply.status.handle!==operation.handle||reply.status.generation!==operation.generation||reply.status.principal!==operation.owner
        ||(operation.operation==='read_cache_monitor_update'?(!reply.cacheUpdate||reply.cacheMonitorId!==operation.monitorId||reply.cacheUpdate.selected!==null&&reply.cacheUpdate.selected.chat.id!==operation.ids[0]||reply.status.localReadOnly===true):((operation.operation==='read_retained_saved_chat'||operation.operation==='read_cold_retained_saved_chat'||operation.operation==='read_monitored_retained_saved_chat')?(!reply.retainedRead||!(operation.stage==='owned_local'?!!operation.localRead&&ownedLocalReadReady(operation.localRead)&&reply.retainedRead.cacheReadKind==='local':retainedKindMatches(operation.operation,reply.retainedRead))||reply.retainedRead.chat.id!==operation.ids[0]||reply.status.localReadOnly===true)
          :(!reply.cachedMetadata||reply.cachedMetadata.metadataRestored!==(operation.operation==='restore_cached_metadata')||reply.cachedMetadata.items.length!==operation.ids.length||reply.cachedMetadata.items.some(row=>!operation.ids.includes(row.id))))))){this.close('unavailable');return;}
      if(failedResponse(reply)&&reply.profileCacheAbsent===true&&(!operation.profileCache||operation.operation!=='read_cold_retained_saved_chat'||operation.stage!=='owned_local'||!operation.localRead||!ownedLocalReadFallbackReady(operation.localRead))){this.close('unavailable');return;}
      if(operation.ownedIdentity&&!operation.workerTerminal){if(operation.finalEvent){this.close('unavailable');return;}operation.finalEvent=event;return;}
      const sealed=['read_cache_monitor_update','read_cold_retained_saved_chat','read_monitored_retained_saved_chat'].includes(operation.operation);
      if(sealed){
        // No awaited cleanup after Rust consumed its original publication.
        if(reply.ok&&(!operation.drained||operation.draining)){this.close('unavailable');return;}
        if(operation.drained){try{operation.handler.current();}catch{this.close();return;}
          clearTimeout(pending.timer);pending.dispose();this.pending.delete(reply.id);
          // Keep native source DATA stable across the facade's awaited original
          // key verification; this copy is never a root or authority token.
          const result=(operation.stage==='owned_selected'||operation.stage==='owned_local')&&operation.operation==='read_cold_retained_saved_chat'&&reply.ok?structuredClone(reply):reply;
          if(operation.progressFailure)pending.reject(operation.progressFailure);else pending.resolve(result);return;}
      }
      void operation.handler.close().then(()=>{
        if(this.closed||this.pending.get(reply.id)!==pending)return;try{operation.handler.current();}catch{this.close();return;}
        if(failedResponse(reply)&&reply.profileCacheAbsent===true){
          try{if(!operation.workerTerminal||!operation.profileCache||!operation.scope||readNativeChatIOMessage(event,this.worker)!==(this.deferredNativeFinals.get(event)?.raw??reply))throw Error('unavailable');operation.originalCurrent();}
          catch{this.close('unavailable');return;}
          this.profileCacheAbsences.set(reply,{handle:operation.handle,generation:operation.generation,owner:operation.owner,chatId:operation.ids[0],scope:{...operation.scope}});
        }
        clearTimeout(pending.timer);pending.dispose();this.pending.delete(reply.id);if(operation.progressFailure)pending.reject(operation.progressFailure);else pending.resolve(reply);
      },()=>this.close('unavailable'));return;
    }
    if(data.ok&&('cachedMetadata' in data||'retainedRead' in data||'cacheUpdate' in data||'cacheSourceEvidence' in data)){this.close('unavailable');return;}
    if(pending.credentialCas){
      const cas=pending.credentialCas,reply=data;
      if(cas.inFlight||reply.ok&&(!reply.credentialCas||!reply.status||reply.status.handle!==cas.handle||reply.status.generation!==cas.generation
        ||reply.credentialCas.operationId!==cas.operationId||reply.credentialCas.scope.lifecycleGeneration!==cas.scope.lifecycleGeneration||reply.credentialCas.scope.workspaceEpoch!==cas.scope.workspaceEpoch)){this.close("unavailable");return;}
      void (cas.lease?.close()??Promise.resolve()).then(()=>{
        if(this.closed||this.pending.get(reply.id)!==pending)return;
        try{this.credentialEffects!.current();}catch{this.close();return;}
        clearTimeout(pending.timer);pending.dispose();this.pending.delete(reply.id);pending.resolve(reply);
      },()=>this.close("unavailable"));return;
    }
    if(data.ok && "credentialCas" in data){this.close("unavailable");return;}
    if(pending.localCursor && (pending.localCursor.inFlight || data.ok && pending.localCursor.planState.effects<(pending.expectedCheckpoint?1:pending.localCursor.selector.direction==="around"?2:1))){this.close("unavailable");return;}
    if(pending.expectedCheckpoint){
      const expected=pending.expectedCheckpoint,reply=data;
      if(reply.ok&&(!reply.checkpointRead||!reply.status||reply.status.handle!==expected.handle||reply.status.generation!==expected.generation
        ||reply.status.principal!==expected.principal||reply.status.localReadOnly!==true||reply.checkpointRead.coverage!=="retained_selected"
        ||reply.checkpointRead.checkpoint!==null&&(reply.checkpointRead.checkpoint.chatId!==expected.chatId||reply.checkpointRead.checkpoint.id!==expected.checkpointId))){this.close("unavailable");return;}
    }else if(data.ok&&"checkpointRead" in data){this.close("unavailable");return;}
    if(data.ok && pending.expectedLocal?.online){
      const expected=pending.expectedLocal,reply=data;
      if(!reply.onlineCachedRead||!reply.status||reply.status.handle!==expected.handle||reply.status.generation!==expected.generation
        ||reply.status.localReadOnly===true||reply.status.principal!==expected.principal||reply.onlineCachedRead.chat.id!==expected.chatId
        ||!("chatMetadata" in reply.onlineCachedRead)){this.close("unavailable");return;}
    } else if(data.ok && "onlineCachedRead" in data){this.close("unavailable");return;
    } else if(data.ok && pending.expectedLocal){
      const expected=pending.expectedLocal,reply=data;
      if(!reply.localRead||!reply.status||reply.status.handle!==expected.handle||reply.status.generation!==expected.generation
        ||reply.status.localReadOnly!==true||reply.status.principal!==expected.principal||reply.localRead.chat.id!==expected.chatId
        ||("chatMetadata" in reply.localRead)!==expected.saved){this.close("unavailable");return;}
    } else if(data.ok && "localRead" in data){this.close("unavailable");return;
    } else if(data.ok && pending.expectedSnapshot){
      const expected=pending.expectedSnapshot;
      if(!data.snapshot||!data.status||data.status.handle!==expected.handle||data.status.generation!==expected.generation
        ||expected.exact!==undefined&&JSON.stringify(data.snapshot)!==expected.exact){this.close("unavailable");return;}
    } else if (data.ok && pending.expectedSend) {
      const expected = pending.expectedSend, reply = data.send;
      if (!reply || reply.kind !== expected.kind || expected.operationId && reply.operationId !== expected.operationId
        || expected.kind === "started" && (!data.status || data.status.handle !== expected.handle || data.status.generation !== expected.generation || this.sends.has(reply.operationId))
        || reply.kind === "event" && reply.event !== null && !validSendEvent(reply.event, expected.chatId)) { this.close("unavailable"); return; }
      if(reply.kind==="event"&&reply.terminal){
        // dispatchEvent can fabricate an otherwise valid message on the same
        // Worker object. Only a native event from this original Worker may mint
        // the one-use terminal correlation used for retained-session lifetime.
        if(event.isTrusted!==true||event.target!==this.worker){this.close("unavailable");return;}
        const terminal=reply.terminal;
        if(reply.event?.type==="completed"&&(terminal.outcome!=="completed"||!terminal.canContinueParent)
          ||reply.event?.type==="error"&&(reply.event.error==="cancelled"&&!["cancelled","uncertain"].includes(terminal.outcome))){this.close("unavailable");return;}
        this.terminals.set(data,{handle:expected.handle,generation:expected.generation,operationId:reply.operationId,value:Object.freeze({...terminal})});
      }
      if (reply.kind === "started") this.sends.set(reply.operationId, { handle: expected.handle, generation: expected.generation, chatId: expected.chatId });
      if (reply.kind === "closed" || reply.kind === "event" && (reply.event === null || reply.event.type !== "update")) this.sends.delete(reply.operationId);
    } else {
    const resultId = data.ok && (pending.expectedChat?.kind === "savedRead" ? data.savedRead?.chat.id : data.chat?.id);
    if (data.ok && (pending.expectedChat ? !(resultId && data.status
      && resultId === pending.expectedChat.chatId && data.status.handle === pending.expectedChat.handle
      && data.status.generation === pending.expectedChat.generation) : "chat" in data || "savedRead" in data || "send" in data || "snapshot" in data)) {
      this.close("unavailable"); return;
    }
    }
    clearTimeout(pending.timer);
    pending.dispose();
    this.pending.delete(data.id);
    pending.resolve(data);
  };
}
