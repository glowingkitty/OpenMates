// The Worker consumes only the Rust receipt from this check. The browser gets
// ordinary UI data and never supplies a response or a session grant.
import { withAuthRefreshLock } from './browserAdapters';
import type { ProfileCacheInvalidation } from './profileCacheProtocol';
import { clearExistingKeyRequest, validFirstSessionData } from './protocol';
import type { CoreRequest, SessionStatus } from './protocol';
import { clearClient, project, retireRecoveryPort } from './workerRuntimeState';
import type { WorkerRuntimeState } from './workerRuntimeState';
import type {
  PreparedProfile, RustClient, RustFirstSessionReceipt,
  RustPreparedFirstSession, RustRecoveryRestoredClient,
} from './workerRuntimeTypes';

type FirstSessionRequest = Extract<CoreRequest, { operation: 'check_first_session' }>;
type RefuseFirstSession = (error: 'cancelled' | 'unavailable') => void;

export async function checkFirstSession(
  rt: WorkerRuntimeState, input: FirstSessionRequest, fail: RefuseFirstSession,
): Promise<void> {
  if (rt.originalRecoveryBootstrap || rt.originalStartupStore) {
    // The isolated original-store prototype retains its Page-owned lock contract.
    return await runFirstSession(rt, input, fail);
  }
  const task = rt.firstSessionTask;
  if (!task || task.id !== input.id || task.stopped) {
    clearExistingKeyRequest(input);
    fail('cancelled');
    return;
  }
  const queued = new AbortController();
  task.cancelQueued = () => queued.abort();
  try {
    // The Worker owns the real browser lock and the HTTP task. Closing the
    // Page's unit port can never let another caller race cookie rotation.
    await withAuthRefreshLock(rt.locks, AbortSignal.any([queued.signal, rt.lifetime.signal]), async () => {
      task.cancelQueued = undefined;
      await runFirstSession(rt, input, fail);
    });
  } finally {
    task.cancelQueued = undefined;
    clearExistingKeyRequest(input);
  }
}

