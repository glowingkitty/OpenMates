// Request dispatcher of the Rust core Worker; all Rust work goes through the wasm binding.
import { withAuthRefreshLock } from "./browserAdapters";
import { advanceBrowserCachePlan,browserCachePlansComplete,retainedKindMatches,sameBrowserOwnedCacheIdentity,validBrowserCacheDrained,validBrowserCacheReply,validBrowserCachedMetadataRead,validBrowserIncomingCacheUpdate,validBrowserOwnedCacheStop,validBrowserRetainedRead } from './browserCacheProtocol';
import { validBrowserSealedCredentials } from "./browserCredentialStorage";
import { validCredentialCasValidation,validCredentialEffectMessage,validCredentialEffectReply } from "./credentialCasProtocol";
import type { InitialSyncClient } from './initialSyncOperation';
import { OwnedInitialSyncOperation } from './initialSyncOperation';
import { validInitialSyncStop } from './initialSyncProtocol';
import { OwnedCacheMonitorAcquisition } from './phasedCacheMonitorOperation';
import type { ProfileCacheInvalidation } from './profileCacheProtocol';
import type { SessionStatus } from "./protocol";
import { advanceLocalReadPlan,clearExistingKeyRequest,clearPasswordRequest,parseBrowserLocalReadPlan,validChat,validFirstSessionData,validLocalCursorReply,validRequest } from "./protocol";
import { validCheckpointPresentation,validLocalRead,validSavedRead } from "./savedReadProtocol";
import { OwnedSelectedCodeEmbedStore } from './selectedCodeEmbedOperation';
import { OwnedSendOperation } from "./sendOperation";
import { consumeWorkerMasterKey } from "./workerCredentials";
import { runOwnedCacheRead } from "./workerOwnedCacheRead";
import type { WorkerRuntimeState } from "./workerRuntimeState";
import { clearClient,dispose,noOwnedDriver,ownedCacheReply,project,retainOriginalClient,retireCacheMonitor,retireOriginalClient,retireRecoveryPort,runClientPhase } from "./workerRuntimeState";
import type { CacheMonitorSlot,PreparedProfile,RustCacheMonitor,RustCachePublication,RustClient,RustFirstSessionDataHandle,RustFirstSessionReceipt,RustPreparedFirstSession,RustPreparedFirstSessionData,RustRecoveryRestoredClient } from "./workerRuntimeTypes";

