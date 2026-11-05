// Owned cache read driver of the Rust core Worker dispatcher.
import type { BrowserCacheSelected } from './browserCacheProtocol';
import { advanceBrowserCachePlan,browserCachePlansComplete,validBrowserCacheSelected,validBrowserCacheSourceEvidence,validBrowserRetainedRead } from './browserCacheProtocol';
import { OwnedMainMetadataStore } from './mainMetadataStoreOperation';
import { beginOwnedLocalRead,completeOwnedLocalRead,createOwnedLocalReadState,ownedLocalReadFallbackReady,ownedLocalReadReady } from './ownedLocalReadProtocol';
import { MAX_PENDING_REQUESTS } from "./protocol";
import { OwnedRecoveredReplyStore } from './recoveredReplyStoreOperation';
import { OwnedRecoveryFinalization } from './recoveryFinalizationOperation';
import type { WorkerRuntimeState } from "./workerRuntimeState";
import { noOwnedDriver,ownedIdentity,project,retainOriginalClient,runClientPhase } from "./workerRuntimeState";
import type { OwnedCacheRequest,OwnedCacheSlot,RustOwnedCacheHandle,RustOwnedCacheTerminal } from "./workerRuntimeTypes";

/** Owned cache read driver of the Rust core Worker dispatcher. */
export const runOwnedCacheRead = async (rt: WorkerRuntimeState, input:OwnedCacheRequest, fail:(error:'unavailable'|'session_expired')=>void) => {
    const owned=rt.client;
    if(!owned||rt.busy||rt.cacheRead||input.id<=rt.lastCacheReadId||rt.ownedCacheReads.size>=MAX_PENDING_REQUESTS){fail('unavailable');noOwnedDriver(rt, input);return;}
    const incoming=input.operation==='read_cache_monitor_update',monitor=incoming?rt.cacheMonitor:null;
    if(incoming&&(!monitor||monitor.retired||monitor.id!==input.monitorId||monitor.handle!==input.handle||monitor.generation!==input.generation||monitor.owner!==input.expectedPrincipal)){fail('unavailable');noOwnedDriver(rt, input);return;}
    rt.lastCacheReadId=input.id;
    const slot:OwnedCacheSlot={id:input.id,original:owned,monitor,live:true,stopped:false,effectId:0,state:{effects:0,rows:new Map()},...((input.localFirst||input.profileCache)?{localRead:createOwnedLocalReadState()}:{}),absence:null,control:null,continuation:null,heldDriver:null,inventory:null,recovery:null,recoveryControl:null,finalization:null,mainMetadata:null,replyStore:null,retainedRecoveries:[],reply:null,drain:null,identity:ownedIdentity(rt, input),terminalRequired:input.ownedCache===true};
    rt.ownedCacheReads.set(input.id,slot);const release=retainOriginalClient(rt, owned);
    let handle:RustOwnedCacheHandle|null=null,continuationWait:Promise<void>|null=null,terminal:RustOwnedCacheTerminal|null=null,observedAbsence=false;
    const current=()=>{if(rt.disposed||rt.client!==owned||!slot.live||slot.stopped||slot.monitor?.retired)throw Error('session_expired');};
    let draftBudget=false;
    const effect=async(plan:string):Promise<string>=>{
      let terminal!:Promise<string>;
      // The opaque ORIGINAL control rechecks full B row/key/monitor/cursor here,
      // after every scheduling await, immediately before actual plan dispatch.
      // Return from this short phase BEFORE awaiting the actual native IO reply.
      await runClientPhase(rt, owned,async()=>{
        current();slot.control!.ensure_current(owned);
        if(slot.reply||typeof plan!=='string')throw Error('unavailable');
        const parsed=JSON.parse(plan),local=!!slot.localRead&&!slot.localFallback&&['owned_metadata','messages'].includes(parsed?.kind)&&!Object.hasOwn(parsed,'stores');
        if(local){if(draftBudget)throw Error('unavailable');beginOwnedLocalRead(slot.localRead!,plan,{owner:input.expectedPrincipal,chatId:input.chatId});}
        else{if(input.profileCache)throw Error('unavailable');if(slot.localRead&&!slot.localFallback){if(!ownedLocalReadFallbackReady(slot.localRead))throw Error('unavailable');slot.localFallback=true;}
          advanceBrowserCachePlan(slot.state,plan,{operation:'read_owned_selected_message_cache',owner:input.expectedPrincipal,ids:[input.chatId],scope:input.scope});}
        const effectId=++slot.effectId;
        terminal=new Promise<string>((resolve,reject)=>{slot.reply={effectId,...(draftBudget?{draftBudget:true as const}:{}),resolve,reject};});
        slot.control!.ensure_current(owned);current();
        rt.endpoint.postMessage({version:1,id:input.id,effectId,cacheEffect:plan,cacheStage:local?'owned_local':'owned_selected',...(draftBudget?{cacheDraftBudget:'original_physical_draft' as const}:{})});
      });
      const packet=await terminal;
      if(slot.localRead&&!slot.localFallback)completeOwnedLocalRead(slot.localRead,packet);
      return packet;
    };
    try{
      // Wait only for the SAME original opaque acquisition/retain. Auth prepare
      // temporarily retires private guards; never turn that latency into a B failure.
      // This wait owns no Client/auth lane and never waits for expanded A metadata.
      const acquisition=rt.initialSync;if(!input.profileCache&&acquisition?.original===owned)await acquisition.ready;
      current();
      handle=await runClientPhase(rt, owned,async()=>{
        current();const originalProfile=input.profileCache?rt.profileCache:null;
        if(input.profileCache&&(!originalProfile||originalProfile.original!==owned||originalProfile.negative||originalProfile.status.handle!==input.handle||originalProfile.status.generation!==input.generation||originalProfile.status.principal!==input.expectedPrincipal||typeof owned.begin_owned_profile_cache_read!=='function'))throw Error('session_expired');
        if(originalProfile)originalProfile.resource.ensure_current(owned);
        const status=originalProfile?originalProfile.status:project(rt, owned.status(input.handle,input.generation));
        if(status.principal!==input.expectedPrincipal||status.localReadOnly===true)throw Error('session_expired');
        const resource=originalProfile?owned.begin_owned_profile_cache_read!(originalProfile.resource,input.handle,input.generation,input.expectedPrincipal,input.chatId,JSON.stringify(input.selector),JSON.stringify(input.scope),input.nowSeconds):incoming?owned.begin_owned_cache_incoming_read!(input.handle,input.generation,input.expectedPrincipal,input.monitorId!,input.chatId,JSON.stringify(input.selector),JSON.stringify(input.scope),input.nowSeconds)
          :(input.localFirst?owned.begin_owned_cache_local_first_read!:owned.begin_owned_cache_cold_read!).call(owned,input.handle,input.generation,input.expectedPrincipal,input.chatId,JSON.stringify(input.selector),JSON.stringify(input.scope),input.nowSeconds);
        try{slot.control=resource.control();if(typeof slot.control.ensure_current!=='function')throw Error('unavailable');slot.control.ensure_current(owned);slot.heldDriver=resource;return resource;}
        catch(error){resource.free();throw error;}
      });
      if(rt.originalRecoveryPort&&!input.profileCache){
        const port=rt.originalRecoveryPort;
        slot.inventory=await runClientPhase(rt, owned,async()=>{current();if(typeof handle!.begin_physical_draft_inventory!=='function')throw Error('unavailable');return handle!.begin_physical_draft_inventory(owned,port);});
        for(;;){
          const phase=slot.inventory.kind;
          if(phase==='original_physical_draft_rows_hydrated'){slot.inventory.free();slot.inventory=null;break;}
          if(phase==='drive')await slot.inventory.drive();
          else if(phase==='apply')await runClientPhase(rt, owned,async()=>{slot.inventory!.apply(owned);});
          else throw Error('unavailable');
        }
      }
      for(;;){
        let step=await handle.next(),consumed=false;
        try{
          if(step.kind==='io'){
            draftBudget=step.uses_original_physical_draft_budget?.()===true;
            consumed=true;
            try{step=await step.execute(effect);consumed=false;}
            catch{slot.control!.cancel();continue;} // Drain the SAME actual future next.
          }
          if(step.kind==='apply'){
            try{await runClientPhase(rt, owned,async()=>{step.apply(owned);});}
            catch{slot.control!.cancel();} // Drop exact phase, then poll actual future.
            continue;
          }
          if(step.kind!=='selected_pending_metadata'||!(slot.localRead&&!slot.localFallback?ownedLocalReadReady(slot.localRead):browserCachePlansComplete(slot.state,'read_owned_selected_message_cache',[input.chatId])))throw Error('unavailable');
          const publicationId=step.id;if(!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(publicationId))throw Error('unavailable');
          current();
          await new Promise<void>(resolve=>{slot.drain={publicationId,resolve};rt.endpoint.postMessage({version:1,id:input.id,cachePrepared:{publicationId}});});
          // No plaintext leaves an outer async continuation. Full original check
          // and actual post share ONE synchronous short native Client phase.
          await runClientPhase(rt, owned,async()=>{
            current();slot.control!.ensure_current(owned);
            const encoded=step.take(owned);
            if(typeof encoded!=='string'||new TextEncoder().encode(encoded).byteLength>256*1024)throw Error('unavailable');
            const selected:unknown=JSON.parse(encoded);
            if(!validBrowserRetainedRead(selected)||selected.chat.id!==input.chatId||selected.cacheReadKind!==(slot.localRead&&!slot.localFallback?'local':incoming?'monitor':'cold'))throw Error('unavailable');
            const sourceEvidence=selected.cacheReadKind==='local'?null:{packetStamp:step.authenticated_source_stamp(owned),messagesVersion:step.authenticated_messages_version(owned)??null};
            if(sourceEvidence!==null&&!validBrowserCacheSourceEvidence(sourceEvidence))throw Error('unavailable');
            const originalProfile=input.profileCache?rt.profileCache:null;
            if(input.profileCache&&(!originalProfile||originalProfile.original!==owned||originalProfile.negative))throw Error('session_expired');
            if(originalProfile)originalProfile.resource.ensure_current(owned);
            // DATA identity from the actual original restore; authority is the
            // exact readiness/control + native profile checks, never this label.
            const status=originalProfile?originalProfile.status:project(rt, owned.status(input.handle,input.generation));
            if(status.principal!==input.expectedPrincipal||status.localReadOnly===true)throw Error('session_expired');
            if(!incoming){
              step.finish_cold(owned);current();
              rt.endpoint.postMessage({version:1,id:input.id,ok:true,status,retainedRead:selected,...(sourceEvidence?{cacheSourceEvidence:sourceEvidence}:{})});
            }else{
              const continuation=step.pending_metadata(owned);slot.continuation=continuation;
              if(continuation.id!==publicationId||continuation.kind!=='original_hint_metadata')throw Error('unavailable');
              const progress:BrowserCacheSelected={version:1,id:input.id,cacheSelected:{publicationId,selected,pending:'metadata',sourceEvidence:sourceEvidence!}};
              if(!validBrowserCacheSelected(progress))throw Error('unavailable');
              current();continuation.ensure_current(owned);
              rt.endpoint.postMessage(progress);
            }
          });
          if(!incoming)return;
          // This opt-in foreground choice only schedules the SAME sealed
          // metadata remainder. Rust remains sole recovery/crypto/receipt policy.
          if(rt.originalRecoveryPort&&rt.foregroundRecoveryClient===owned){
            const port=rt.originalRecoveryPort;
            // Selected view is already posted. Core selects only the original
            // hint's bounded working set; never enumerate all local chats here.
            for(;;){
              slot.inventory=await runClientPhase(rt, owned,async()=>{current();if(typeof slot.continuation!.begin_next_physical_draft_inventory!=='function')throw Error('unavailable');return slot.continuation!.begin_next_physical_draft_inventory(owned,port)??null;});
              if(!slot.inventory)break;
              for(;;){
                const phase=slot.inventory.kind;
                if(phase==='original_physical_draft_rows_hydrated'){slot.inventory.free();slot.inventory=null;break;}
                if(phase==='drive')await slot.inventory.drive();
                else if(phase==='apply')await runClientPhase(rt, owned,async()=>{slot.inventory!.apply(owned);});
                else throw Error('unavailable');
              }
            }

            const previousHandle=handle;
            handle=await runClientPhase(rt, owned,async()=>{current();return slot.continuation!.begin_metadata(owned);});
            slot.heldDriver=handle;previousHandle?.free();
            slot.state={effects:0,rows:new Map()};
            const metadataEffect=async(plan:string):Promise<string>=>{
              let terminal!:Promise<string>;
              await runClientPhase(rt, owned,async()=>{
                current();slot.control!.ensure_current(owned);
                if(slot.reply||typeof plan!=='string')throw Error('unavailable');
                advanceBrowserCachePlan(slot.state,plan,{operation:input.operation,owner:input.expectedPrincipal,ids:[input.chatId],scope:input.scope});
                const effectId=++slot.effectId;
                terminal=new Promise<string>((resolve,reject)=>{slot.reply={effectId,...(draftBudget?{draftBudget:true as const}:{}),resolve,reject};});
                current();rt.endpoint.postMessage({version:1,id:input.id,effectId,cacheEffect:plan,...(draftBudget?{cacheDraftBudget:'original_physical_draft' as const}:{})});
              });
              return await terminal;
            };
            for(;;){
              let metadataStep=await handle.next(),used=false;
              try{
                if(metadataStep.kind==='io'){draftBudget=metadataStep.uses_original_physical_draft_budget?.()===true;used=true;metadataStep=await metadataStep.execute(metadataEffect);used=false;}
                // Exact typed Apply owns matched header/auth bookkeeping before its
                // original negative refusal; a stopped slot adds no pre-gate.
                if(metadataStep.kind==='apply'){await runClientPhase(rt, owned,async()=>{metadataStep.apply(owned);});continue;}
                if(metadataStep.kind!=='metadata_pending_remainder')throw Error('unavailable');
                const publicationId=metadataStep.id;
                await new Promise<void>(resolve=>{slot.drain={publicationId,resolve};rt.endpoint.postMessage({version:1,id:input.id,cachePrepared:{publicationId}});});
                await runClientPhase(rt, owned,async()=>{
                  current();metadataStep.take(owned);
                  const previous=slot.continuation;slot.continuation=metadataStep.pending_remainder(owned);previous?.free();

                });
                break;
              }finally{if(!used)metadataStep.free();}
            }
            // The Page's SAME pending RPC stays owned. Core retains each
            // distinct immutable later hint and bounds admissions; this adapter
            // never resolves/ACKs old facets or manufactures a terminal.
            for(;;){
              slot.recovery=await runClientPhase(rt, owned,async()=>{current();return slot.continuation!.begin_next_recovery(owned,port)??null;});
              if(!slot.recovery){
                if(typeof slot.continuation!.wait_recovery_work!=='function')throw Error('unavailable');
                continuationWait=slot.continuation!.wait_recovery_work();
                await continuationWait;continuationWait=null;
                continue; // Capture only actual newly pending work in Core.
              }
              slot.recoveryControl=slot.recovery.control();
              const recovery=slot.recovery;
              const detached=new Set(['next','io','checkpoint_ready','checkpoint_read','checkpoint_crypto','checkpoint_write','checkpoint_readback_crypto']);
              for(;;){
                const phase=recovery.kind;
                if(['recovery_pending_local_persistence','deferred','retained_failure','refused'].includes(phase))break;
                if(detached.has(phase))await recovery.drive();
                // Core Apply performs mandatory original control-plane drain first.
                else await runClientPhase(rt, owned,async()=>{recovery.apply(owned);});
              }
              if(recovery.kind==='recovery_pending_local_persistence')await runClientPhase(rt, owned,async()=>{current();recovery.ensure_current(owned);current();rt.endpoint.postMessage({version:1,id:input.id,cacheRecoveryProgress:'local_persistence_pending'});});
              if(recovery.kind==='recovery_pending_local_persistence'&&recovery.job_kind==='main'){
                // Original Core offer selects the facet; Core still validates
                // SAME Main Progress/Master/store/checkpoint independently.
                slot.mainMetadata=new OwnedMainMetadataStore(owned,recovery,slot.recoveryControl,
                  operation=>runClientPhase(rt, owned,operation),current);
                await slot.mainMetadata.run();
                await runClientPhase(rt, owned,async()=>{current();slot.mainMetadata!.ensure_current();current();rt.endpoint.postMessage({version:1,id:input.id,cacheRecoveryProgress:'main_metadata_stored_pending'});});
                slot.replyStore=new OwnedRecoveredReplyStore(owned,recovery,slot.mainMetadata,slot.recoveryControl,
                  operation=>runClientPhase(rt, owned,operation),current);
                await slot.replyStore.run();
                await runClientPhase(rt, owned,async()=>{current();slot.replyStore!.ensure_current();current();rt.endpoint.postMessage({version:1,id:input.id,cacheRecoveryProgress:'main_reply_stored_pending'});});
                // This partial facet never retires Main or its journal.
              }else if(recovery.kind==='recovery_pending_local_persistence'){
                if(recovery.job_kind!=='metadata')throw Error('unavailable');
                // Capture only from the SAME actual Rust Progress and Client.
                // Keep this operation in the original slot BEFORE any await.
                slot.finalization=new OwnedRecoveryFinalization(owned,recovery,slot.recoveryControl,
                  operation=>runClientPhase(rt, owned,operation),current);
                await slot.finalization.run();
                await runClientPhase(rt, owned,async()=>{current();slot.finalization!.ensure_current();current();rt.endpoint.postMessage({version:1,id:input.id,cacheRecoveryProgress:'local_metadata_stored'});});
                // The source/remainder stays pending. No whole-hint ACK or
                // publication follows this native local persistence operation.
              }
              if(!['recovery_pending_local_persistence','deferred'].includes(recovery.kind)){
                // Unknown/failure owns its original resources; do not retry,
                // retire it, or allow a later attempt to bypass its actual IO.
                continuationWait=slot.recoveryControl.wait_cancelled();
                await continuationWait;continuationWait=null;throw Error('cancelled');
              }
              // Hold exact original result/checkpoint/durability resources while
              // Core permits another genuine job. Core's bound is four attempts
              // and four later whole hints; only one recovery IO runs at a time.
              slot.retainedRecoveries.push({resource:recovery,control:slot.recoveryControl,finalization:slot.finalization,mainMetadata:slot.mainMetadata,replyStore:slot.replyStore,codeEmbed:null});
              slot.recovery=null;slot.recoveryControl=null;slot.finalization=null;slot.mainMetadata=null;slot.replyStore=null;
            }
          }
          continuationWait=slot.recovery?slot.recoveryControl!.wait_cancelled():slot.continuation!.wait_cancelled();await continuationWait;continuationWait=null;
          throw Error('cancelled');
        }finally{if(!consumed)step.free();}
      }
    }catch{
      // A failed/retired B read owns no parent/session retirement authority.
      // Existing native root/parent/master/denial guards still refuse every
      // operation/output; actual global disposal remains authoritative.
      if(input.profileCache&&handle&&typeof handle.take_profile_cache_absence==='function'){
        try{await runClientPhase(rt, owned,async()=>{
          current();const original=rt.profileCache;if(!original||original.original!==owned||original.negative)throw Error('session_expired');
          original.resource.ensure_current(owned);
          slot.absence=handle!.take_profile_cache_absence!(owned);slot.absence.ensure_current(owned);slot.absence.consume(owned);
          observedAbsence=true;
        });}catch{/* No absence from error labels, cancellation, Drop or unknown IO. */}
      }
      if(!observedAbsence)fail('unavailable');
    }finally{
      // Settlement runs in a nested function so its early returns do not
      // override the try/catch completion (no-unsafe-finally); try/catch never throws.
      const settle=async():Promise<void>=>{
      slot.control?.cancel();
      if(continuationWait){slot.continuation?.cancel();await continuationWait.catch(()=>{});}
      if(slot.continuation){slot.continuation.close();slot.continuation.free();slot.continuation=null;}
      if(slot.inventory){
        // The opaque actual consumer retains its exact native/crypto resources.
        // Failure/drop/status is never a drain or permission to rearm its row.
        if(!rt.disposed)rt.endpoint.postMessage({version:1,id:input.id,cacheTerminal:slot.identity,state:'unsettled'});return;
      }
      if(slot.mainMetadata||slot.retainedRecoveries.some(value=>value.mainMetadata!==null)){
        // Even native metadata success is partial DATA. Retain SAME Main
        // Progress/store/result/journal on cancellation/error/normal teardown;
        // only a separately proved transcript coordinator may retire them.
        if(!rt.disposed)rt.endpoint.postMessage({version:1,id:input.id,cacheTerminal:slot.identity,state:'unsettled'});return;
      }
      if(slot.finalization&&!slot.finalization.nativeIoQuiescent()
        ||slot.retainedRecoveries.some(value=>value.finalization&&!value.finalization.nativeIoQuiescent())){
        // Failure/cancellation/unknown never frees original Rust finalizer IO.
        // Retain the whole slot until global Page/native close and termination.
        if(!rt.disposed)rt.endpoint.postMessage({version:1,id:input.id,cacheTerminal:slot.identity,state:'unsettled'});return;
      }
      if(slot.terminalRequired&&handle){try{terminal=handle.terminal?.()??null;}catch{/* No private/terminal authority from an arbitrary binding error. */}}
      if(slot.terminalRequired&&handle&&(!terminal||!terminal.is_quiescent())){
        // The original slot strongly retains heldDriver/control; skipping
        // .free alone would allow wasm-bindgen finalization after this return.
        // Unknown native quiescence is a transport failure, never an ordinary
        // B completion. Retain its actual resources until global Page drain
        // and Worker termination; do not falsely report Client/driver free.
        terminal?.free();
        if(!rt.disposed)rt.endpoint.postMessage({version:1,id:input.id,cacheTerminal:slot.identity,state:'unsettled'});
        return;
      }
      if(slot.recovery){try{slot.recovery.retire();slot.finalization?.releaseAfterRecoveryRetired();slot.finalization=null;slot.recovery.free();slot.recovery=null;slot.recoveryControl?.free();slot.recoveryControl=null;}catch{terminal?.free();if(!rt.disposed)rt.endpoint.postMessage({version:1,id:input.id,cacheTerminal:slot.identity,state:'unsettled'});return;}}
      while(slot.retainedRecoveries.length){const retained=slot.retainedRecoveries[0];try{retained.resource.retire();retained.finalization?.releaseAfterRecoveryRetired();slot.retainedRecoveries.shift();retained.resource.free();retained.control.free();}catch{terminal?.free();if(!rt.disposed)rt.endpoint.postMessage({version:1,id:input.id,cacheTerminal:slot.identity,state:'unsettled'});return;}}
      terminal?.free();slot.absence?.free();slot.absence=null;handle?.free();slot.heldDriver=null;slot.control?.free();slot.control=null;slot.live=false;
      rt.ownedCacheReads.delete(input.id);release();
      if(observedAbsence&&!rt.disposed)rt.endpoint.postMessage({version:1,id:input.id,ok:false,error:'chat_unavailable',profileCacheAbsent:true});
      if(slot.terminalRequired&&!rt.disposed)rt.endpoint.postMessage({version:1,id:input.id,cacheTerminal:slot.identity,state:'drained'});
      if(rt.disposed&&rt.ownedCacheReads.size===0)rt.endpoint.removeEventListener('message',rt.receiveListener);
      };
      await settle();
    }
  };

