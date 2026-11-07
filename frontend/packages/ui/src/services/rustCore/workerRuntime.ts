// Rust core Worker dispatcher entry: installs one dispatcher on a Worker endpoint.
// State lives in workerRuntimeState.ts; requests in workerDispatch.ts. Inert unless a Worker entry calls it.
import type { WorkerRuntimeState } from "./workerRuntimeState";
import { dispose,receive } from "./workerRuntimeState";
import { registerCoreClientBorrows } from "./drafts/coreClientBorrow";
import type { BrowserCoreBinding,OwnedCacheSlot,ProfileCacheSlot,RustClient,RustInitialSyncStoreBootstrap,RustRecoveryBootstrap,RustRecoveryPort,WorkerConfiguration,WorkerEndpoint } from "./workerRuntimeTypes";
export type { BrowserCoreBinding,CacheMonitorSlot,OwnedCacheRequest,OwnedCacheSlot,PreparedProfile,ProfileCacheSlot,RustCacheMonitor,RustCachePublication,RustClient,RustFirstSessionControl,RustFirstSessionDataHandle,RustFirstSessionReceipt,RustInitialSyncStoreBootstrap,RustOriginalRecovery,RustOriginalRecoveryControl,RustOwnedCacheControl,RustOwnedCacheHandle,RustOwnedCacheStep,RustOwnedCacheTerminal,RustOwnedMetadata,RustPhysicalDraftInventory,RustPreparedFirstSession,RustPreparedFirstSessionData,RustProfileCacheAbsence,RustProfileCacheReadiness,RustRecoveryBootstrap,RustRecoveryPort,RustRecoveryRestoredClient,RustStatus,WorkerConfiguration,WorkerEndpoint } from "./workerRuntimeTypes";

/** Explicit opt-in foundation: no Worker is constructed or active flow replaced.
 * Binding/SDK, not this dispatcher, authenticates and compares the profile owner.
 */
export function installBrowserCoreWorker(endpoint: WorkerEndpoint, binding: BrowserCoreBinding,
  configuration: Readonly<WorkerConfiguration>, locks: LockManager, recoveryBootstrap?:RustRecoveryBootstrap,startupStoreBootstrap?:RustInitialSyncStoreBootstrap): () => void {
  const rt = {} as WorkerRuntimeState;
  rt.endpoint = endpoint;
  rt.binding = binding;
  rt.configuration = configuration;
  rt.locks = locks;
  rt.recoveryBootstrap = recoveryBootstrap;
  rt.startupStoreBootstrap = startupStoreBootstrap;
  rt.client = null;
  rt.firstSessionDataOnlyUsed = false;
  rt.firstSessionUsed = false;
  rt.firstSessionControl = null;
  rt.firstSessionTask = null;
  rt.originalRecoveryBootstrap = rt.recoveryBootstrap;
  rt.originalStartupStore = rt.startupStoreBootstrap;
  rt.originalRecoveryPort = null;
  rt.foregroundRecoveryClient = null;
  rt.recoveryDrains = new Set<Promise<void>>();
  rt.failedRecoveryPorts = new Set<RustRecoveryPort>();
  rt.reading = null;
  rt.sending = null;
  rt.casReply = null;
  rt.localRead = null;
  rt.lastLocalReadId = 0;
  rt.lastCacheReadId = 0;
  rt.cacheRead = null;
  rt.ownedCacheReads = new Map<number,OwnedCacheSlot>();
  rt.cacheMonitor = null;
  rt.profileCache = null;
  rt.retiredProfileCaches = new Set<ProfileCacheSlot>();
  rt.initialSync = null;
  rt.passwordAdmission = null;
  rt.busy = false;
  rt.disposed = false;
  rt.lifetime = new AbortController();
  rt.retainedClients = new Map<RustClient,{holders:number;invalidated:boolean}>();
  rt.freedClients = new WeakSet<RustClient>();
  rt.clientPhaseTail = Promise.resolve();
  rt.receiveListener = (event: Event) => receive(rt, event);
  rt.endpoint.addEventListener("message", rt.receiveListener);
  // Sibling units of this realm (drafts) may borrow the ADMITTED client only
  // while this dispatcher is idle; see drafts/coreClientBorrow.ts.
  const unregisterBorrows = registerCoreClientBorrows(rt);
  return (() => { unregisterBorrows(); dispose(rt); });
}
