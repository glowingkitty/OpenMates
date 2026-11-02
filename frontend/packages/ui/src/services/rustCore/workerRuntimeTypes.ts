// Structural types of the wasm-bindgen Rust core exports used by the Worker dispatcher.
import type { BrowserCacheEffect,BrowserCachePlanState,BrowserCachePrepared,BrowserCacheRecoveryProgress,BrowserCacheScope,BrowserCacheSelected,BrowserOwnedCacheIdentity,BrowserOwnedCacheTerminal } from './browserCacheProtocol';
import type { CredentialEffectMessage } from "./credentialCasProtocol";
import type { InitialSyncHandle } from './initialSyncOperation';
import { OwnedMainMetadataStore,type MainMetadataSource } from './mainMetadataStoreOperation';
import type { OwnedLocalReadState } from './ownedLocalReadProtocol';
import type { PreparedCacheMonitor } from './phasedCacheMonitorOperation';
import type { ProfileCacheInvalidation } from './profileCacheProtocol';
import type { CoreResponse,FirstSessionTerminal,LocalCursorEffect,SessionStatus } from "./protocol";
import { OwnedRecoveredReplyStore,type ReplySource } from './recoveredReplyStoreOperation';
import type { RecoveryFinalizeSource } from './recoveryFinalizationOperation';
import { OwnedRecoveryFinalization } from './recoveryFinalizationOperation';
import { OwnedSelectedCodeEmbedStore,type CodeEmbedSource } from './selectedCodeEmbedOperation';
import type { SendClient } from "./sendOperation";


/** Structural view of the new wasm-bindgen exports, not a second auth API. */
export interface RustStatus {
  readonly handle: string; readonly principal: string; readonly generation: number; readonly persisted: boolean; readonly local_read_only?: boolean;
  free(): void;
}
export interface RustCachePublication {readonly id:string;take(client:RustClient):string;free():void}
export interface RustCacheMonitor {readonly id:string;changed():Promise<boolean>;close():void;free():void}
export interface CacheMonitorSlot {status:SessionStatus;resource:RustCacheMonitor;id:string;handle:string;generation:number;owner:string;waiting:boolean;retired:boolean;explicitlyStopped:boolean}
export interface ProfileCacheSlot {original:RustClient;status:Readonly<SessionStatus>;resource:RustProfileCacheReadiness;negative:boolean;watch:Promise<void>|null}
export interface RustProfileCacheAbsence {ensure_current(client:RustClient):void;consume(client:RustClient):void;free():void}
export interface RustProfileCacheReadiness {ensure_current(client:RustClient):void;cancel():void;wait_invalidated():Promise<void>;free():void}
export interface RustOwnedCacheControl {cancel():void;ensure_current(client:RustClient):void;free():void}
export interface RustOwnedCacheTerminal {is_quiescent():boolean;free():void}
export interface RustPhysicalDraftInventory {readonly kind:string;drive():Promise<void>;apply(client:RustClient):void;free():void}
export interface RustOwnedCacheHandle {take_profile_cache_absence?(client:RustClient):RustProfileCacheAbsence;begin_physical_draft_inventory?(client:RustClient,port:RustRecoveryPort):RustPhysicalDraftInventory;control():RustOwnedCacheControl;next():Promise<RustOwnedCacheStep>;terminal?():RustOwnedCacheTerminal|undefined;free():void}
export interface RustOwnedCacheStep {
 readonly id:string;readonly kind:string;
 uses_original_physical_draft_budget?():boolean;
 apply(client:RustClient):void;execute(effect:(plan:string)=>Promise<string>):Promise<RustOwnedCacheStep>;
 take(client:RustClient):string;finish_cold(client:RustClient):void;
 pending_metadata(client:RustClient):RustOwnedMetadata;
 pending_remainder(client:RustClient):RustOwnedMetadata;
 authenticated_source_stamp(client:RustClient):string;authenticated_messages_version(client:RustClient):number|undefined;
 free():void;
}
export interface RustOriginalRecoveryControl {cancel():void;wait_cancelled():Promise<void>;free():void}
export interface RustOriginalRecovery extends RecoveryFinalizeSource<RustClient>,MainMetadataSource<RustClient>,ReplySource<RustClient>,CodeEmbedSource<RustClient> {readonly job_kind:string;readonly kind:string;control():RustOriginalRecoveryControl;failure_kind():string|undefined;drive():Promise<void>;apply(client:RustClient):void;ensure_current(client:RustClient):void;retire():void;free():void}
export interface RustOwnedMetadata {begin_next_physical_draft_inventory?(client:RustClient,port:RustRecoveryPort):RustPhysicalDraftInventory|undefined;begin_metadata(client:RustClient):RustOwnedCacheHandle;begin_next_recovery(client:RustClient,port:RustRecoveryPort):RustOriginalRecovery|undefined;readonly id:string;readonly kind:string;ensure_current(client:RustClient):void;cancel():void;wait_cancelled():Promise<void>;wait_recovery_work():Promise<void>;close():void;free():void}
export interface OwnedCacheRequest {id:number;operation:'read_cold_retained_saved_chat'|'read_cache_monitor_update';handle:string;generation:number;expectedPrincipal:string;chatId:string;selector:unknown;scope:BrowserCacheScope;nowSeconds:number;monitorId?:string;ownedCache?:true;localFirst?:true;profileCache?:true}
export interface OwnedCacheSlot {
 id:number;original:RustClient;monitor:CacheMonitorSlot|null;live:boolean;stopped:boolean;effectId:number;state:BrowserCachePlanState;localRead?:OwnedLocalReadState;localFallback?:boolean;identity:BrowserOwnedCacheIdentity;terminalRequired:boolean;
 absence:RustProfileCacheAbsence|null;control:RustOwnedCacheControl|null;continuation:RustOwnedMetadata|null;heldDriver:RustOwnedCacheHandle|null;inventory:RustPhysicalDraftInventory|null;recovery:RustOriginalRecovery|null;recoveryControl:RustOriginalRecoveryControl|null;finalization:OwnedRecoveryFinalization<RustClient>|null;mainMetadata:OwnedMainMetadataStore<RustClient>|null;replyStore:OwnedRecoveredReplyStore<RustClient>|null;retainedRecoveries:Array<{resource:RustOriginalRecovery;control:RustOriginalRecoveryControl;finalization:OwnedRecoveryFinalization<RustClient>|null;mainMetadata:OwnedMainMetadataStore<RustClient>|null;replyStore:OwnedRecoveredReplyStore<RustClient>|null;codeEmbed:OwnedSelectedCodeEmbedStore<RustClient>|null}>;
 reply:null|{effectId:number;draftBudget?:true;resolve:(value:string)=>void;reject:(error:string)=>void};
 drain:null|{publicationId:string;resolve:()=>void};
}
export interface RustClient extends SendClient {
  prepare_cache_monitor?(handle:string,generation:number,owner:string):PreparedCacheMonitor<RustClient>;
  begin_initial_sync?(handle:string,generation:number,owner:string,monitorId:string):InitialSyncHandle;
  set_foreground_recovery?(handle:string,generation:number,owner:string,enabled:boolean):void;
  prepare_profile_cache_readiness?(handle:string,generation:number,owner:string):RustProfileCacheReadiness;
  begin_owned_profile_cache_read?(readiness:RustProfileCacheReadiness,handle:string,generation:number,owner:string,chatId:string,selector:string,scope:string,nowSeconds:number):RustOwnedCacheHandle;
  begin_owned_cache_local_first_read?(handle:string,generation:number,owner:string,chatId:string,selector:string,scope:string,nowSeconds:number):RustOwnedCacheHandle;
  begin_owned_cache_cold_read?(handle:string,generation:number,owner:string,chatId:string,selector:string,scope:string,nowSeconds:number):RustOwnedCacheHandle;
  begin_owned_cache_incoming_read?(handle:string,generation:number,owner:string,monitorId:string,chatId:string,selector:string,scope:string,nowSeconds:number):RustOwnedCacheHandle;

