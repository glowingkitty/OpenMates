// Explicit dispatcher state (formerly closure variables) and its small lifecycle helpers.
import { withAuthRefreshLock } from "./browserAdapters";
import type { BrowserCachePlanState,BrowserOwnedCacheIdentity } from './browserCacheProtocol';
import { validBrowserCacheDrained,validBrowserCacheReply } from './browserCacheProtocol';
import { OwnedInitialSyncOperation } from './initialSyncOperation';
import { OwnedCacheMonitorAcquisition } from './phasedCacheMonitorOperation';
import type { FirstSessionTerminal,LocalReadPlanState } from "./protocol";
import { clearPasswordRequest,validFirstSessionStop,validRequest } from "./protocol";
import { OwnedSendOperation } from "./sendOperation";
import { dispatch } from "./workerDispatch";
import type { BrowserCoreBinding,CacheMonitorSlot,OwnedCacheRequest,OwnedCacheSlot,ProfileCacheSlot,RustCacheMonitor,RustClient,RustFirstSessionControl,RustInitialSyncStoreBootstrap,RustRecoveryBootstrap,RustRecoveryPort,RustStatus,WorkerConfiguration,WorkerEndpoint } from "./workerRuntimeTypes";
import { projectStatus } from "./workerRuntimeTypes";

/** Explicit state of one installed Rust core Worker dispatcher (formerly closure variables). */
export interface WorkerRuntimeState {
  endpoint: WorkerEndpoint;
  binding: BrowserCoreBinding;
  configuration: Readonly<WorkerConfiguration>;
  locks: LockManager;
  recoveryBootstrap: RustRecoveryBootstrap | undefined;
  startupStoreBootstrap: RustInitialSyncStoreBootstrap | undefined;
  client: RustClient | null;
  firstSessionDataOnlyUsed: boolean;
  firstSessionUsed: boolean;
  firstSessionControl: RustFirstSessionControl|null;
  firstSessionTask: {id:number;stopped:boolean}|null;
  originalRecoveryBootstrap: RustRecoveryBootstrap | undefined;
  originalStartupStore: RustInitialSyncStoreBootstrap | undefined;
  originalRecoveryPort: RustRecoveryPort|null;
  foregroundRecoveryClient: RustClient|null;
  recoveryDrains: Set<Promise<void>>;
  failedRecoveryPorts: Set<RustRecoveryPort>;
  reading: RustClient | null;
  sending: OwnedSendOperation | null;
  casReply: {id:number;effectId:number;operationId:string;resolve:(value:string)=>void;reject:(error:string)=>void}|null;
  localRead: { planState: LocalReadPlanState; id: number; live: boolean; effectId: number; operationId?: string;
    reply: { effectId: number; operationId: string; maxBytes: number; resolve(packet: string): void; reject(error: string): void } | null } | null;
  lastLocalReadId: number;
  lastCacheReadId: number;
  cacheRead: {id:number;live:boolean;effectId:number;state:BrowserCachePlanState;reply:null|{effectId:number;resolve:(packet:string)=>void;reject:(error:string)=>void};drain:null|{publicationId:string;resolve:()=>void;reject:(error:string)=>void}}|null;
  ownedCacheReads: Map<number, OwnedCacheSlot>;
  cacheMonitor: CacheMonitorSlot|null;
  profileCache: ProfileCacheSlot|null;
  retiredProfileCaches: Set<ProfileCacheSlot>;
  initialSync: {id:number;handle:string;generation:number;owner:string;original:RustClient;operation:OwnedInitialSyncOperation;acquisition:OwnedCacheMonitorAcquisition<RustClient>;monitor:RustCacheMonitor|null;ready:Promise<RustCacheMonitor>;task:Promise<void>|null;release:()=>void}|null;
  passwordAdmission: unknown;
  busy: boolean;
  disposed: boolean;
  lifetime: AbortController;
  retainedClients: Map<RustClient, { holders: number; invalidated: boolean; }>;
  freedClients: WeakSet<RustClient>;
  clientPhaseTail: Promise<void>;
  /** Stable listener identity for add/removeEventListener. */
  receiveListener: (event: Event) => void;
}

