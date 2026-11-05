// Type-only declarations shared by BrowserCoreWorkerHost. Split from workerHost.ts
// to keep the host module within the repository file-size limit; no runtime code.
import type {CoreRequest,CoreResponse} from "./protocol";
import type {LocalCursorEffectHandler,LocalReadPlanState,LocalReadSelector} from "./protocol";
import type {OwnedLocalReadState} from './ownedLocalReadProtocol';
import type {BrowserCacheOperation,BrowserCacheScope,BrowserCacheEffectHandler,BrowserCachePlanState,BrowserRetainedRead,BrowserCacheSourceEvidence,BrowserOwnedCacheIdentity} from './browserCacheProtocol';
import type {AuthRefreshEffectLease,openAuthRefreshEffectLease} from "./browserAdapters";
import type {BrowserCredentialIOEffect,BrowserCredentialIOResult,CredentialCasScope} from "./credentialCasProtocol";

export interface BrowserCredentialEffectHandler {current():void;execute(effect:BrowserCredentialIOEffect,lease:AuthRefreshEffectLease,signal:AbortSignal):Promise<BrowserCredentialIOResult>;close():Promise<void>}
export type RequestBody = CoreRequest extends infer R ? R extends CoreRequest ? Omit<R, "version" | "id" | "ownedCache"> : never : never;
/** Data publication only; actual Rust/root/IO resources remain independently owned. */
export interface BrowserSelectedCacheProgress {
  onSelected(selected:BrowserRetainedRead,evidence:BrowserCacheSourceEvidence):void|Promise<void>;
  createContinuationEffects(current:()=>void):BrowserCacheEffectHandler;
}
export interface Pending {
  resolve: (response: CoreResponse) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
  dispose: () => void;
  credentialCas?:{handle:string;generation:number;scope:CredentialCasScope;signal:AbortSignal;operationId?:string;effectId:number;inFlight:boolean;lease?:ReturnType<typeof openAuthRefreshEffectLease>};
  cache?:{operation:BrowserCacheOperation;handle:string;generation:number;owner:string;ids:string[];scope?:BrowserCacheScope;monitorId?:string;handler:BrowserCacheEffectHandler;
    controller:AbortController;state:BrowserCachePlanState;effectId:number;inFlight:boolean;terminal:Promise<void>;draining:boolean;drained:boolean;publicationId:string|null;
    stage?:'owned_selected'|'owned_local'|'metadata';preparedNative?:boolean;localRead?:OwnedLocalReadState;profileCache?:true;
    progressOwner?:Readonly<BrowserSelectedCacheProgress>;progress?:Promise<void>;progressPending?:boolean;
    selectedProgressReceived?:boolean;progressFailure?:Error;progressStop?:Promise<CoreResponse>;queuedContinuation?:boolean;
    originalCurrent:()=>void;ownedIdentity?:BrowserOwnedCacheIdentity;workerTerminal?:boolean;finalEvent?:MessageEvent<unknown>;stopReason?:'cancelled'|'deadline';stopDrain?:Promise<void>;stoppedDrainSent?:string;dispatched?:boolean};
  expectedSnapshot?: {handle:string;generation:number;exact?:string};
  expectedSend?: { handle: string; generation: number; operationId?: string; chatId: string | undefined; kind: "started" | "event" | "cancel_requested" | "closed" };
  passwordLogin?: true;
  existingKeyRestore?: { principal: string };
  firstSession?:{principal:string;dataOnly?:true;stopReason?:"cancelled"|"deadline"|"unavailable";response?:CoreResponse;event?:MessageEvent<unknown>;serialized?:string;terminal?:true};
  localCursor?: { selector: LocalReadSelector; planState: LocalReadPlanState; handler: LocalCursorEffectHandler; controller: AbortController; effectId: number; operationId?: string; inFlight: boolean; terminal: Promise<void> };
  expectedCheckpoint?:{handle:string;generation:number;principal:string;chatId:string;checkpointId:string};
  expectedLocal?: {handle:string;generation:number;principal:string;chatId:string;saved:boolean};
  expectedInitialSync?:{handle:string;generation:number;owner:string;stopReason?:'cancelled'|'deadline'};
  expectedMonitor?:{handle:string;generation:number;owner:string;operation:'start_cache_monitor'|'wait_cache_monitor'|'stop_cache_monitor';id?:string};
  expectedChat?: { handle: string; generation: number; chatId: string; kind: "chat" | "savedRead" };
}