  restore_cached_metadata?(handle:string,generation:number,owner:string,ids:string,scope:string,effect:(plan:string)=>Promise<string>):Promise<string>;
  read_cached_chat_items?(handle:string,generation:number,owner:string,ids:string):Promise<string>;
  read_retained_saved_chat?(handle:string,generation:number,owner:string,chatId:string,selector:string,scope:string,effect:(plan:string)=>Promise<string>):Promise<string>;
  start_cache_monitor?(handle:string,generation:number,owner:string):Promise<RustCacheMonitor>;
  stop_cache_monitor?(handle:string,generation:number,owner:string,monitorId:string):void;
  prepare_cache_monitor_update?(handle:string,generation:number,owner:string,monitorId:string,chatId:string,selector:string,scope:string,nowSeconds:number,effect:(plan:string)=>Promise<string>):Promise<RustCachePublication>;
  prepare_cold_retained_saved_chat?(handle:string,generation:number,owner:string,chatId:string,selector:string,scope:string,nowSeconds:number,effect:(plan:string)=>Promise<string>):Promise<RustCachePublication>;
  prepare_monitored_retained_saved_chat?(handle:string,generation:number,owner:string,chatId:string,selector:string,scope:string,nowSeconds:number,effect:(plan:string)=>Promise<string>):Promise<RustCachePublication>;