export const project = (rt: WorkerRuntimeState, status:RustStatus) => {
    const projected=projectStatus(status,rt.configuration.admission==="existing_key");
    if(rt.configuration.admission==="existing_key"&&projected.principal!==rt.configuration.expectedPrincipal)throw Error("unavailable");
    return projected;
  };

export const retireRecoveryPort = (rt: WorkerRuntimeState) => {
    const original=rt.originalRecoveryPort;rt.originalRecoveryPort=null;if(!original)return;
    original.revoke();const terminal=original.close_and_drain().then(()=>{original.free();});
    rt.recoveryDrains.add(terminal);void terminal.then(()=>rt.recoveryDrains.delete(terminal),()=>{rt.failedRecoveryPorts.add(original);/* No quiescence/free claim on failure. */});
  };

export const retireCacheMonitor = (rt: WorkerRuntimeState, slot:CacheMonitorSlot|null) => {if(!slot||slot.retired)return;slot.retired=true;slot.resource.close();if(!slot.waiting)slot.resource.free();if(rt.cacheMonitor===slot)rt.cacheMonitor=null;};

export const retireOriginalClient = (rt: WorkerRuntimeState, owned:RustClient) => {
    if(rt.client===owned||rt.reading===owned||rt.freedClients.has(owned))return;
    let state=rt.retainedClients.get(owned);
    if(!state){state={holders:0,invalidated:false};rt.retainedClients.set(owned,state);}
    if(!state.invalidated){owned.invalidate();state.invalidated=true;}
    if(state.holders===0){rt.freedClients.add(owned);rt.retainedClients.delete(owned);owned.free();}
  };

export const retainOriginalClient = (rt: WorkerRuntimeState, owned:RustClient) => {
    let state=rt.retainedClients.get(owned);
    if(!state){state={holders:0,invalidated:false};rt.retainedClients.set(owned,state);}
    state.holders++;let released=false;
    return ()=>{if(released)return;released=true;state!.holders--;retireOriginalClient(rt, owned);};
  };

export const runClientPhase = <T>(rt: WorkerRuntimeState, owned:RustClient, operation:()=>Promise<T>): Promise<T> => {
    const apply=async()=>{
      if(rt.disposed||rt.client!==owned||rt.freedClients.has(owned))throw Error("session_expired");
      if(rt.reading!==null)throw Error("unavailable");
      rt.reading=owned;
      try{return await withAuthRefreshLock(rt.locks,rt.lifetime.signal,async()=>{
        if(rt.disposed||rt.client!==owned)throw Error("session_expired");return await operation();
      });}finally{if(rt.reading===owned)rt.reading=null;retireOriginalClient(rt, owned);}
    };
    const result=rt.clientPhaseTail.then(apply,apply);
    rt.clientPhaseTail=result.then(()=>{},()=>{});return result;
  };

export const clearClient = (rt: WorkerRuntimeState) => {
    if(rt.profileCache){const original=rt.profileCache;rt.profileCache=null;original.negative=true;original.resource.cancel();rt.retiredProfileCaches.add(original);}
    rt.foregroundRecoveryClient=null;
    retireRecoveryPort(rt);
    retireCacheMonitor(rt, rt.cacheMonitor);
    const owned=rt.client;rt.client=null;
    // Revoke when the actual mutable phase returns; free only after original
    // driver owners have also drained. No copied status/census authorizes IO.
    if(owned)retireOriginalClient(rt, owned);
  };

export const ownedCacheReply = (rt: WorkerRuntimeState, input:unknown): boolean => {
    if(typeof input!=='object'||input===null||!('id'in input)||typeof input.id!=='number')return false;
    const slot=rt.ownedCacheReads.get(input.id);if(!slot)return false;
    if('cacheReply'in input){
      const pending=slot.reply;
      if(!validBrowserCacheReply(input)||!pending||input.effectId!==pending.effectId||(input.cacheDraftBudget==='original_physical_draft')!==!!pending.draftBudget){dispose(rt);return true;}
      // A revoked original IO callback still receives its ACTUAL terminal reply.
      // Never synthesize drain from cancellation, disposal, or a status flag.
      slot.reply=null;if(input.cacheReply.ok)pending.resolve(input.cacheReply.packet);else pending.reject((input.cacheReply as Extract<typeof input.cacheReply,{ok:false}>).error);return true;
    }
    if('cacheDrained'in input){
      const pending=slot.drain;
      if(!validBrowserCacheDrained(input)||!pending||input.cacheDrained.publicationId!==pending.publicationId){dispose(rt);return true;}
      slot.drain=null;pending.resolve();return true;
    }
    return false;
  };