/** Request dispatcher of the Rust core Worker. */
export const dispatch = async (rt: WorkerRuntimeState, input: unknown) => {
    if(typeof input==='object'&&input!==null&&'cacheStop'in input){
      if(!validBrowserOwnedCacheStop(input)){dispose(rt);return;}
      const original=rt.ownedCacheReads.get(input.id);
      // A terminal may already have been posted in the original FIFO lane.
      // Stale negative control never admits or targets a different resource.
      if(!original)return;
      if(!original.terminalRequired||!sameBrowserOwnedCacheIdentity(original.identity,input.cacheStop)){dispose(rt);return;}
      original.stopped=true;original.control?.cancel();original.continuation?.cancel();original.recoveryControl?.cancel();for(const retained of original.retainedRecoveries){try{retained.codeEmbed?.cancel();}finally{retained.control.cancel();}}return;
    }
    if(ownedCacheReply(rt, input))return;
    if (rt.disposed) { clearPasswordRequest(input);clearExistingKeyRequest(input); return; }
    // Invalid envelopes have no trustworthy request ID: close the endpoint's
    // admission path instead of reflecting arbitrary data back to the page.
    if(typeof input==='object'&&input!==null&&'cacheDrained' in input){
      if(validBrowserCacheDrained(input)&&input.id<=rt.lastCacheReadId&&(!rt.cacheRead||input.id<rt.cacheRead.id))return;
      const pending=rt.cacheRead?.drain;
      if(!validBrowserCacheDrained(input)||!rt.cacheRead?.live||!pending||input.id!==rt.cacheRead.id||input.cacheDrained.publicationId!==pending.publicationId){dispose(rt);return;}
      rt.cacheRead.drain=null;pending.resolve();return;
    }
    if(typeof input==='object'&&input!==null&&'cacheReply' in input){
      if(validBrowserCacheReply(input)&&input.id<=rt.lastCacheReadId&&(!rt.cacheRead||input.id<rt.cacheRead.id))return;
      const pending=rt.cacheRead?.reply;
      if(!validBrowserCacheReply(input)||input.cacheDraftBudget!==undefined||!rt.cacheRead?.live||!pending||input.id!==rt.cacheRead.id||input.effectId!==pending.effectId){dispose(rt);return;}
      rt.cacheRead.reply=null;if(input.cacheReply.ok)pending.resolve(input.cacheReply.packet);else pending.reject((input.cacheReply as Extract<typeof input.cacheReply,{ok:false}>).error);return;
    }
    if(typeof input==='object'&&input!==null&&'localReadReply' in input){
      // A valid retired reply cannot cancel a later request. It resolves no
      // callback and carries no admission/publication authority into the new one.
      if(validLocalCursorReply(input)&&input.id<=rt.lastLocalReadId&&(!rt.localRead||input.id<rt.localRead.id))return;
      const pending = rt.localRead?.reply;
      if(!validLocalCursorReply(input)||!rt.localRead?.live||!pending||input.id!==rt.localRead.id||input.effectId!==pending.effectId
        ||input.localReadReply.operationId!==pending.operationId){dispose(rt);return;}
      rt.localRead.reply=null;
      if(input.localReadReply.ok){
        if(new TextEncoder().encode(input.localReadReply.packet).byteLength>pending.maxBytes){pending.reject("unavailable");dispose(rt);return;}
        pending.resolve(input.localReadReply.packet);
      }else pending.reject((input.localReadReply as Extract<typeof input.localReadReply,{ok:false}>).error);
      return;
    }
    if(typeof input==='object'&&input!==null&&'hostReply' in input){
      if(!validCredentialEffectReply(input)||!rt.casReply||input.id!==rt.casReply.id||input.effectId!==rt.casReply.effectId
        ||input.hostReply.ok&&input.hostReply.result.operationId!==rt.casReply.operationId){dispose(rt);return;}
      const owned=rt.casReply;rt.casReply=null;
      if(input.hostReply.ok)owned.resolve(JSON.stringify(input.hostReply.result));else owned.reject((input.hostReply as Extract<typeof input.hostReply,{ok:false}>).error);
      return;
    }
    if(typeof input==='object'&&input!==null&&'initialSyncStop' in input){
      if(!validInitialSyncStop(input)){dispose(rt);return;}
      const original=rt.initialSync,identity=input.initialSyncStop;
      if(original&&original.original===rt.client&&original.id===input.id&&original.handle===identity.handle&&original.generation===identity.generation&&original.owner===identity.owner){
        original.operation.cancel();original.acquisition.cancel();original.monitor?.close();
      }
      return; // Stale control never reaches a successor or another owned read.
    }
    if (!validRequest(input)) { clearPasswordRequest(input);clearExistingKeyRequest(input); dispose(rt); return; }
    const { id } = input;
    const fail = (error: "cancelled" | "unavailable" | "reauthentication_required" | "session_expired" | "chat_unavailable" | "credential_conflict" | "authentication_failed" | "two_factor_required") => {
      if (!rt.disposed) rt.endpoint.postMessage({ version: 1, id, ok: false, error });
    };
    if (input.operation === "invalidate" || input.operation === "cancel") { dispose(rt); return; }
    if(rt.firstSessionDataOnlyUsed){clearExistingKeyRequest(input);fail('unavailable');return;}
    if(input.operation==='run_initial_sync'){
      if(rt.initialSync||rt.busy||rt.sending||rt.reading||rt.cacheMonitor||rt.cacheRead||rt.ownedCacheReads.size||!rt.client){fail('unavailable');return;}
      const owned=rt.client;
      if(typeof owned.begin_initial_sync!=='function'||typeof owned.prepare_cache_monitor!=='function'){fail('unavailable');return;}
      const current=()=>{if(rt.disposed||rt.lifetime.signal.aborted||rt.client!==owned)throw Error('session_expired');const status=project(rt, owned.status(input.handle,input.generation));if(status.principal!==input.expectedPrincipal||status.localReadOnly===true)throw Error('session_expired');};
      const operation=new OwnedInitialSyncOperation(owned as RustClient&InitialSyncClient,phase=>runClientPhase(rt, owned,phase),current);
      const acquisition=new OwnedCacheMonitorAcquisition(owned,owned.prepare_cache_monitor.bind(owned),phase=>runClientPhase(rt, owned,phase),current);
      const slot={id:input.id,handle:input.handle,generation:input.generation,owner:input.expectedPrincipal,original:owned,operation,acquisition,monitor:null as RustCacheMonitor|null,ready:acquisition.run({handle:input.handle,generation:input.generation,owner:input.expectedPrincipal}),task:null as Promise<void>|null,release:retainOriginalClient(rt, owned)};
      rt.initialSync=slot;
      slot.task=(async()=>{
        try{
          slot.monitor=await slot.ready;
          const result=await operation.run({handle:input.handle,generation:input.generation,owner:input.expectedPrincipal,monitorId:slot.monitor!.id});
          await runClientPhase(rt, owned,async()=>{current();rt.endpoint.postMessage({version:1,id:input.id,ok:true,status:project(rt, owned.status(input.handle,input.generation)),initialSync:result});});
          // Typed store completion permits releasing this Client holder only.
          // The original operation/monitor remain held; no full/global ACK.
          slot.release();
        }catch{operation.cancel();if(!rt.disposed)fail('unavailable');/* Unknown work/resources stay in this exact slot. */}
      })();
      await slot.task;return;
    }
    if(input.operation==='store_selected_main_code_embed'){
      const slot=rt.ownedCacheReads.get(input.recoveryRequestId),owned=rt.client;
      // Request IDs/UUIDs only select an ALREADY retained original resource.
      // No scalar can supply Main, metadata/native proof, key, row or store.
      if(!owned||!slot||slot.original!==owned||slot.identity.handle!==input.handle||slot.identity.generation!==input.generation
        ||slot.recovery!==null||slot.mainMetadata!==null){fail('unavailable');return;}
      const matches=slot.retainedRecoveries.filter(value=>value.mainMetadata!==null);
      if(matches.length!==1){fail('unavailable');return;}
      const retained=matches[0];
      if(retained.codeEmbed||!retained.replyStore||retained.resource.job_kind!=='main'
        ||typeof retained.resource.prepare_selected_code_embed_read!=='function'
        ||typeof retained.resource.begin_selected_code_embed_local_store!=='function'){fail('unavailable');return;}
      const current=()=>{if(rt.disposed||rt.client!==owned||!slot.live||slot.stopped||slot.monitor?.retired)throw Error('session_expired');};
      try{
        // Reserve the genuine Main record BEFORE any await. Refusal/unknown
        // keeps this exact owner and prevents rearm, not merely a JS flag.
        const operation=new OwnedSelectedCodeEmbedStore(owned,retained.resource,retained.mainMetadata!,input.embedId,
          phase=>runClientPhase(rt, owned,phase),current);
        retained.codeEmbed=operation;
        await runClientPhase(rt, owned,async()=>{current();retained.mainMetadata!.ensure_current();retained.replyStore!.ensure_current();});
        await operation.run();
        await runClientPhase(rt, owned,async()=>{current();operation.ensure_current();current();
          // Nonfinal DATA only. Never a native/Root completion or Main ACK.
          rt.endpoint.postMessage({version:1,id,ok:true,status:null});});
      }catch{if(!rt.disposed)fail('unavailable');/* All actual resources stay held on retained.codeEmbed. */}
      return;
    }
    if(rt.initialSync&&input.operation!=='status'&&!(input.operation==='read_cold_retained_saved_chat'&&input.ownedCache===true)){fail('unavailable');return;}

    if(input.operation==='stop_cache_monitor'){
      const slot=rt.cacheMonitor;
      if(!slot||slot.retired||slot.id!==input.monitorId||slot.handle!==input.handle||slot.generation!==input.generation||slot.owner!==input.expectedPrincipal){fail('unavailable');return;}
      // Cancellation owns this original opaque resource, not a mutable Client or
      // the global Worker. It can close A while another Client borrow is busy.
      slot.explicitlyStopped=true;for(const read of rt.ownedCacheReads.values())if(read.monitor===slot){read.stopped=true;read.control?.cancel();read.continuation?.cancel();read.recoveryControl?.cancel();for(const retained of read.retainedRecoveries){try{retained.codeEmbed?.cancel();}finally{retained.control.cancel();}}}retireCacheMonitor(rt, slot);
      if(!rt.busy&&rt.client&&rt.reading!==rt.client){try{rt.client.stop_cache_monitor?.(input.handle,input.generation,input.expectedPrincipal,input.monitorId);}catch{/* Negative resource close already completed. */}}
      rt.endpoint.postMessage({version:1,id,ok:true,status:null,cacheMonitor:{id:input.monitorId,state:'closed'}});return;
    }
    if(input.operation==='wait_cache_monitor'){
      const slot=rt.cacheMonitor,owned=rt.client;
      if(rt.busy||!owned||!slot||slot.retired||slot.waiting||slot.id!==input.monitorId||slot.handle!==input.handle||slot.generation!==input.generation||slot.owner!==input.expectedPrincipal){fail('unavailable');return;}
      // Captured status accompanies keyless readiness only; it grants no read.
      // Never borrow the mutable Client while an exact send owns it.
      const status=slot.status;
      if(status.principal!==input.expectedPrincipal||status.localReadOnly===true){fail('session_expired');return;}
      slot.waiting=true;
      try{const ready=await slot.resource.changed();
        const original=rt.sending;
        if(original?.owns(owned)&&!original.usesOwnedDriver){
          await original.finished;
          if(rt.sending!==null&&rt.sending!==original||original.failed||!original.terminalDisposition?.canContinueParent)throw Error('session_expired');
        }
        // Keyless readiness is not access/publication authority. Do not borrow
        // the Client while another short read may own its mutable WASM lane.
        if(rt.disposed||rt.client!==owned||rt.cacheMonitor!==slot||slot.retired)throw Error('session_expired');
        rt.endpoint.postMessage({version:1,id,ok:true,status,cacheMonitor:{id:slot.id,state:ready?'ready':'idle'}});
      }catch{retireCacheMonitor(rt, slot);fail('session_expired');}
      finally{slot.waiting=false;if(slot.retired)slot.resource.free();}
      return;
    }
    if (input.operation === "next_send_event" || input.operation === "cancel_send" || input.operation === "close_send") {
      const active = rt.sending;
      if (!active || !active.matches(input.handle, input.generation, input.operationId)) { fail("session_expired"); return; }
      if (input.operation === "next_send_event" && active.isPolling) { fail("unavailable"); return; }
      try {
        if (input.operation === "cancel_send") {
          active.cancel(input.handle, input.generation, input.operationId);
          if (!rt.disposed) rt.endpoint.postMessage({ version: 1, id, ok: true, status: null,
            send: { operationId: active.operationId, kind: "cancel_requested" } });
        } else if (input.operation === "close_send") {
          active.requestClose(input.handle, input.generation, input.operationId);
          if(active.usesOwnedDriver){
            // Wait OUTSIDE a Client/auth lease for this exact original future,
            // actual terminal consume and original parent continuation proof.
            await active.finished;
            if(rt.sending===active)rt.sending=null;
            if(active.owns(rt.client)&&(active.failed||!active.terminalDisposition?.canContinueParent))clearClient(rt);
            if(!rt.disposed)rt.endpoint.postMessage({version:1,id,ok:true,status:null,
              send:{operationId:active.operationId,kind:"closed",...(active.terminalDisposition?{terminal:active.terminalDisposition}:{})}});
          }else{
            rt.sending = null; if (active.owns(rt.client)) clearClient(rt);
            if (!rt.disposed) rt.endpoint.postMessage({ version: 1, id, ok: true, status: null,
              send: { operationId: active.operationId, kind: "closed" } });
          }
        } else {
          // At most one parsed update can cross this async return boundary.
          // Refuse it under the exact original Rust resource, then pull that
          // resource's canonical terminal; never mint a terminal from timing.
          for(let pull=0;pull<2;pull++){
            const event = await active.next(input.handle, input.generation, input.operationId);
            if (rt.disposed) return;
            if(event?.type==="update"){
              if(!active.publicationCurrent(input.handle,input.generation,input.operationId))continue;
              // No await between this original-resource check and the transfer.
              rt.endpoint.postMessage({version:1,id,ok:true,status:null,
                send:{operationId:active.operationId,kind:"event",event}});
              return;
            }
            if (rt.sending === active) rt.sending = null;
            if (event?.type === "error" && active.owns(rt.client)
              && !active.terminalDisposition?.canContinueParent) clearClient(rt);
            rt.endpoint.postMessage({ version: 1, id, ok: true, status: null,
              send: { operationId: active.operationId, kind: "event", event,
                ...(active.terminalDisposition?{terminal:active.terminalDisposition}:{}) } });
            return;
          }
          throw Error("session_expired");
        }
      } catch {
        if (input.operation === "next_send_event") {
          active.close();
          if(active.usesOwnedDriver){
            // close can reject a pending event borrow BEFORE the original
            // driver returns. Suppress that poll, but retain the SAME Client
            // until its actual terminal/disposition has been processed once.
            // This wait holds no Client/auth lease and grants no continuation.
            await active.finished;
            if(rt.sending===active)rt.sending=null;
            if(active.owns(rt.client)&&(active.failed||!active.terminalDisposition?.canContinueParent))clearClient(rt);
          }else{
            if (rt.sending === active) rt.sending = null;
            if (active.owns(rt.client)) clearClient(rt);
          }
        }
        fail("session_expired");
      }
      return;
    }
    if((input.operation==='read_cold_retained_saved_chat'||input.operation==='read_cache_monitor_update')&&input.ownedCache){
      const owned=rt.client,complete=owned&&typeof owned.begin_owned_cache_cold_read==='function'&&typeof owned.begin_owned_cache_incoming_read==='function';
      if(!complete||input.operation==='read_cold_retained_saved_chat'&&input.localFirst&&typeof owned!.begin_owned_cache_local_first_read!=='function'){fail('unavailable');noOwnedDriver(rt, {...input,operation:input.operation});return;}
      await runOwnedCacheRead(rt, {...input,operation:input.operation},fail);return;
    }
    if((input.operation==='read_cold_retained_saved_chat'||input.operation==='read_cache_monitor_update')&&rt.client){
      const owned=rt.client,complete=typeof owned.begin_owned_cache_cold_read==='function'&&typeof owned.begin_owned_cache_incoming_read==='function';
      // Ordinary no-send incoming keeps its compatibility path. The bounded
      // concurrent incoming variant requires the actual owned send/runtime.
      if(complete&&(input.operation==='read_cold_retained_saved_chat'||rt.sending?.usesOwnedDriver)){
        await runOwnedCacheRead(rt, {...input,operation:input.operation},fail);return;
      }
    }
    if(input.operation==='start_cache_monitor'&&rt.sending?.usesOwnedDriver){
      const owned=rt.client;if(!owned||rt.busy){fail('unavailable');return;}
      const previous=rt.cacheMonitor;let started:RustCacheMonitor|null=null;
      try{await runClientPhase(rt, owned,async()=>{
        const status=project(rt, owned.status(input.handle,input.generation));
        if(status.principal!==input.expectedPrincipal||status.localReadOnly===true||typeof owned.start_cache_monitor!=='function')throw Error('unavailable');
        started=await owned.start_cache_monitor(input.handle,input.generation,input.expectedPrincipal);
        if(rt.disposed||rt.client!==owned)throw Error('session_expired');
        const actual=started;if(!actual||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(actual.id))throw Error('unavailable');
        const after=project(rt, owned.status(input.handle,input.generation));
        if(after.principal!==input.expectedPrincipal||after.localReadOnly===true)throw Error('session_expired');
        retireCacheMonitor(rt, previous);rt.cacheMonitor={status:after,resource:actual,id:actual.id,handle:input.handle,generation:input.generation,owner:input.expectedPrincipal,waiting:false,retired:false,explicitlyStopped:false};started=null;
        rt.endpoint.postMessage({version:1,id,ok:true,status:after,cacheMonitor:{id:actual.id,state:'started'}});
      });}catch{fail('unavailable');}finally{const abandoned=started as RustCacheMonitor|null;if(abandoned){abandoned.close();abandoned.free();}}
      return;
    }
    if(input.operation==='set_foreground_recovery'){
      const owned=rt.client;
      if(!owned||typeof owned.set_foreground_recovery!=='function'){fail('unavailable');return;}
      try{await runClientPhase(rt, owned,async()=>{
        if(rt.disposed||rt.client!==owned)throw Error('session_expired');
        const status=project(rt, owned.status(input.handle,input.generation));
        if(status.principal!==input.expectedPrincipal||status.localReadOnly===true)throw Error('session_expired');
        owned.set_foreground_recovery!(input.handle,input.generation,input.expectedPrincipal,input.enabled);
        rt.foregroundRecoveryClient=input.enabled?owned:null;
        rt.endpoint.postMessage({version:1,id,ok:true,status});
      });}catch{fail('session_expired');}return;
    }
    // A pending selected update may wait only for the exact original send.
    // Actual Rust hints stay bounded; no Client borrow/lock is held while waiting.
    let drainedSend:OwnedSendOperation|null=null;
    if(input.operation==='read_cache_monitor_update'&&rt.sending){
      const original=rt.sending,owned=rt.client;
      if(!original.owns(owned)){fail('session_expired');return;}
      await original.finished;
      if(rt.disposed||rt.client!==owned||rt.sending!==null&&rt.sending!==original||original.failed||!original.terminalDisposition?.canContinueParent){fail('session_expired');return;}
      drainedSend=original;
    }
    if (rt.busy || rt.sending&&rt.sending!==drainedSend) { clearPasswordRequest(input);clearExistingKeyRequest(input); fail("unavailable"); return; }
    if(rt.configuration.admission==="existing_key"&&["prepare_credentials","validate_credentials","rotate_credentials"].includes(input.operation)){
      clearExistingKeyRequest(input);fail("unavailable");return;
    }
    rt.busy = true;
    let stoppedOriginalUpdate:(()=>boolean)|null=null;
    try {
      if (input.operation === "login_password") {
        const login=rt.binding.BrowserCoreClient.login_password;
        if (rt.configuration.admission!=="fresh_password" || rt.client || typeof login!=="function") {
          clearPasswordRequest(input); fail("unavailable"); return;
        }
        rt.passwordAdmission=input;
        try {
          const admitted=await withAuthRefreshLock(rt.locks,rt.lifetime.signal,()=>{
            let password=new TextDecoder("utf-8",{fatal:true}).decode(input.password);
            let tfa=input.tfa?new TextDecoder("utf-8",{fatal:true}).decode(input.tfa):null;
            try { return login(rt.configuration.apiUrl,rt.configuration.appOrigin,rt.configuration.sessionId,input.email,password,tfa,input.stayLoggedIn ?? false); }
            finally { password="";tfa=null;clearPasswordRequest(input); }
          });
          if (rt.disposed) { admitted.invalidate();admitted.free();return; }
          rt.client=admitted;
          const status=project(rt, rt.client.admitted_status());
          if (status.persistence!=="memory_only") throw Error("unavailable");
          rt.endpoint.postMessage({version:1,id,ok:true,status});
        } finally { clearPasswordRequest(input);if(rt.passwordAdmission===input)rt.passwordAdmission=null; }
      } else if(input.operation==='check_first_session_data') {
        const first=rt.binding.BrowserCoreClient.prepare_first_session_data_original,store=rt.originalStartupStore;
        if(rt.firstSessionTask?.stopped){fail('cancelled');return;}
        if(rt.firstSessionUsed||rt.client||rt.configuration.admission!=='existing_key'||typeof first!=='function'||!store){fail('unavailable');return;}
        rt.firstSessionUsed=true;rt.firstSessionDataOnlyUsed=true;
        let pending:RustPreparedFirstSessionData|null=null,receipt:RustFirstSessionDataHandle|null=null,waitConsumed=false;
        try{
          pending=first(JSON.stringify(input.deviceSignals),store);rt.firstSessionControl=pending.control();
          if(rt.firstSessionTask?.stopped)rt.firstSessionControl.cancel();
          if(rt.disposed||rt.lifetime.signal.aborted||rt.firstSessionTask?.stopped)throw Error('cancelled');
          rt.firstSessionControl.ensure_current();
          const remaining=Math.max(0,Math.min(10000,Math.floor(input.deadlineEpochMs-Date.now())));
          pending.restrict_remaining_budget_ms(remaining);if(remaining===0)throw Error('deadline');
          waitConsumed=true;receipt=await pending.wait();pending=null;
          const receiptControl=receipt.control();rt.firstSessionControl.free();rt.firstSessionControl=receiptControl;
          if(rt.disposed||rt.lifetime.signal.aborted||rt.firstSessionTask?.stopped)throw Error('cancelled');
          rt.firstSessionControl.ensure_current();
          const httpStatus=receipt.observed_http_status()??null;let data:Record<string,unknown>|null=null;
          try{const parsed:unknown=JSON.parse(receipt.response_json());if(!validFirstSessionData({httpStatus,data:parsed}))throw Error('unavailable');data=parsed as Record<string,unknown>;}
          catch{/* Exact actual status remains DATA when the bounded body is unavailable. */}
          const firstSession={httpStatus,data};if(!validFirstSessionData(firstSession))throw Error('unavailable');
          if(rt.firstSessionTask?.stopped)fail('cancelled');
          else if(!rt.disposed)rt.endpoint.postMessage({version:1,id,ok:true,status:null,firstSession});
        }finally{
          if(pending&&!waitConsumed)pending.free();receipt?.free();rt.firstSessionControl?.free();rt.firstSessionControl=null;
        }
      } else if(input.operation==='check_first_session') {
        const prepare=rt.binding.PreparedBrowserProfile.from_existing_key,first=rt.binding.BrowserCoreClient.prepare_first_session_original;
        const bootstrap=rt.originalRecoveryBootstrap,store=rt.originalStartupStore;
        if(rt.firstSessionTask?.stopped){clearExistingKeyRequest(input);fail('cancelled');return;}
        if(rt.firstSessionUsed||rt.client||rt.configuration.admission!=='existing_key'||typeof prepare!=='function'||typeof first!=='function'
          ||input.profile.principal!==rt.configuration.expectedPrincipal||!bootstrap||!store||typeof bootstrap.restore_original_from_first_session!=='function'){
          clearExistingKeyRequest(input);fail('unavailable');return;
        }
        rt.firstSessionUsed=true;
        let prepared:PreparedProfile;
        try{prepared=prepare(input.profile.principal,input.key,input.profile.hashedEmail,input.profile.userEmailSalt,false);}
        finally{clearExistingKeyRequest(input);}
        let pending:RustPreparedFirstSession|null=null,receipt:RustFirstSessionReceipt|null=null,profileConsumed=false,waitConsumed=false,receiptConsumed=false;
        try{
          profileConsumed=true;
          // The SAME captured native store supplies configured routes and actual
          // profile before HTTP; Page configuration strings confer no authority.
          pending=first(prepared,JSON.stringify(input.deviceSignals),store);
          rt.firstSessionControl=pending.control();
          if(rt.firstSessionTask?.stopped)rt.firstSessionControl.cancel();
          if(rt.disposed||rt.lifetime.signal.aborted||rt.firstSessionTask?.stopped)throw Error('cancelled');
          rt.firstSessionControl.ensure_current();
          // The Page already owns its original auth-session refresh WebLock.
          // Floor the ORIGINAL outer budget after all setup; never renew it.
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
              receiptConsumed=true;restored=await bootstrap.restore_original_from_first_session(receipt,store);receipt=null;
              rt.originalRecoveryPort=restored.take_port();const admitted=restored.take_client();
              if(rt.disposed||rt.firstSessionTask?.stopped){retireRecoveryPort(rt);admitted.invalidate();admitted.free();fail('cancelled');return;}
              rt.client=admitted;status=project(rt, rt.client.admitted_status());
              if(status.principal!==rt.configuration.expectedPrincipal||status.persistence!=='memory_only'||typeof status.localReadOnly!=='boolean')throw Error('unavailable');
              if(typeof rt.client.prepare_profile_cache_readiness!=='function')throw Error('unavailable');
              const original={original:rt.client,status:Object.freeze({...status}),resource:rt.client.prepare_profile_cache_readiness(status.handle,status.generation,status.principal),negative:false,watch:null as Promise<void>|null};
              original.resource.ensure_current(rt.client);rt.profileCache=original;
              const invalidate=()=>{original.negative=true;original.resource.cancel();if(!rt.disposed&&rt.profileCache===original&&rt.client===original.original){
                const frame:ProfileCacheInvalidation={version:1,profileCacheInvalidated:{handle:original.status.handle,generation:original.status.generation,owner:original.status.principal}};rt.endpoint.postMessage(frame);
              }};
              original.watch=original.resource.wait_invalidated().then(invalidate,()=>{invalidate();rt.retiredProfileCaches.add(original);});
            }catch{clearClient(rt);retireRecoveryPort(rt);status=null;}
            finally{restored?.free();}
          }
          if(rt.firstSessionTask?.stopped){clearClient(rt);retireRecoveryPort(rt);fail('cancelled');}
          else if(!rt.disposed)rt.endpoint.postMessage({version:1,id,ok:true,status,firstSession});
        }finally{
          if(!profileConsumed)prepared.free();if(pending&&!waitConsumed)pending.free();if(receipt&&!receiptConsumed)receipt.free();
          rt.firstSessionControl?.free();rt.firstSessionControl=null;
        }
      } else if(input.operation==="restore_existing") {
        const prepare=rt.binding.PreparedBrowserProfile.from_existing_key;
        if(rt.configuration.admission!=="existing_key"||typeof prepare!=="function"
          ||typeof rt.configuration.expectedPrincipal!=="string"
          ||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(rt.configuration.expectedPrincipal)
          ||input.profile.principal!==rt.configuration.expectedPrincipal){
          clearExistingKeyRequest(input);fail("unavailable");return;
        }
        clearClient(rt);
        let prepared:PreparedProfile;
        try {prepared=prepare(input.profile.principal,input.key,input.profile.hashedEmail,input.profile.userEmailSalt,false);}
        finally {clearExistingKeyRequest(input);}
        let consumed=false;
        try {
          const bootstrap=rt.originalRecoveryBootstrap;
          const originalStoreBound=!!rt.originalStartupStore;
          let restored:RustRecoveryRestoredClient|null=null;
          const admitted=await withAuthRefreshLock(rt.locks,rt.lifetime.signal,async()=>{
            consumed=true;
            if(!bootstrap)return rt.binding.BrowserCoreClient.restore(rt.configuration.apiUrl,rt.configuration.appOrigin,rt.configuration.sessionId,prepared);
            rt.originalRecoveryBootstrap=undefined;
            // The native Rust constructor binds Root before exposing Client.
            if(rt.originalStartupStore){
              const store=rt.originalStartupStore;rt.originalStartupStore=undefined;
              if(typeof bootstrap.restore_original_with_startup_store!=='function')throw Error('unavailable');
              restored=await bootstrap.restore_original_with_startup_store(rt.configuration.apiUrl,rt.configuration.appOrigin,rt.configuration.sessionId,prepared,store);
            }else restored=await bootstrap.restore_original(rt.configuration.apiUrl,rt.configuration.appOrigin,rt.configuration.sessionId,prepared);
            try{rt.originalRecoveryPort=restored.take_port();return restored.take_client();}
            finally{restored.free();restored=null;}
          });
          if(rt.disposed){retireRecoveryPort(rt);admitted.invalidate();admitted.free();return;}
          rt.client=admitted;
          const status=project(rt, rt.client.admitted_status());
          if(status.persistence!=="memory_only")throw Error("unavailable");
          if(originalStoreBound){
            if(typeof rt.client.prepare_profile_cache_readiness!=='function')throw Error('unavailable');
            const original={original:rt.client,status:Object.freeze({...status}),resource:rt.client.prepare_profile_cache_readiness(status.handle,status.generation,status.principal),negative:false,watch:null as Promise<void>|null};
            original.resource.ensure_current(rt.client);rt.profileCache=original;
            const invalidate=()=>{original.negative=true;original.resource.cancel();if(!rt.disposed&&rt.profileCache===original&&rt.client===original.original){
              const frame:ProfileCacheInvalidation={version:1,profileCacheInvalidated:{handle:original.status.handle,generation:original.status.generation,owner:original.status.principal}};rt.endpoint.postMessage(frame);
            }};
            // Negative only; an exception refuses views, never proves drain.
            original.watch=original.resource.wait_invalidated().then(invalidate,()=>{invalidate();rt.retiredProfileCaches.add(original);});
          }
          rt.endpoint.postMessage({version:1,id,ok:true,status});
        } finally {if(!consumed)prepared.free();}
      } else if (input.operation === "restore") {
        if(rt.configuration.admission==="fresh_password"||rt.configuration.admission==="existing_key"){fail("unavailable");return;}

        clearClient(rt);
        // Key bytes exist only here and inside Rust; wipe the JS export BEFORE
        // awaiting the shared refresh lock or the credentialed server check.
        const prepared = await consumeWorkerMasterKey(input.key, (bytes) => rt.binding.PreparedBrowserProfile.from_bytes(
          input.profile.principal, bytes, input.profile.encryptedEmail, input.profile.userEmailSalt,
          input.persistence === "persisted"));
        let consumed = false;
        try {
          const admitted = await withAuthRefreshLock(rt.locks, rt.lifetime.signal, async () => {
            consumed = true; // wasm-bindgen consumes this one-use profile, even on failure.
            return rt.binding.BrowserCoreClient.restore(rt.configuration.apiUrl, rt.configuration.appOrigin, rt.configuration.sessionId, prepared);
          });
          if (rt.disposed) { admitted.invalidate(); admitted.free(); return; }
          rt.client = admitted;
        } finally { if (!consumed) prepared.free(); }
        rt.endpoint.postMessage({ version: 1, id, ok: true, status: project(rt, rt.client.admitted_status()) });
      } else if (input.operation === "start_send" || input.operation === "start_new_send") {
        if (!rt.client) { fail("session_expired"); return; }
        const owned = rt.client;
        const authority = project(rt, owned.status(input.handle, input.generation));
        const releaseDriver=retainOriginalClient(rt, owned);
        try {
          let started: OwnedSendOperation | null = null;
          started = new OwnedSendOperation(owned, authority, input.operation==="start_new_send"?null:input.chatId, input.text,
            operation => runClientPhase(rt, owned,operation), () => {
              if (rt.sending === started && started?.failed) {
                rt.sending = null;
                if (rt.client === owned) rt.client = null;
              }
              releaseDriver();
            });
          rt.sending = started;
        } catch (error) { releaseDriver();throw error; }
        rt.endpoint.postMessage({ version: 1, id, ok: true, status: authority,
          send: { operationId: rt.sending.operationId, kind: "started" } });
      } else if(input.operation==="rotate_credentials"){
        if(!rt.client){fail("session_expired");return;}
        const owned=rt.client;project(rt, owned.status(input.handle,input.generation));rt.reading=owned;
        let count=0,operationId:string|null=null;
        const current=()=>{if(rt.disposed||rt.client!==owned||rt.lifetime.signal.aborted)throw Error("session_expired");};
        try{
          const encoded=await withAuthRefreshLock(rt.locks,rt.lifetime.signal,async()=>{
            current();
            return await owned.rotate_credentials(input.handle,input.generation,JSON.stringify(input.scope),async(encoded:string)=>{
              current();if(rt.casReply||typeof encoded!=="string"||new TextEncoder().encode(encoded).byteLength+1024>16*1024)throw "invalid_request";
              const hostEffect:unknown=JSON.parse(encoded),message:unknown={version:1,id,effectId:++count,hostEffect};
              if(!validCredentialEffectMessage(message)||operationId!==null&&operationId!==message.hostEffect.operationId)throw "invalid_request";
              operationId=message.hostEffect.operationId;
              // Do not abort-reject before host true-terminal IO reply: the
              // Worker lock must outlive a still-committing Page transaction.
              return await new Promise<string>((resolve,reject)=>{rt.casReply={id,effectId:count,operationId:operationId!,resolve,reject};rt.endpoint.postMessage(message);});
            });
          },{current});
          current();if(typeof encoded!=="string"||new TextEncoder().encode(encoded).byteLength>4096)throw "invalid_request";
          const credentialCas:unknown=JSON.parse(encoded);
          if(!validCredentialCasValidation(credentialCas)||credentialCas.operationId!==operationId
            ||credentialCas.scope.lifecycleGeneration!==input.scope.lifecycleGeneration||credentialCas.scope.workspaceEpoch!==input.scope.workspaceEpoch)throw "session_expired";
          rt.endpoint.postMessage({version:1,id,ok:true,status:project(rt, owned.status(input.handle,input.generation)),credentialCas});
        }finally{rt.reading=null;retireOriginalClient(rt, owned);}
      } else if (input.operation === "prepare_credentials" || input.operation === "validate_credentials") {
        if(!rt.client){fail("session_expired");return;}
        const owned=rt.client;project(rt, owned.status(input.handle,input.generation));rt.reading=owned;
        let encoded:string;
        try{encoded=await withAuthRefreshLock(rt.locks,rt.lifetime.signal,async()=> input.operation==="prepare_credentials"
          ?await owned.prepare_credentials(input.handle,input.generation)
          :await owned.validate_credentials(input.handle,input.generation,JSON.stringify(input.snapshot)));}
        finally{rt.reading=null;retireOriginalClient(rt, owned);}
        if(rt.disposed)return;
        if(typeof encoded!=="string"||new TextEncoder().encode(encoded).byteLength>16*1024)throw Error("unavailable");
        const snapshot:unknown=JSON.parse(encoded);
        const authority=project(rt, owned.status(input.handle,input.generation));
        if(!validBrowserSealedCredentials(snapshot)||snapshot.owner!==authority.principal||snapshot.generation!==authority.generation
          ||snapshot.apiEndpoint!==rt.configuration.apiUrl||snapshot.appOrigin!==rt.configuration.appOrigin
          ||input.operation==="validate_credentials"&&JSON.stringify(snapshot)!==JSON.stringify(input.snapshot))throw Error("session_expired");
        rt.endpoint.postMessage({version:1,id,ok:true,status:authority,snapshot});

      } else if(input.operation==='start_cache_monitor'){
        if(!rt.client){fail('session_expired');return;}const owned=rt.client,authority=project(rt, owned.status(input.handle,input.generation));
        if(authority.principal!==input.expectedPrincipal||authority.localReadOnly===true||typeof owned.start_cache_monitor!=='function'||typeof owned.stop_cache_monitor!=='function'){fail('unavailable');return;}
        const previous=rt.cacheMonitor;
        let started:RustCacheMonitor|null=null;
        rt.reading=owned;try{await withAuthRefreshLock(rt.locks,rt.lifetime.signal,async()=>{
          started=await owned.start_cache_monitor!(input.handle,input.generation,input.expectedPrincipal);
        });
          if(rt.disposed||rt.client!==owned)throw Error('session_expired');const status=project(rt, owned.status(input.handle,input.generation));if(status.principal!==input.expectedPrincipal||status.localReadOnly===true)throw Error('session_expired');
          {
            const resource=started as RustCacheMonitor|null;if(!resource||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(resource.id))throw Error('unavailable');
            retireCacheMonitor(rt, previous);const slot:CacheMonitorSlot={status:authority,resource,id:resource.id,handle:input.handle,generation:input.generation,owner:input.expectedPrincipal,waiting:false,retired:false,explicitlyStopped:false};rt.cacheMonitor=slot;started=null;
            rt.endpoint.postMessage({version:1,id,ok:true,status,cacheMonitor:{id:slot.id,state:'started'}});
          }
        }finally{const abandoned=started as RustCacheMonitor|null;if(abandoned){abandoned.close();abandoned.free();}rt.reading=null;retireOriginalClient(rt, owned);}
      } else if(input.operation==='restore_cached_metadata'||input.operation==='read_cached_chat_items'||(input.operation==='read_retained_saved_chat'||input.operation==='read_cold_retained_saved_chat'||input.operation==='read_monitored_retained_saved_chat'||input.operation==='read_cache_monitor_update')){
        if(!rt.client||input.id<=rt.lastCacheReadId){fail('session_expired');return;}rt.lastCacheReadId=input.id;
        const owned=rt.client,authority=project(rt, owned.status(input.handle,input.generation));
        const incoming=input.operation==='read_cache_monitor_update',incomingMonitor=rt.cacheMonitor;
        if(incoming&&incomingMonitor)stoppedOriginalUpdate=()=>!rt.disposed&&rt.client===owned&&incomingMonitor.explicitlyStopped;
        if(incoming&&(!incomingMonitor||incomingMonitor.retired||incomingMonitor.id!==input.monitorId||typeof owned.prepare_cache_monitor_update!=='function')){fail('unavailable');return;}
        const retained=(input.operation==='read_retained_saved_chat'||input.operation==='read_cold_retained_saved_chat'||input.operation==='read_monitored_retained_saved_chat'),ids='chatId' in input?[input.chatId]:input.chatIds;
        if(authority.principal!==input.expectedPrincipal||(retained||incoming)&&authority.localReadOnly===true
          ||input.operation==='restore_cached_metadata'&&typeof owned.restore_cached_metadata!=='function'
          ||input.operation==='read_cached_chat_items'&&typeof owned.read_cached_chat_items!=='function'
          ||input.operation==='read_retained_saved_chat'&&typeof owned.read_retained_saved_chat!=='function'||input.operation==='read_cold_retained_saved_chat'&&typeof owned.prepare_cold_retained_saved_chat!=='function'||input.operation==='read_monitored_retained_saved_chat'&&typeof owned.prepare_monitored_retained_saved_chat!=='function'){fail('unavailable');return;}
        const operation:NonNullable<typeof rt.cacheRead>={id:input.id,live:true,effectId:0,state:{effects:0,rows:new Map()},reply:null,drain:null};
        rt.cacheRead=operation;rt.reading=owned;
        const current=()=>{if(rt.disposed||rt.lifetime.signal.aborted||rt.cacheRead!==operation||!operation.live||rt.client!==owned)throw Error('session_expired');
          const status=project(rt, owned.status(input.handle,input.generation));if(status.principal!==input.expectedPrincipal||(retained||incoming)&&status.localReadOnly===true||incoming&&(rt.cacheMonitor!==incomingMonitor||incomingMonitor?.retired===true))throw Error('session_expired');};
        const effect=(plan:string):Promise<string>=>{
          try{current();if(operation.reply||input.operation==='read_cached_chat_items')throw Error('unavailable');
            advanceBrowserCachePlan(operation.state,plan,{operation:input.operation,owner:input.expectedPrincipal,ids,scope:input.scope});
            const effectId=++operation.effectId;
            return new Promise<string>((resolve,reject)=>{const reply={effectId,resolve,reject};operation.reply=reply;
              try{rt.endpoint.postMessage({version:1,id:input.id,effectId,cacheEffect:plan});}catch{operation.reply=null;reject('unavailable');}}).then(packet=>{current();return packet;});
          }catch{return Promise.reject('unavailable');}
        };
        let encoded:string;let publication:RustCachePublication|null=null;
        const prepareAndDrain=async(prepare:()=>Promise<RustCachePublication>):Promise<string>=>{
          publication=await prepare();current();
          if(operation.reply||!browserCachePlansComplete(operation.state,input.operation,ids)||!publication||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(publication.id))throw Error('unavailable');
          const publicationId=publication.id;
          await new Promise<void>((resolve,reject)=>{operation.drain={publicationId,resolve,reject};
            try{rt.endpoint.postMessage({version:1,id:input.id,cachePrepared:{publicationId}});}catch{operation.drain=null;reject('unavailable');}});
          current();return '';
        };

        try{encoded=await withAuthRefreshLock(rt.locks,rt.lifetime.signal,()=>input.operation==='restore_cached_metadata'
            ?owned.restore_cached_metadata!(input.handle,input.generation,input.expectedPrincipal,JSON.stringify(input.chatIds),JSON.stringify(input.scope),effect)
            :input.operation==='read_cached_chat_items'?owned.read_cached_chat_items!(input.handle,input.generation,input.expectedPrincipal,JSON.stringify(input.chatIds))
            :input.operation==='read_cache_monitor_update'?prepareAndDrain(()=>owned.prepare_cache_monitor_update!(input.handle,input.generation,input.expectedPrincipal,input.monitorId,input.chatId,JSON.stringify(input.selector),JSON.stringify(input.scope),input.nowSeconds,effect))
            :input.operation==='read_retained_saved_chat'?owned.read_retained_saved_chat!(input.handle,input.generation,input.expectedPrincipal,input.chatId,JSON.stringify(input.selector),JSON.stringify(input.scope),effect)
            :prepareAndDrain(()=>(input.operation==='read_cold_retained_saved_chat'?owned.prepare_cold_retained_saved_chat!:owned.prepare_monitored_retained_saved_chat!).call(owned,input.handle,input.generation,input.expectedPrincipal,input.chatId,JSON.stringify(input.selector),JSON.stringify(input.scope),input.nowSeconds,effect)));
          current();if(operation.reply||!browserCachePlansComplete(operation.state,input.operation,ids))throw Error('unavailable');
          // Take AFTER the final lock/await boundary; no await follows release.
          const prepared=publication as RustCachePublication|null;if(prepared)encoded=prepared.take(owned);
        }finally{const prepared=publication as RustCachePublication|null;prepared?.free();operation.live=false;operation.reply?.reject('cancelled');operation.reply=null;operation.drain?.reject('cancelled');operation.drain=null;if(rt.cacheRead===operation)rt.cacheRead=null;
          rt.reading=null;retireOriginalClient(rt, owned);}
        if(rt.disposed)return;const status=project(rt, owned.status(input.handle,input.generation));
        if(rt.client!==owned||status.principal!==input.expectedPrincipal||typeof encoded!=='string'||new TextEncoder().encode(encoded).byteLength+8192>256*1024)throw Error('session_expired');
        const data:unknown=JSON.parse(encoded);
        if(input.operation==='read_cache_monitor_update'){if(!validBrowserIncomingCacheUpdate(data)||data.selected!==null&&data.selected.chat.id!==input.chatId||status.localReadOnly===true)throw 'chat_unavailable';
          rt.endpoint.postMessage({version:1,id:input.id,ok:true,status,cacheMonitorId:input.monitorId,cacheUpdate:data});}
        else if(retained){if(!validBrowserRetainedRead(data)||!retainedKindMatches(input.operation,data)||data.chat.id!==input.chatId||status.localReadOnly===true)throw 'chat_unavailable';
          rt.endpoint.postMessage({version:1,id:input.id,ok:true,status,retainedRead:data});}
        else{if(!validBrowserCachedMetadataRead(data)||data.metadataRestored!==(input.operation==='restore_cached_metadata')
            ||data.items.length!==ids.length||data.items.some(row=>!ids.includes(row.id)))throw 'chat_unavailable';
          rt.endpoint.postMessage({version:1,id:input.id,ok:true,status,cachedMetadata:data});}
      } else if ((input.operation === "read_local_saved_chat_cursor"||input.operation==="read_local_checkpoint_summary")) {
        if(!rt.client||input.id<=rt.lastLocalReadId){fail("session_expired");return;}
        rt.lastLocalReadId=input.id;
        const owned=rt.client, authority=project(rt, owned.status(input.handle,input.generation));
        if(rt.configuration.admission!=="existing_key"||authority.localReadOnly!==true||authority.persistence!=="memory_only"
          ||input.expectedPrincipal!==rt.configuration.expectedPrincipal||authority.principal!==input.expectedPrincipal
          ||(input.operation==="read_local_checkpoint_summary"?typeof owned.read_local_checkpoint_summary!=="function":typeof owned.read_local_saved_chat_cursor!=="function")){fail("unavailable");return;}
        const operation:NonNullable<typeof rt.localRead>={planState:{effects:0,payloadRows:0},id:input.id,live:true,effectId:0,reply:null};
        rt.localRead=operation;rt.reading=owned;
        const current=()=>{
          if(rt.disposed||rt.lifetime.signal.aborted||rt.localRead!==operation||!operation.live||rt.client!==owned)throw Error("session_expired");
          const status=project(rt, owned.status(input.handle,input.generation));
          if(status.principal!==input.expectedPrincipal||status.localReadOnly!==true||status.persistence!=="memory_only")throw Error("session_expired");
        };
        const effect=(encoded:string):Promise<string>=>{
          try{
            current();const plan=parseBrowserLocalReadPlan(encoded);
            if(operation.reply||operation.operationId!==undefined&&operation.operationId!==plan.operationId
              ||plan.owner!==input.expectedPrincipal||plan.chatId!==input.chatId)throw Error("unavailable");
            operation.planState=advanceLocalReadPlan(operation.planState,plan,input.operation==="read_local_checkpoint_summary"?{direction:"checkpoint_summary",checkpointId:input.checkpointId}:input.selector);
            operation.operationId=plan.operationId;const effectId=++operation.effectId;
            return new Promise<string>((resolve,reject)=>{
              const reply={effectId,operationId:plan.operationId,maxBytes:plan.maxPacketBytes,resolve,reject};operation.reply=reply;
              try{rt.endpoint.postMessage({version:1,id:input.id,effectId,localReadEffect:plan});}
              catch{if(operation.reply===reply)operation.reply=null;reject("unavailable");}
            }).then(packet=>{current();return packet;});
          }catch{return Promise.reject("unavailable");}
        };
        let encoded:string;
        try{encoded=await withAuthRefreshLock(rt.locks,rt.lifetime.signal,()=>input.operation==="read_local_checkpoint_summary"?owned.read_local_checkpoint_summary!(input.handle,input.generation,input.expectedPrincipal,input.chatId,input.checkpointId,effect):owned.read_local_saved_chat_cursor!(
          input.handle,input.generation,input.expectedPrincipal,input.chatId,JSON.stringify(input.selector),effect));current();if(operation.reply||operation.planState.effects<(input.operation==="read_local_checkpoint_summary"?1:input.selector.direction==="around"?2:1))throw Error("unavailable");}
        finally{operation.live=false;operation.reply?.reject("cancelled");operation.reply=null;if(rt.localRead===operation)rt.localRead=null;
          rt.reading=null;retireOriginalClient(rt, owned);}
        if(rt.disposed)return;
        const status=project(rt, owned.status(input.handle,input.generation));
        if(rt.client!==owned||status.principal!==input.expectedPrincipal||status.localReadOnly!==true||status.persistence!=="memory_only"
          ||typeof encoded!=="string"||new TextEncoder().encode(encoded).byteLength+8192>256*1024)throw Error("session_expired");
        if(input.operation==="read_local_checkpoint_summary"){
          const checkpointRead:unknown=JSON.parse(encoded);
          if(!validCheckpointPresentation(checkpointRead,input.chatId,"retained_selected")||checkpointRead.checkpoint!==null&&checkpointRead.checkpoint.id!==input.checkpointId)throw "chat_unavailable";
          rt.endpoint.postMessage({version:1,id:input.id,ok:true,status,checkpointRead});return;
        }
        const localReadback:unknown=JSON.parse(encoded);
        if(!validLocalRead(localReadback,true)||localReadback.chat.id!==input.chatId)throw "chat_unavailable";
        rt.endpoint.postMessage({version:1,id:input.id,ok:true,status,localRead:localReadback});
      } else if (input.operation === "read_local_chat" || input.operation === "read_local_saved_chat") {
        if (!rt.client) { fail("session_expired"); return; }
        const owned = rt.client;
        const authority = project(rt, owned.status(input.handle,input.generation));
        if (rt.configuration.admission !== "existing_key" || authority.localReadOnly !== true
          || input.expectedPrincipal !== rt.configuration.expectedPrincipal || input.expectedPrincipal !== authority.principal
          || typeof owned.read_local_chat !== "function") { fail("unavailable"); return; }
        rt.reading = owned;
        let encoded: string;
        try { encoded = await withAuthRefreshLock(rt.locks,rt.lifetime.signal,()=>
          owned.read_local_chat!(input.handle,input.generation,input.expectedPrincipal,input.chatId,
            JSON.stringify(input.encryptedRows),input.operation === "read_local_saved_chat")); }
        finally { rt.reading=null;retireOriginalClient(rt, owned); }
        if(rt.disposed)return;
        const current=project(rt, owned.status(input.handle,input.generation));
        if(rt.client!==owned||current.localReadOnly!==true||current.principal!==input.expectedPrincipal
          || typeof encoded!=="string" || new TextEncoder().encode(encoded).byteLength+8192>256*1024) throw Error("session_expired");
        const localRead:unknown=JSON.parse(encoded);
        if(!validLocalRead(localRead,input.operation==="read_local_saved_chat")||localRead.chat.id!==input.chatId)throw Error("chat_unavailable");
        rt.endpoint.postMessage({version:1,id,ok:true,status:current,localRead});
      } else if (input.operation === "read_saved_chat" || input.operation === "read_saved_chat_page") {
        if (!rt.client) { fail("session_expired"); return; }
        const owned = rt.client;
        const authority=project(rt, owned.status(input.handle,input.generation));
        if(input.operation==="read_saved_chat_page"&&(authority.localReadOnly===true||typeof owned.read_saved_chat_page!=="function")){fail("unavailable");return;}
        rt.reading = owned;
        let encoded: string;
        try { encoded = await withAuthRefreshLock(rt.locks, rt.lifetime.signal,
          () => input.operation==="read_saved_chat_page"?owned.read_saved_chat_page!(input.handle,input.generation,input.chatId,JSON.stringify(input.selector)):
            owned.read_saved_chat(input.handle, input.generation, input.chatId)); }
        finally {
          rt.reading = null;
          retireOriginalClient(rt, owned);
        }
        if (rt.disposed) return;
        if (typeof encoded !== "string" || encoded.length + 8192 > 256 * 1024
          || new TextEncoder().encode(encoded).byteLength + 8192 > 256 * 1024) throw new Error("unavailable");
        const savedRead: unknown = JSON.parse(encoded);
        if (!validSavedRead(savedRead) || savedRead.chat.id !== input.chatId) throw new Error("unavailable");
        rt.endpoint.postMessage({ version: 1, id, ok: true,
          status: project(rt, owned.status(input.handle, input.generation)), savedRead });
      } else if ((input.operation === "open_chat" || input.operation === "reconnect_chat")) {
        if (!rt.client) { fail("session_expired"); return; }
        const owned = rt.client;
        // Rust repeats this fence around its awaited shared SDK operation.
        project(rt, owned.status(input.handle, input.generation));
        rt.reading = owned;
        let chat: unknown;
        try { chat = await withAuthRefreshLock(rt.locks, rt.lifetime.signal,
          () => input.operation === "reconnect_chat"
            ? owned.reconnect_chat(input.handle, input.generation, input.chatId)
            : owned.open_chat(input.handle, input.generation, input.chatId)); }
        finally {
          rt.reading = null;
          retireOriginalClient(rt, owned);
        }
        if (rt.disposed) return;
        if (!validChat(chat) || chat.id !== input.chatId) throw new Error("unavailable");
        rt.endpoint.postMessage({ version: 1, id, ok: true,
          status: project(rt, owned.status(input.handle, input.generation)),
          chat: { id: chat.id, title: chat.title, historyComplete: chat.historyComplete, piiRestoration: chat.piiRestoration,
            hasMoreBefore: chat.hasMoreBefore, hasMoreAfter: chat.hasMoreAfter, messages: chat.messages.map(row => ({ id: row.id, role: row.role, content: row.content })) } });
      } else {
        if (!rt.client) { fail("session_expired"); return; }
        rt.endpoint.postMessage({ version: 1, id, ok: true, status: project(rt, rt.client.status(input.handle, input.generation)) });
      }
    } catch (error) {
      // Never stringify/forward Rust/JS errors, metadata, URLs or server replies.
      if(input.operation==="rotate_credentials"&&error==="credential_conflict"){fail("credential_conflict");return;}
      // Exact original-resource stop is a negative cancellation, not admission.
      // The final original Rust take is withheld; retain the existing Client so
      // this cancelled A cannot tear down unrelated state or a later B.
      if(input.operation==='read_cache_monitor_update'&&stoppedOriginalUpdate?.()){fail('session_expired');return;}
      clearClient(rt);clearExistingKeyRequest(input);
      if(input.operation==='check_first_session'||input.operation==='check_first_session_data'){fail(rt.firstSessionTask?.stopped?'cancelled':'unavailable');return;}
      if(input.operation==="restore_existing"){fail("unavailable");return;}
      if (input.operation==="login_password") {
        clearPasswordRequest(input);
        fail(error==="two_factor_required"?"two_factor_required":"authentication_failed");return;
      }
      fail(input.operation === "restore" ? "reauthentication_required" : (input.operation === "open_chat" || input.operation === "reconnect_chat" || input.operation === "read_saved_chat" || input.operation === "read_saved_chat_page" || input.operation === "read_local_saved_chat_cursor" || input.operation === "read_local_checkpoint_summary" || input.operation === "read_retained_saved_chat" || input.operation === "restore_cached_metadata" || input.operation === "read_cached_chat_items") && error === "chat_unavailable" ? "chat_unavailable" : "session_expired");
    } finally { rt.busy = false; }
  };