async function runFirstSession(
  rt: WorkerRuntimeState, input: FirstSessionRequest, fail: RefuseFirstSession,
): Promise<void> {
  const { id } = input;
  const {PreparedBrowserProfile,BrowserCoreClient}=rt.binding;
  const prepare=PreparedBrowserProfile.from_existing_key;
  const first=BrowserCoreClient.prepare_first_session;
  const firstOriginal=BrowserCoreClient.prepare_first_session_original;
  const bootstrap=rt.originalRecoveryBootstrap,store=rt.originalStartupStore;
  const configured=!!(bootstrap||store);
  if(rt.firstSessionTask?.stopped){clearExistingKeyRequest(input);fail('cancelled');return;}
  if(rt.firstSessionUsed||rt.client||rt.configuration.admission!=='existing_key'||typeof prepare!=='function'
    ||input.profile.principal!==rt.configuration.expectedPrincipal
    ||(configured?(!bootstrap||!store||typeof firstOriginal!=='function'||typeof bootstrap.restore_original_from_first_session!=='function')
      :typeof first!=='function')){
    clearExistingKeyRequest(input);fail('unavailable');return;
  }
  rt.firstSessionUsed=true;
  let prepared:PreparedProfile;
  try{prepared=prepare(input.profile.principal,input.key,input.profile.hashedEmail,input.profile.userEmailSalt,false);}
  finally{clearExistingKeyRequest(input);}
  let pending:RustPreparedFirstSession|null=null,receipt:RustFirstSessionReceipt|null=null,profileConsumed=false,waitConsumed=false,receiptConsumed=false;
  try{
    profileConsumed=true;
    // The normal unit already validated its shared Worker route. The
    // configured path still requires its own original native store.
    const signals=JSON.stringify(input.deviceSignals);
    pending=configured?firstOriginal!(prepared,signals,store!):
      first!(rt.configuration.apiUrl,rt.configuration.appOrigin,rt.configuration.sessionId,prepared,signals);
    rt.firstSessionControl=pending.control();
    if(rt.firstSessionTask?.stopped)rt.firstSessionControl.cancel();
    if(rt.disposed||rt.lifetime.signal.aborted||rt.firstSessionTask?.stopped)throw Error('cancelled');
    rt.firstSessionControl.ensure_current();
    // Only the original auth deadline is used after acquiring the lock.
    const remaining=Math.max(0,Math.min(10000,Math.floor(input.deadlineEpochMs-Date.now())));
    pending.restrict_remaining_budget_ms(remaining);
    if(remaining===0)throw Error('deadline');
    waitConsumed=true;receipt=await pending.wait();pending=null;
    const receiptControl=receipt.control();rt.firstSessionControl.free();rt.firstSessionControl=receiptControl;
    if(rt.disposed||rt.lifetime.signal.aborted||rt.firstSessionTask?.stopped)throw Error('cancelled');
    rt.firstSessionControl.ensure_current();
    const httpStatus=receipt.observed_http_status()??null;
    let data:Record<string,unknown>|null=null;
    try{const encoded=receipt.response_json();const parsed:unknown=JSON.parse(encoded);
      if(!validFirstSessionData({httpStatus,data:parsed}))throw Error('unavailable');data=parsed as Record<string,unknown>;
    }catch{/* Preserve actual HTTP status DATA even when body/read/crypto is unavailable. */}
    const firstSession={httpStatus,data};if(!validFirstSessionData(firstSession))throw Error('unavailable');
    let status:SessionStatus|null=null;
    if(httpStatus===200&&data?.success===true){
      // Only the opaque ORIGINAL receipt can restore; UI JSON is never input.
      rt.originalRecoveryBootstrap=undefined;rt.originalStartupStore=undefined;
      let restored:RustRecoveryRestoredClient|null=null;
      try{
        let admitted:RustClient;
        if(configured){
          receiptConsumed=true;restored=await bootstrap!.restore_original_from_first_session!(receipt,store!);receipt=null;
          rt.originalRecoveryPort=restored.take_port();admitted=restored.take_client();
        }else{
          if(typeof receipt.admit_existing!=='function')throw Error('unavailable');
          receiptConsumed=true;admitted=receipt.admit_existing();receipt=null;
        }
        if(rt.disposed||rt.firstSessionTask?.stopped){retireRecoveryPort(rt);admitted.invalidate();admitted.free();fail('cancelled');return;}
        rt.client=admitted;status=project(rt, rt.client.admitted_status());
        if(status.principal!==rt.configuration.expectedPrincipal||status.persistence!=='memory_only'||typeof status.localReadOnly!=='boolean'||(!configured&&status.localReadOnly))throw Error('unavailable');
        if(configured){
          if(typeof rt.client.prepare_profile_cache_readiness!=='function')throw Error('unavailable');
          const original={original:rt.client,status:Object.freeze({...status}),resource:rt.client.prepare_profile_cache_readiness(status.handle,status.generation,status.principal),negative:false,watch:null as Promise<void>|null};
          original.resource.ensure_current(rt.client);rt.profileCache=original;
          const invalidate=()=>{original.negative=true;original.resource.cancel();if(!rt.disposed&&rt.profileCache===original&&rt.client===original.original){
            const frame:ProfileCacheInvalidation={version:1,profileCacheInvalidated:{handle:original.status.handle,generation:original.status.generation,owner:original.status.principal}};rt.endpoint.postMessage(frame);
          }};
          original.watch=original.resource.wait_invalidated().then(invalidate,()=>{invalidate();rt.retiredProfileCaches.add(original);});
        }
      }catch{clearClient(rt);retireRecoveryPort(rt);status=null;}
      finally{restored?.free();}
    }
    if(rt.firstSessionTask?.stopped){clearClient(rt);retireRecoveryPort(rt);fail('cancelled');}
    else if(!rt.disposed)rt.endpoint.postMessage({version:1,id,ok:true,status,firstSession});
  }finally{
    if(!profileConsumed)prepared.free();if(pending&&!waitConsumed)pending.free();if(receipt&&!receiptConsumed)receipt.free();
    rt.firstSessionControl?.free();rt.firstSessionControl=null;
  }
}