export const ownedIdentity = (rt: WorkerRuntimeState, input:OwnedCacheRequest): BrowserOwnedCacheIdentity => ({operation:input.operation,handle:input.handle,generation:input.generation,owner:input.expectedPrincipal,chatId:input.chatId,...(input.operation==='read_cache_monitor_update'?{monitorId:input.monitorId!}:{})});

export const noOwnedDriver = (rt: WorkerRuntimeState, input:OwnedCacheRequest) => {if(input.ownedCache&&!rt.disposed)rt.endpoint.postMessage({version:1,id:input.id,cacheTerminal:ownedIdentity(rt, input),state:input.id<=rt.lastCacheReadId||rt.ownedCacheReads.has(input.id)?'unsettled':'drained'});};

export const receive = (rt: WorkerRuntimeState, event: Event) => {
    const frame=(event as MessageEvent<unknown>).data;
    if(typeof frame==='object'&&frame!==null&&'firstSessionStop' in frame){
      if(!validFirstSessionStop(frame)){dispose(rt);return;}
      if(rt.firstSessionTask?.id===frame.id){rt.firstSessionTask.stopped=true;rt.firstSessionControl?.cancel();}
      return;
    }
    if(validRequest(frame)&&(frame.operation==='check_first_session'||frame.operation==='check_first_session_data')&&!rt.firstSessionTask){
      const original={id:frame.id,stopped:false};rt.firstSessionTask=original;
      // ACTUAL original dispatch return, after awaited native work and finally.
      // Stop/cancel/Drop/error alone cannot emit this task-return correlation.
      const terminal=()=>{
        if(rt.firstSessionTask!==original)return;
        rt.firstSessionTask=null;
        const returned:FirstSessionTerminal={version:1,id:original.id,firstSessionTerminal:{requestId:original.id,state:'returned'}};
        rt.endpoint.postMessage(returned);
      };
      void dispatch(rt, frame).then(terminal,terminal);return;
    }
    void dispatch(rt, frame);
  };

export const dispose = (rt: WorkerRuntimeState) => {
    if (rt.disposed) return;
    rt.disposed = true;
    rt.firstSessionControl?.cancel();
    clearPasswordRequest(rt.passwordAdmission);rt.passwordAdmission=null;
    rt.initialSync?.operation.cancel();rt.initialSync?.acquisition.cancel();rt.initialSync?.monitor?.close();
    rt.originalStartupStore?.free();rt.originalStartupStore=undefined;
    rt.lifetime.abort();rt.originalRecoveryBootstrap?.free();rt.originalRecoveryBootstrap=undefined;retireRecoveryPort(rt);retireCacheMonitor(rt, rt.cacheMonitor);
    for(const read of rt.ownedCacheReads.values()){read.live=false;read.stopped=true;read.control?.cancel();read.continuation?.cancel();read.recoveryControl?.cancel();for(const retained of read.retainedRecoveries){try{retained.codeEmbed?.cancel();}finally{retained.control.cancel();}}}
    const cache=rt.cacheRead;rt.cacheRead=null;if(cache){cache.live=false;cache.reply?.reject('cancelled');cache.reply=null;cache.drain?.reject('cancelled');cache.drain=null;}
    const local=rt.localRead;rt.localRead=null;if(local){local.live=false;local.reply?.reject("cancelled");local.reply=null;}
    rt.sending?.close(); rt.sending = null;
    if(rt.ownedCacheReads.size===0)rt.endpoint.removeEventListener("message", rt.receiveListener);
    clearClient(rt);
  };