  rotate_credentials(handle:string,generation:number,scope:string,hostEffect:(encoded:string)=>Promise<string>):Promise<string>;
  prepare_credentials(handle:string,generation:number):Promise<string>;
  validate_credentials(handle:string,generation:number,encoded:string):Promise<string>;
  admitted_status(): RustStatus;
  status(handle: string, generation: number): RustStatus;
  reconnect_chat(handle: string, generation: number, chatId: string): Promise<unknown>;
  read_local_chat?(handle:string,generation:number,expectedPrincipal:string,chatId:string,encryptedRows:string,saved:boolean):Promise<string>;
  read_local_saved_chat_cursor?(handle:string,generation:number,expectedPrincipal:string,chatId:string,selector:string,hostEffect:(plan:string)=>Promise<string>):Promise<string>;
  read_local_checkpoint_summary?(handle:string,generation:number,principal:string,chatId:string,checkpointId:string,hostEffect:(plan:string)=>Promise<string>):Promise<string>;
  read_saved_chat_page?(handle:string,generation:number,chatId:string,selector:string):Promise<string>;
  read_saved_chat(handle: string, generation: number, chatId: string): Promise<string>;
  open_chat(handle: string, generation: number, chatId: string): Promise<unknown>;
  invalidate(): void;
  free(): void;
}
export interface PreparedProfile { free(): void }
export interface RustRecoveryPort {ready():Promise<void>;revoke():void;close_and_drain():Promise<void>;free():void}
export interface RustRecoveryRestoredClient {take_port():RustRecoveryPort;take_client():RustClient;free():void}
export interface RustInitialSyncStoreBootstrap {free():void}
export interface RustFirstSessionControl {cancel():void;ensure_current():void;free():void}
export interface RustFirstSessionReceipt {observed_http_status():number|undefined|null;response_json():string;control():RustFirstSessionControl;free():void}
/** Distinct DATA result: never accepted by any restore consumer. */
export interface RustFirstSessionDataHandle {observed_http_status():number|undefined|null;response_json():string;control():RustFirstSessionControl;free():void}
export interface RustPreparedFirstSessionData {control():RustFirstSessionControl;restrict_remaining_budget_ms(remaining:number):void;wait():Promise<RustFirstSessionDataHandle>;free():void}
export interface RustPreparedFirstSession {control():RustFirstSessionControl;restrict_remaining_budget_ms(remaining:number):void;wait():Promise<RustFirstSessionReceipt>;free():void}
export interface RustRecoveryBootstrap {restore_original_from_first_session?(receipt:RustFirstSessionReceipt,store:RustInitialSyncStoreBootstrap):Promise<RustRecoveryRestoredClient>;restore_original_with_startup_store?(apiUrl:string,appOrigin:string,sessionId:string,profile:PreparedProfile,store:RustInitialSyncStoreBootstrap):Promise<RustRecoveryRestoredClient>;restore_original(apiUrl:string,appOrigin:string,sessionId:string,profile:PreparedProfile):Promise<RustRecoveryRestoredClient>;free():void}
export interface BrowserCoreBinding {
  capture_initial_sync_store?(event:MessageEvent<unknown>):RustInitialSyncStoreBootstrap;
  capture_original_recovery_bootstrap?(event:MessageEvent<unknown>):RustRecoveryBootstrap|undefined;
  PreparedBrowserProfile: {
    from_existing_key?(principal:string,key:CryptoKey,hashedEmail:string|null,userEmailSalt:string|null,persisted:boolean):PreparedProfile;
    from_bytes(principal: string, raw: Uint8Array, encryptedEmail: string, userEmailSalt: string,
      persisted: boolean): PreparedProfile;
  };
  BrowserCoreClient: {
    prepare_first_session?(apiUrl:string,appOrigin:string,sessionId:string,profile:PreparedProfile,deviceSignals:string):RustPreparedFirstSession;
    prepare_first_session_data_original?(deviceSignals:string,store:RustInitialSyncStoreBootstrap):RustPreparedFirstSessionData;
    prepare_first_session_original?(profile:PreparedProfile,deviceSignals:string,store:RustInitialSyncStoreBootstrap):RustPreparedFirstSession;
    login_password?(apiUrl:string,appOrigin:string,sessionId:string,email:string,password:string,tfa:string|null,stayLoggedIn?:boolean):Promise<RustClient>;
    restore(apiUrl: string, appOrigin: string, sessionId: string, profile: PreparedProfile): Promise<RustClient>;
  };
}
export interface WorkerConfiguration { apiUrl: string; appOrigin: string; sessionId: string; admission?: "prior_profile" | "fresh_password" | "existing_key"; expectedPrincipal?:string }
export interface WorkerEndpoint extends EventTarget { postMessage(response: FirstSessionTerminal|ProfileCacheInvalidation|CoreResponse|CredentialEffectMessage|LocalCursorEffect|BrowserCacheEffect|BrowserCachePrepared|BrowserCacheSelected|BrowserOwnedCacheTerminal|BrowserCacheRecoveryProgress): void }

export function projectStatus(status: RustStatus, existingKey=false): SessionStatus {
  try {
    if(existingKey&&typeof status.local_read_only!=="boolean")throw Error("unavailable");
    return { handle: status.handle, principal: status.principal, generation: status.generation,
      persistence: status.persisted ? "persisted" : "memory_only", ...(existingKey?{localReadOnly:status.local_read_only}: {}) };
  } finally { status.free(); }
}