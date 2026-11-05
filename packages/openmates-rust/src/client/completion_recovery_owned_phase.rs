//! One-use Client Apply / detached IO / matching Resume resources. The shared
//! policy future owns no Client; no Apply method is async or performs network IO.
use super::*;
use super::super::phase_runtime::{RecoveryChecks,RecoveryConnected,RecoveryCrypto,RecoveryFuture,RecoveryPhases};
use super::super::super::{auth::{PreparedOwnedSessionValidation,OwnedSessionValidationHeaders,OwnedSessionValidationBody,CompletedOwnedSessionValidation,send_owned_session_validation_headers_with_negative,drive_owned_session_validation_body},transport::{OwnedRecoverySocketPreparation,PreparedOwnedRecoverySocket,OwnedConnectedRecoverySocket,OwnedUnannouncedRecoverySocket,PreparedOwnedRecoveryLifecycle,connect_owned_completion_recovery_socket_with_negative,drive_owned_completion_recovery_lifecycle_with_negative,OwnedReadRoute,PreparedOwnedRead,OwnedReadHeaders,OwnedReadBody,CompletedOwnedRead,send_owned_read_headers,drive_owned_read_body}};
use tokio::sync::{mpsc,oneshot};
#[cfg(target_arch="wasm32")]
use super::checkpoint::{prepare_restore,OriginalRecoveryRestorePreparation,OriginalRecoveryRestoreReadiness,OriginalRecoveryRestoreRead,OriginalRecoveryRestoreReadResult,OriginalRecoveryRestoreCrypto,OriginalRecoveryRestoreDecoded};
use super::super::super::sync::canonical_owned::{OwnedCanonicalChatDriver,OwnedCanonicalChatStep,OriginalCanonicalChatReadResult};

#[cfg(test)]
struct CloseGate {entered:oneshot::Sender<()>,release:oneshot::Receiver<()>}
struct Run {
    #[cfg(test)] close_gate:Mutex<Option<CloseGate>>,
    #[cfg(target_arch="wasm32")] checkpoint_port:Option<crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort>,
    terminal_socket:tokio::sync::Mutex<Option<Socket>>,
    original:Arc<OwnedRecoveryContext>,request:CancellationToken,storage:Option<Arc<OriginalRecoveryStorageProof>>,artifacts:Mutex<Option<OwnedRecoveryArtifacts>>,lease_deadline:Mutex<Option<u64>>,
}
impl Run {
    // Registration precedes the actual detached await. Unknown/failed/abandoned
    // close keeps this same socket in Run and never releases active occupancy.
    async fn close_outcome_socket(&self,socket:Socket)->Result<()> {
        let mut retained=self.terminal_socket.lock().await;
        if retained.is_some(){return Err(Error::Conflict)}
        *retained=Some(socket);
        #[cfg(test)]
        {
            // Negative-only scheduler hold around the SAME registered real
            // socket. Releasing this gate supplies no close/settlement result.
            let gate=self.close_gate.lock().map_err(|_|Error::Protocol)?.take();
            if let Some(gate)=gate {
                drop(retained);let _=gate.entered.send(());
                gate.release.await.map_err(|_|Error::Cancelled)?;
                retained=self.terminal_socket.lock().await;
            }
        }
        let actual=retained.as_mut().ok_or(Error::Protocol)?.close(None).await;
        if actual.is_err(){return Err(Error::Offline)}
        retained.take();Ok(())
    }
    async fn finish_stage_outcome(&self,outcome:OriginalForegroundRecoveryAdmission)->Result<OriginalForegroundRecoveryAdmission>{
        match outcome {
            OriginalForegroundRecoveryAdmission::Canonical(mut result)=>{
                let socket=result.owned_socket.take().ok_or(Error::Protocol)?;
                self.close_outcome_socket(socket).await?;
                Ok(OriginalForegroundRecoveryAdmission::Canonical(result))
            }
            OriginalForegroundRecoveryAdmission::DeferredWithSocket(socket)=>{
                self.close_outcome_socket(socket).await?;
                Ok(OriginalForegroundRecoveryAdmission::Deferred)
            }
            value=>Ok(value),
        }
    }
    async fn finish_commit_outcome(&self,mut result:OriginalForegroundRecoveryResult)->Result<OriginalForegroundRecoveryResult>{
        let socket=result.owned_socket.take().ok_or(Error::Protocol)?;
        self.close_outcome_socket(socket).await?;Ok(result)
    }
    fn negative(&self)->Result<()> {
        self.original.check_negative()?;
        self.narrow_negative()
    }
    fn narrow_negative(&self)->Result<()> {
        self.original.handoff.check_original_negative()?;
        self.original.fence.check()?;
        if self.original.cancel.is_cancelled()||self.request.is_cancelled(){return Err(Error::Cancelled)}
        if self.lease_deadline.lock().map_err(|_|Error::Cancelled)?.is_some_and(|at|at<=now_ms()){return Err(Error::Conflict)}
        if let Some(proof)=&self.storage{proof.check_negative()?;}
        Ok(())
    }
    fn check(&self,client:&Client)->Result<()> {self.original.check_root(client)?;self.negative()}
    async fn socket_io<T>(&self,future:impl std::future::Future<Output=Result<T>>)->Result<T>{
        self.negative()?;
        let deadline=*self.lease_deadline.lock().map_err(|_|Error::Cancelled)?;
        let expiry=async move{match deadline {Some(at)=>crate::platform::time::sleep(std::time::Duration::from_millis(at.saturating_sub(now_ms()))).await,None=>std::future::pending::<()>().await}};
        let result=tokio::select!{biased;
            _=self.request.cancelled()=>Err(Error::Cancelled),
            _=self.original.cancel.cancelled()=>Err(Error::Cancelled),
            _=self.original.fence.mode.cancelled()=>Err(Error::Cancelled),
            _=self.original.handoff.cancelled()=>Err(Error::Cancelled),
            _=expiry=>Err(Error::Conflict),
            result=future=>result,
        };
        self.negative()?;result
    }
}
struct CanonicalRun {driver:OwnedCanonicalChatDriver,boundary:Arc<OriginalRecoveryRowBoundary>,job:CompletionRecoveryJob,key:Key}
enum Call {
    #[cfg(target_arch="wasm32")] RestoreBegin,
    #[cfg(target_arch="wasm32")] RestoreReady(OriginalRecoveryRestoreReadiness),
    #[cfg(target_arch="wasm32")] RestoreRead(OriginalRecoveryRestoreReadResult),
    #[cfg(target_arch="wasm32")] RestoreDecoded(OriginalRecoveryRestoreDecoded),
    CanonicalBegin(CompletionRecoveryJob,Key),CanonicalApply(CanonicalRun,OwnedCanonicalChatStep),CanonicalReady(CanonicalRun,OriginalCanonicalChatReadResult),
    Terminal(OriginalForegroundRecoveryResult),
    Fence(CancellationToken),CheckFence(RecoveryFence),Scope(Option<String>),Owner,Team,Api,Master,
    CheckOwner(Box<CompletionRecoveryCheckpoint>,RecoveryFence),Canonical(CompletionRecoveryJob),ObservedCreatedAt(CompletionRecoveryJob),
    Validate,ValidateSocket(OwnedRecoverySocketPreparation),AuthHeaders(OwnedSessionValidationHeaders),AuthBody(CompletedOwnedSessionValidation),
    Metadata(String),ReadHeaders(OwnedReadHeaders),ReadBody(CompletedOwnedRead),
    Capture(String,Value),CacheKey(String,Value,Option<phase_key::SelectedRecoveryWrapper>),Insert(String,Value),
    SocketBegin,SocketUnannounced(OwnedUnannouncedRecoverySocket),SocketConnected(OwnedConnectedRecoverySocket),
    ConnectedCheck(OwnedConnectedRecoverySocket),ConnectedFinish(OwnedConnectedRecoverySocket),
}
enum Reply {#[cfg(target_arch="wasm32")] Checkpoint(Option<CompletionRecoveryCheckpoint>),Unit,Fence(RecoveryFence),Owner(String),CreatedAt(Option<u64>),Team(Option<String>),Api(String),Master(MasterCapability),Value(Option<Value>),SocketPreparation(OwnedRecoverySocketPreparation),Connected(OwnedConnectedRecoverySocket),Socket(Socket),Reconciled(Option<CompletionRecoveryReceipt>)}
struct Envelope {run:Arc<Run>,call:Option<Call>,reply:Option<oneshot::Sender<Result<Reply>>>,socket_preparation:Option<OwnedRecoverySocketPreparation>}
impl Drop for Envelope {fn drop(&mut self){if let Some(reply)=self.reply.take(){self.run.original.cancel.cancel();let _=reply.send(Err(Error::Cancelled));}}}
enum Io {
    #[cfg(target_arch="wasm32")] RestoreReady(OriginalRecoveryRestorePreparation),
    #[cfg(target_arch="wasm32")] RestoreRead(OriginalRecoveryRestoreRead),
    #[cfg(target_arch="wasm32")] RestoreCrypto(OriginalRecoveryRestoreCrypto),
    Canonical(CanonicalRun),
    AuthHeaders(PreparedOwnedSessionValidation),AuthBody(OwnedSessionValidationBody),
    ReadHeaders(PreparedOwnedRead),ReadBody(OwnedReadBody),Connect(PreparedOwnedRecoverySocket),Lifecycle(PreparedOwnedRecoveryLifecycle),
}
enum Next {Reply(Envelope,Result<Reply>),Apply(Envelope),Io(Envelope,Io),Terminal(OriginalForegroundRecoveryResult)}
/// Issued only by the actual shared policy request. No serialized constructor.
pub(in crate::client) struct OwnedRecoveryApply {run:Arc<Run>,sequence:u64,envelope:Option<Envelope>}
/// Contains only prepared actual request/response/socket ownership; no Client.
pub(in crate::client) struct OwnedRecoveryIo {run:Arc<Run>,sequence:u64,envelope:Option<Envelope>,io:Option<Io>}
/// Actual phase completion, matched by same Arc identity and sequence exactly.
pub(in crate::client) struct OwnedRecoveryResume {run:Arc<Run>,sequence:u64,next:Option<Next>}
pub(in crate::client) enum OwnedRecoveryStep {
    Apply(OwnedRecoveryApply),Io(OwnedRecoveryIo),
    Canonical(OriginalForegroundRecoveryResult),PendingPersistence(OwnedRecoveryPendingPersistence),Deferred,
}
enum AlgorithmResult {Stage(OriginalForegroundRecoveryAdmission),Commit(OriginalForegroundRecoveryResult)}
#[cfg(not(target_arch="wasm32"))]
type DriverFuture=std::pin::Pin<Box<dyn std::future::Future<Output=Result<AlgorithmResult>>+Send+'static>>;
#[cfg(target_arch="wasm32")]
type DriverFuture=std::pin::Pin<Box<dyn std::future::Future<Output=Result<AlgorithmResult>>+'static>>;
pub(in crate::client) struct OwnedRecoveryDriver {
    run:Arc<Run>,future:Option<DriverFuture>,receiver:mpsc::Receiver<Envelope>,queued:Option<Next>,
    sequence:u64,outstanding:Option<u64>,finished:bool,
}
#[derive(Clone)]
pub(in crate::client) struct OwnedRecoveryControl {run:Arc<Run>}
impl OwnedRecoveryControl {
    #[cfg(test)]
    pub(in crate::client) fn hold_outcome_close_for_test(&self)->(oneshot::Receiver<()>,oneshot::Sender<()>){
        let(entered,wait)=oneshot::channel();let(release,resume)=oneshot::channel();
        let mut gate=self.run.close_gate.lock().unwrap();assert!(gate.is_none());*gate=Some(CloseGate{entered,release:resume});(wait,release)
    }
    #[cfg(test)]
    pub(in crate::client) async fn outcome_socket_retained_for_test(&self)->bool{self.run.terminal_socket.lock().await.is_some()}
    #[cfg(test)]
    pub(in crate::client) async fn observe_outcome_transport_error_for_test(&self)->Result<()> {
        let mut retained=self.run.terminal_socket.lock().await;
        // The maintained receiver owns this same socket while observing the
        // real peer's EOF/error. The caller's existing ten-second test bound
        // cannot mistake the transport's ninety-second deadline for peer EOF.
        let actual=transport::receive(retained.as_mut().ok_or(Error::Conflict)?).await;
        match actual{Err(Error::Offline)=>Ok(()),_=>Err(Error::Protocol)}
    }
    pub(in crate::client) fn cancel(&self){self.run.original.cancel.cancel();}
    pub(in crate::client) async fn wait_cancelled(&self){tokio::select!{_=self.run.original.cancel.cancelled()=>{},_=self.run.original.handoff.cancelled()=>{},_=self.run.original.fence.mode.cancelled()=>{}}}
}
impl Drop for OwnedRecoveryDriver {fn drop(&mut self){if !self.finished{self.run.original.cancel.cancel();}}}
impl PreparedOwnedRecovery {
    pub(in crate::client) fn into_driver(mut self)->Result<OwnedRecoveryDriver>{
        let context=self.context.take().ok_or(Error::Cancelled)?;
        context.check_negative()?;
        if context.issued.swap(true,Ordering::AcqRel){return Err(Error::Cancelled)}
        // From here the actual driver owns the attempt. Error, cancellation,
        // Drop or an abandoned IO/Apply can no longer release occupancy.
        context.active_permit.activate()?;
        let run=Arc::new(Run{#[cfg(test)] close_gate:Mutex::new(None),#[cfg(target_arch="wasm32")] checkpoint_port:self.checkpoint_port.take(),request:context.cancel.clone(),storage:None,terminal_socket:tokio::sync::Mutex::new(None),artifacts:Mutex::new(None),lease_deadline:Mutex::new(None),original:context});
        let(sender,receiver)=mpsc::channel(1);let runtime_run=run.clone();let saved=self.saved.take();
        let future=Box::pin(async move{
            let job=runtime_run.original.handoff.job().clone();let cancel=runtime_run.request.clone();
            let mut runtime=OwnedRuntime {run:runtime_run.clone(),sender};
            let actual=phase_algorithm::stage(&mut runtime,&job,saved,&cancel).await?;
            runtime_run.finish_stage_outcome(actual).await.map(AlgorithmResult::Stage)
        });
        Ok(OwnedRecoveryDriver{run,future:Some(future),receiver,queued:None,sequence:0,outstanding:None,finished:false})
    }
}
// Only the actual native-delivery receipt CHILD can call this parent-private
// seam. Validation errors return the original Stage before any future starts.
pub(super) struct PreparedOwnedRecoveryCommit {run:Arc<Run>,digest:String}
pub(super) fn prepare_commit_driver(client:&Client,context:Arc<OwnedRecoveryContext>,stage:&CompletionRecoveryStage,storage:Arc<OriginalRecoveryStorageProof>)->Result<PreparedOwnedRecoveryCommit>{
    context.check_row(client)?;stage.fence.check_client(client)?;storage.check_original(client)?;
    if stage.fence.operation!=context.cancel||!same_checkpoint_job(&stage.checkpoint.job,context.handoff.job()){return Err(Error::Cancelled)}
    let digest=stage.checkpoint.digest()?;let deadline=stage.fence.lease_expires_at;let request=context.cancel.child_token();
    let run=Arc::new(Run{#[cfg(test)] close_gate:Mutex::new(None),#[cfg(target_arch="wasm32")] checkpoint_port:None,request,storage:Some(storage),terminal_socket:tokio::sync::Mutex::new(None),artifacts:Mutex::new(None),lease_deadline:Mutex::new(deadline),original:context});
    run.check(client)?;Ok(PreparedOwnedRecoveryCommit{run,digest})
}
impl PreparedOwnedRecoveryCommit {
    pub(super) fn into_driver(self,stage:CompletionRecoveryStage,durable:CompletionRecoveryDurableReceipt)->std::result::Result<OwnedRecoveryDriver,(CompletionRecoveryStage,Error)>{
        let checked=(||{if stage.fence.operation!=self.run.original.cancel||stage.checkpoint.digest()?!=self.digest||durable.checkpoint_sha256!=self.digest{return Err(Error::Conflict)}self.run.narrow_negative()})();
        if let Err(error)=checked{return Err((stage,error))}
        let run=self.run;let(sender,receiver)=mpsc::channel(1);let runtime_run=run.clone();
        let future=Box::pin(async move{let cancel=runtime_run.request.clone();let mut runtime=OwnedRuntime{run:runtime_run.clone(),sender};let actual=phase_algorithm::commit(&mut runtime,stage,durable,&cancel).await?;runtime_run.finish_commit_outcome(actual).await.map(AlgorithmResult::Commit)});
        Ok(OwnedRecoveryDriver{run,future:Some(future),receiver,queued:None,sequence:0,outstanding:None,finished:false})
    }
}
impl OwnedRecoveryDriver {
    fn returned_phase_queue(&self)->Result<()> {
        if self.future.is_some()||self.outstanding.is_some()||!self.receiver.is_closed()||!self.receiver.is_empty(){return Err(Error::Conflict)}
        Ok(())
    }
    pub(in crate::client) fn control(&self)->OwnedRecoveryControl{OwnedRecoveryControl{run:self.run.clone()}}
    pub(in crate::client) async fn next(&mut self)->Result<OwnedRecoveryStep>{
        if self.finished{return Err(Error::Cancelled)}
        if self.outstanding.is_some(){return Err(Error::Conflict)}
        // A returned IO/Apply owns the pending channel. It must settle before
        // the shared future can be polled/declare cancellation or terminal.
        let next=loop {
            if let Some(next)=self.queued.take(){break next;}
            let future=self.future.as_mut().ok_or(Error::Cancelled)?;
            tokio::select! {biased;
                result=future=>{
                    self.future=None;
                    match result? {
                        AlgorithmResult::Stage(OriginalForegroundRecoveryAdmission::Ready(stage))=>{
                            self.finished=true;
                            return Ok(OwnedRecoveryStep::PendingPersistence(OwnedRecoveryPendingPersistence{context:self.run.original.clone(),stage:Some(*stage)}));
                        }
                        AlgorithmResult::Stage(OriginalForegroundRecoveryAdmission::Deferred)=>{
                            // Actual shared future returned its typed finite
                            // deferred boundary with no outstanding phase.
                            self.returned_phase_queue()?;
                            self.run.original.active_permit.settle_after_return()?;
                            self.finished=true;return Ok(OwnedRecoveryStep::Deferred);
                        },
                        AlgorithmResult::Stage(OriginalForegroundRecoveryAdmission::DeferredWithSocket(_))=>return Err(Error::Protocol),
                        AlgorithmResult::Stage(OriginalForegroundRecoveryAdmission::Canonical(result))|AlgorithmResult::Commit(result)=>{
                            self.queued=Some(Next::Apply(Envelope{run:self.run.clone(),call:Some(Call::Terminal(result)),reply:None,socket_preparation:None}));
                        }
                    }
                }
                envelope=self.receiver.recv()=>break Next::Apply(envelope.ok_or(Error::Cancelled)?),
            }
        };
        if let Next::Terminal(result)=next {
            // The actual future returned, its terminal Client Apply completed,
            // and the matching Resume transferred this same result/witness.
            self.returned_phase_queue()?;self.run.negative()?;self.run.original.active_permit.settle_after_return()?;
            self.finished=true;return Ok(OwnedRecoveryStep::Canonical(result));
        }
        self.sequence=self.sequence.checked_add(1).ok_or(Error::Protocol)?;let sequence=self.sequence;self.outstanding=Some(sequence);
        match next {
            Next::Apply(envelope)=>Ok(OwnedRecoveryStep::Apply(OwnedRecoveryApply{run:self.run.clone(),sequence,envelope:Some(envelope)})),
            Next::Io(envelope,io)=>Ok(OwnedRecoveryStep::Io(OwnedRecoveryIo{run:self.run.clone(),sequence,envelope:Some(envelope),io:Some(io)})),
            Next::Reply(_,_)|Next::Terminal(_)=>Err(Error::Protocol),
        }
    }
    pub(in crate::client) fn resume(&mut self,mut resumed:OwnedRecoveryResume)->Result<()> {
        if !Arc::ptr_eq(&self.run,&resumed.run)||self.outstanding!=Some(resumed.sequence){return Err(Error::Cancelled)}
        self.outstanding=None;
        match resumed.next.take().ok_or(Error::Cancelled)? {
            Next::Reply(mut envelope,result)=>{let reply=envelope.reply.take().ok_or(Error::Cancelled)?;let _=reply.send(result);},
            next=>self.queued=Some(next),
        }
        Ok(())
    }
}
impl OwnedRecoveryApply {
    #[cfg(test)]
    pub(in crate::client) fn is_cache_key_for_test(&self)->bool{self.envelope.as_ref().is_some_and(|envelope|matches!(envelope.call.as_ref(),Some(Call::CacheKey(..))))}
    pub(in crate::client) fn apply(mut self,client:&mut Client)->Result<OwnedRecoveryResume>{
        let mut envelope=self.envelope.take().ok_or(Error::Cancelled)?;
        if !Arc::ptr_eq(&self.run,&envelope.run){return Err(Error::Cancelled)}
        let call=envelope.call.take().ok_or(Error::Cancelled)?;
        // Actual received auth/read headers must first merge into their matched
        // original Client even on cancellation. Auth body finalization is also
        // mandatory control-plane drain, never generic private-read cancellation.
        let next=match call {
            Call::Terminal(mut result)=>{
                self.run.check(client)?;
                let witness=self.run.original.transition(client,&result,self.run.request.clone(),self.run.storage.clone())?;
                result.owned_transition=Some(witness);
                result.owned_artifacts=self.run.artifacts.lock().map_err(|_|Error::Cancelled)?.take();
                result.check_original(client)?;
                Next::Terminal(result)
            }
            Call::CanonicalApply(mut run,step)=>{
                // Actual nested headers must reach the provider's typed Apply
                // before outer cancellation refusal. Its ordinary phases still
                // enforce the SAME Boundary; only its genuine header path can
                // perform mandatory matched-header bookkeeping after cancel.
                let result=(||{
                    if !Arc::ptr_eq(&run.boundary.context,&self.run.original){return Err(Error::Cancelled)}
                    let OwnedCanonicalChatStep::Apply(phase)=step else{return Err(Error::Protocol)};
                    run.driver.resume(phase.run(client)?)?;
                    self.run.check(client)
                })();
                match result{Ok(())=>Next::Io(envelope,Io::Canonical(run)),Err(error)=>Next::Reply(envelope,Err(error))}
            }
            Call::AuthHeaders(headers)=>match client.apply_owned_session_validation_headers(headers){Ok(body)=>Next::Io(envelope,Io::AuthBody(body)),Err(error)=>Next::Reply(envelope,Err(error))},
            Call::AuthBody(completed)=>{
                // Actual control-plane install/error bookkeeping always finishes
                // before cancellation refusal. Socket uses its exact receipt in
                // THIS SAME short phase, without an intervening Client turn.
                match client.finish_owned_session_validation(completed) {
                    Err(error)=>Next::Reply(envelope,Err(error)),
                    Ok(receipt)=>{
                        let result=(||{
                            receipt.check_original(client,&self.run.original.original)?;
                            self.run.check(client)?;
                            match envelope.socket_preparation.take(){
                                Some(preparation)=>{
                                    let mut active=super::super::super::owned_operation::ActiveOwnedClient::enter(client,&self.run.original.original)?;
                                    Ok(ApplyResult::Io(Io::Connect(preparation.prepare(&mut active,Some(receipt))?)))
                                }
                                None=>Ok(ApplyResult::Reply(Reply::Unit)),
                            }
                        })();
                        match result {Ok(ApplyResult::Io(io))=>Next::Io(envelope,io),Ok(ApplyResult::Reply(reply))=>Next::Reply(envelope,Ok(reply)),Err(error)=>Next::Reply(envelope,Err(error))}
                    }
                }
            }
            Call::ValidateSocket(preparation)=>{
                let result=self.run.check(client).and_then(|_|client.prepare_owned_session_validation(self.run.original.original.clone()));
                match result {Ok(prepared)=>{envelope.socket_preparation=Some(preparation);Next::Io(envelope,Io::AuthHeaders(prepared))},Err(error)=>Next::Reply(envelope,Err(error))}
            }
            Call::ReadHeaders(headers)=>{
                let result=client.apply_owned_read_headers(headers);
                match result {Ok(body)=>match self.run.check(client){Ok(())=>Next::Io(envelope,Io::ReadBody(body)),Err(error)=>Next::Reply(envelope,Err(error))},Err(error)=>Next::Reply(envelope,Err(error))}
            }
            call=>{
                let checked=self.run.check(client);
                if let Err(error)=checked {Next::Reply(envelope,Err(error))}else{
                    let result=self.apply_checked(client,call);
                    match result {Ok(ApplyResult::Reply(reply))=>Next::Reply(envelope,Ok(reply)),Ok(ApplyResult::Io(io))=>Next::Io(envelope,io),Err(error)=>Next::Reply(envelope,Err(error))}
                }
            }
        };
        Ok(OwnedRecoveryResume{run:self.run.clone(),sequence:self.sequence,next:Some(next)})
    }
    fn apply_checked(&self,client:&mut Client,call:Call)->Result<ApplyResult>{
        let context=&self.run.original;
        match call {
            #[cfg(target_arch="wasm32")]
            Call::RestoreBegin=>{
                let port=self.run.checkpoint_port.as_ref().ok_or(Error::Cancelled)?.clone();
                Ok(ApplyResult::Io(Io::RestoreReady(prepare_restore(context.clone(),client,port)?)))
            }
            #[cfg(target_arch="wasm32")]
            Call::RestoreReady(ready)=>Ok(ApplyResult::Io(Io::RestoreRead(ready.start(client)?))),
            #[cfg(target_arch="wasm32")]
            Call::RestoreRead(completed)=>Ok(ApplyResult::Io(Io::RestoreCrypto(completed.readback(client)?))),
            #[cfg(target_arch="wasm32")]
            Call::RestoreDecoded(decoded)=>Ok(ApplyResult::Reply(Reply::Checkpoint(decoded.finish(client)?))),
            Call::CanonicalBegin(job,key)=>{
                if !same_checkpoint_job(&job,context.handoff.job()){return Err(Error::Cancelled)}
                let deadline=*self.run.lease_deadline.lock().map_err(|_|Error::Cancelled)?;
                let boundary=context.canonical_boundary(client,self.run.request.clone(),deadline)?;
                let prepared=client.prepare_original_canonical_chat_read(context.original.clone(),context.handoff.clone(),boundary.clone())?;
                Ok(ApplyResult::Io(Io::Canonical(CanonicalRun{driver:prepared.into_driver()?,boundary,job,key})))
            }
            Call::CanonicalReady(run,result)=>{
                let(chat,key,transition,artifacts)=result.take_parts(client,&context.original,&context.handoff,&run.boundary)?;
                transition.check_original(client,&context.original,&context.handoff,&run.boundary)?;
                let after=transition.after_row()?;
                let mut state=context.row.lock().map_err(|_|Error::Cancelled)?;
                if transition.before_row()!=&state.expected||client.chats.get(&run.job.chat_id)!=after.as_ref(){return Err(Error::Conflict)}
                state.expected=after;state.mutations=state.mutations.checked_add(1).ok_or(Error::Protocol)?;
                drop(state);context.check_row(client)?;
                let current=client.chats.get(&run.job.chat_id).ok_or(Error::Protocol)?;
                let receipt=phase_reconcile::reconcile_actual(&run.job,&chat,&key,&run.key,current)?;
                *self.run.artifacts.lock().map_err(|_|Error::Cancelled)?=Some(OwnedRecoveryArtifacts{handoff:context.handoff.clone(),scope:context.original.clone(),boundary:run.boundary,request:self.run.request.clone(),actual:artifacts});
                Ok(ApplyResult::Reply(Reply::Reconciled(receipt)))
            }
            Call::Fence(cancel)=>{let mut fence=context.fence.clone();fence.caller=cancel;fence.check_client(client)?;Ok(ApplyResult::Reply(Reply::Fence(fence)))},
            Call::CheckFence(fence)=>{
                fence.check_client(client)?;
                if let Some(at)=fence.lease_expires_at {
                    let mut deadline=self.run.lease_deadline.lock().map_err(|_|Error::Cancelled)?;
                    *deadline=Some((*deadline).map_or(at,|old|old.min(at)));
                }
                self.run.negative()?;Ok(ApplyResult::Reply(Reply::Unit))
            },
            Call::Scope(chat)=>{if let Some(chat)=chat{if chat!=context.handoff.job().chat_id{return Err(Error::Cancelled)}context.original.crypto.check_chat(client,&chat)?;}else{context.original.check(client)?;}Ok(ApplyResult::Reply(Reply::Unit))},
            Call::CheckOwner(checkpoint,fence)=>{client.check_recovery_owner(&checkpoint,&fence)?;Ok(ApplyResult::Reply(Reply::Unit))},
            Call::Owner=>Ok(ApplyResult::Reply(Reply::Owner(owner(client)?))),
            Call::ObservedCreatedAt(job)=>{if !same_checkpoint_job(context.handoff.job(),&job){return Err(Error::Cancelled)}Ok(ApplyResult::Reply(Reply::CreatedAt(observed_job_created_at(client,&job)?)))},
            Call::Team=>Ok(ApplyResult::Reply(Reply::Team(client.team()?.map(str::to_owned)))),
            Call::Api=>Ok(ApplyResult::Reply(Reply::Api(client.base.as_str().trim_end_matches('/').into()))),
            Call::Master=>Ok(ApplyResult::Reply(Reply::Master(client.master_capability()?))),
            Call::Canonical(job)=>{if job.chat_id!=context.handoff.job().chat_id{return Err(Error::Cancelled)}Ok(ApplyResult::Reply(Reply::Value(client.canonical_main_candidate(&job)?)))},
            Call::Validate=>Ok(ApplyResult::Io(Io::AuthHeaders(client.prepare_owned_session_validation(context.original.clone())?))),
            Call::Metadata(chat)=>{
                if chat!=context.handoff.job().chat_id{return Err(Error::Cancelled)}
                let mut active=super::super::super::owned_operation::ActiveOwnedClient::enter(client,&context.original)?;
                Ok(ApplyResult::Io(Io::ReadHeaders(active.prepare_owned_read(OwnedReadRoute::ChatMetadata{chat_id:&chat,include_read_details:false})?)))
            }
            Call::ReadBody(completed)=>Ok(ApplyResult::Reply(Reply::Value(client.finish_owned_read(completed)?))),
            Call::Capture(kind,value)=>{capture(&kind,&value,&mut client.completion_recovery_jobs,&mut client.metadata_recovery_jobs)?;Ok(ApplyResult::Reply(Reply::Unit))},
            Call::CacheKey(id,row,selected)=>{context.cache_key_row(client,id,row,selected)?;Ok(ApplyResult::Reply(Reply::Unit))},
            Call::Insert(id,row)=>{context.insert_metadata_row(client,id,row)?;Ok(ApplyResult::Reply(Reply::Unit))},
            Call::SocketBegin=>{let mut active=super::super::super::owned_operation::ActiveOwnedClient::enter(client,&context.original)?;Ok(ApplyResult::Reply(Reply::SocketPreparation(active.begin_owned_completion_recovery_socket(context.original.clone())?)))},
            Call::SocketUnannounced(connected)=>Ok(ApplyResult::Io(Io::Lifecycle(connected.prepare_lifecycle(client)?))),
            Call::SocketConnected(connected)|Call::ConnectedCheck(connected)=>{connected.check_original(client)?;Ok(ApplyResult::Reply(Reply::Connected(connected)))},
            Call::ConnectedFinish(connected)=>{let socket=connected.into_socket(client)?;self.run.check(client)?;Ok(ApplyResult::Reply(Reply::Socket(socket)))},
            Call::Terminal(_)|Call::CanonicalApply(_,_)|Call::ValidateSocket(_)|Call::AuthHeaders(_)|Call::AuthBody(_)|Call::ReadHeaders(_)=>Err(Error::Protocol),
        }
    }
}
enum ApplyResult {Reply(Reply),Io(Io)}
impl OwnedRecoveryIo {
    #[cfg(test)]
    pub(in crate::client) fn stage_name_for_test(&self)->&'static str{match self.io.as_ref(){#[cfg(target_arch="wasm32")] Some(Io::RestoreReady(_))=>"checkpoint_restore_ready",#[cfg(target_arch="wasm32")] Some(Io::RestoreRead(_))=>"checkpoint_restore_read",#[cfg(target_arch="wasm32")] Some(Io::RestoreCrypto(_))=>"checkpoint_restore_crypto",Some(Io::AuthHeaders(_))=>"auth_headers",Some(Io::AuthBody(_))=>"auth_body",Some(Io::ReadHeaders(_))=>"read_headers",Some(Io::ReadBody(_))=>"read_body",Some(Io::Connect(_))=>"socket_connect",Some(Io::Lifecycle(_))=>"socket_lifecycle",Some(Io::Canonical(_))=>"canonical",None=>"consumed"}}
    pub(in crate::client) async fn drive(mut self)->Result<OwnedRecoveryResume>{
        let mut envelope=self.envelope.take().ok_or(Error::Cancelled)?;
        if !Arc::ptr_eq(&self.run,&envelope.run){return Err(Error::Cancelled)}
        let io=self.io.take().ok_or(Error::Cancelled)?;
        let next=match io {
            #[cfg(target_arch="wasm32")]
            Io::RestoreReady(prepared)=>{let ready=prepared.ready().await;envelope.call=Some(Call::RestoreReady(ready));Next::Apply(envelope)},
            #[cfg(target_arch="wasm32")]
            Io::RestoreRead(read)=>{let actual=read.drive().await;envelope.call=Some(Call::RestoreRead(actual));Next::Apply(envelope)},
            #[cfg(target_arch="wasm32")]
            Io::RestoreCrypto(crypto)=>{match crypto.drive().await{Ok(decoded)=>{envelope.call=Some(Call::RestoreDecoded(decoded));Next::Apply(envelope)},Err(error)=>Next::Reply(envelope,Err(error))}},
            Io::Canonical(mut run)=>{
                loop {
                    match run.driver.next().await {
                        Err(error)=>break Next::Reply(envelope,Err(error)),
                        Ok(OwnedCanonicalChatStep::Apply(phase))=>{envelope.call=Some(Call::CanonicalApply(run,OwnedCanonicalChatStep::Apply(phase)));break Next::Apply(envelope);},
                        Ok(OwnedCanonicalChatStep::Io(io))=>{match io.drive().await.and_then(|resume|run.driver.resume(resume)){Ok(())=>{},Err(error)=>break Next::Reply(envelope,Err(error))}},
                        Ok(OwnedCanonicalChatStep::Ready(result))=>{envelope.call=Some(Call::CanonicalReady(run,result));break Next::Apply(envelope);},
                    }
                }
            }
            Io::AuthHeaders(prepared)=>{let run=self.run.clone();let headers=send_owned_session_validation_headers_with_negative(prepared,move||run.narrow_negative()).await;envelope.call=Some(Call::AuthHeaders(headers));Next::Apply(envelope)},
            Io::AuthBody(body)=>{let completed=drive_owned_session_validation_body(body).await;envelope.call=Some(Call::AuthBody(completed));Next::Apply(envelope)},
            Io::ReadHeaders(prepared)=>{let run=self.run.clone();match send_owned_read_headers(prepared,&self.run.request,move||run.narrow_negative()).await{Ok(headers)=>{envelope.call=Some(Call::ReadHeaders(headers));Next::Apply(envelope)},Err(error)=>Next::Reply(envelope,Err(error))}},
            Io::ReadBody(body)=>{let run=self.run.clone();match drive_owned_read_body(body,&self.run.request,move||run.narrow_negative()).await{Ok(completed)=>{envelope.call=Some(Call::ReadBody(completed));Next::Apply(envelope)},Err(error)=>Next::Reply(envelope,Err(error))}},
            Io::Connect(prepared)=>{let run=self.run.clone();match self.run.socket_io(connect_owned_completion_recovery_socket_with_negative(prepared,move||run.narrow_negative())).await{Ok(connected)=>{envelope.call=Some(Call::SocketUnannounced(connected));Next::Apply(envelope)},Err(error)=>Next::Reply(envelope,Err(error))}},
            Io::Lifecycle(prepared)=>{let run=self.run.clone();match self.run.socket_io(drive_owned_completion_recovery_lifecycle_with_negative(prepared,move||run.narrow_negative())).await{Ok(connected)=>{envelope.call=Some(Call::SocketConnected(connected));Next::Apply(envelope)},Err(error)=>Next::Reply(envelope,Err(error))}},
        };
        Ok(OwnedRecoveryResume{run:self.run.clone(),sequence:self.sequence,next:Some(next)})
    }
}
struct OwnedRuntime {run:Arc<Run>,sender:mpsc::Sender<Envelope>}
impl OwnedRuntime {
    async fn call(&mut self,call:Call)->Result<Reply>{
        self.run.negative()?;let(reply,receive)=oneshot::channel();
        self.sender.send(Envelope{run:self.run.clone(),call:Some(call),reply:Some(reply),socket_preparation:None}).await.map_err(|_|Error::Cancelled)?;
        receive.await.map_err(|_|Error::Cancelled)?
    }
    fn original_scope(&self,scope:&RecoveryCrypto)->Result<()> {match scope{RecoveryCrypto::Owned(original)if Arc::ptr_eq(original,&self.run.original.original)=>Ok(()),_=>Err(Error::Cancelled)}}
    async fn unit(&mut self,call:Call)->Result<()> {match self.call(call).await?{Reply::Unit=>Ok(()),_=>Err(Error::Protocol)}}
}
impl RecoveryChecks for OwnedRuntime {
    fn check_fence<'a>(&'a mut self,fence:&'a RecoveryFence)->RecoveryFuture<'a,()>{Box::pin(self.unit(Call::CheckFence(fence.clone())))}
    fn scope_check<'a>(&'a mut self,scope:&'a RecoveryCrypto)->RecoveryFuture<'a,()>{Box::pin(async move{self.original_scope(scope)?;self.unit(Call::Scope(None)).await})}
    fn scope_chat<'a>(&'a mut self,scope:&'a RecoveryCrypto,chat:&'a str)->RecoveryFuture<'a,()>{Box::pin(async move{self.original_scope(scope)?;self.unit(Call::Scope(Some(chat.into()))).await})}
}
fn unsupported<T>()->Result<T>{Err(Error::Unavailable{code:"completion_recovery_owned_unavailable",reason:"OWNED_RECOVERY_RARE_KEY_OR_CANONICAL_PHASE_NOT_AVAILABLE"})}
impl RecoveryPhases for OwnedRuntime {
    fn saved_checkpoint<'a>(&'a mut self,_job:&'a CompletionRecoveryJob,saved:Option<CompletionRecoveryCheckpoint>,_fence:&'a RecoveryFence)->RecoveryFuture<'a,Option<CompletionRecoveryCheckpoint>>{Box::pin(async move{
        #[cfg(target_arch="wasm32")]
        if saved.is_none()&&self.run.checkpoint_port.is_some(){return match self.call(Call::RestoreBegin).await?{Reply::Checkpoint(value)=>Ok(value),_=>Err(Error::Protocol)}}
        Ok(saved)
    })}
    fn fence<'a>(&'a mut self,cancel:&'a CancellationToken)->RecoveryFuture<'a,RecoveryFence>{Box::pin(async move{match self.call(Call::Fence(cancel.clone())).await?{Reply::Fence(fence)=>Ok(fence),_=>Err(Error::Protocol)}})}
    fn validate<'a>(&'a mut self,_fence:&'a RecoveryFence)->RecoveryFuture<'a,()>{Box::pin(self.unit(Call::Validate))}
    fn begin_scope(&mut self)->RecoveryFuture<'_,RecoveryCrypto>{Box::pin(async move{self.run.negative()?;Ok(RecoveryCrypto::Owned(self.run.original.original.clone()))})}
    fn check_owner<'a>(&'a mut self,checkpoint:&'a CompletionRecoveryCheckpoint,fence:&'a RecoveryFence)->RecoveryFuture<'a,()>{Box::pin(self.unit(Call::CheckOwner(Box::new(checkpoint.clone()),fence.clone())))}
    fn team(&mut self)->RecoveryFuture<'_,Option<String>>{Box::pin(async move{match self.call(Call::Team).await?{Reply::Team(team)=>Ok(team),_=>Err(Error::Protocol)}})}
    fn owner(&mut self)->RecoveryFuture<'_,String>{Box::pin(async move{match self.call(Call::Owner).await?{Reply::Owner(owner)=>Ok(owner),_=>Err(Error::Protocol)}})}
    fn observed_created_at<'a>(&'a mut self,job:&'a CompletionRecoveryJob)->RecoveryFuture<'a,Option<u64>>{Box::pin(async move{match self.call(Call::ObservedCreatedAt(job.clone())).await?{Reply::CreatedAt(at)=>Ok(at),_=>Err(Error::Protocol)}})}
    fn api_url(&mut self)->RecoveryFuture<'_,String>{Box::pin(async move{match self.call(Call::Api).await?{Reply::Api(api)=>Ok(api),_=>Err(Error::Protocol)}})}
    fn metadata<'a>(&'a mut self,chat:&'a str,_fence:&'a RecoveryFence)->RecoveryFuture<'a,Option<Value>>{Box::pin(async move{match self.call(Call::Metadata(chat.into())).await?{Reply::Value(value)=>Ok(value),_=>Err(Error::Protocol)}})}
    fn require_native_master(&mut self)->RecoveryFuture<'_,()>{Box::pin(async{unsupported()})}
    fn load_direct_identity(&mut self)->RecoveryFuture<'_,()>{Box::pin(async{unsupported()})}
    fn direct_chat_key<'a>(&'a mut self,_row:&'a Value)->RecoveryFuture<'a,Key>{Box::pin(async{unsupported()})}
    fn master(&mut self)->RecoveryFuture<'_,MasterCapability>{Box::pin(async move{match self.call(Call::Master).await?{Reply::Master(master)=>Ok(master),_=>Err(Error::Protocol)}})}
    fn team_wrapping<'a>(&'a mut self,_team:&'a str)->RecoveryFuture<'a,Value>{Box::pin(async{unsupported()})}
    fn cache_team<'a>(&'a mut self,_team:String,_key:Key,_encrypted:String)->RecoveryFuture<'a,()>{Box::pin(async{unsupported()})}
    fn unwrap_key<'a>(&'a mut self,encrypted:&'a str,wrapping:&'a MasterCapability,fence:&'a RecoveryFence,scope:&'a RecoveryCrypto,id:&'a str)->RecoveryFuture<'a,Key>{Box::pin(phase_key::unwrap_key(self,encrypted,wrapping,fence,scope,id))}
    fn unwrap_selected_key<'a>(&'a mut self,encrypted:&'a str,wrapping:&'a MasterCapability,fence:&'a RecoveryFence,scope:&'a RecoveryCrypto,id:&'a str,wrapper:&'a Value,team:bool)->RecoveryFuture<'a,Key>{Box::pin(phase_key::unwrap_selected_key(self,encrypted,wrapping,fence,scope,id,wrapper,team))}
    fn cache_key_row<'a>(&'a mut self,id:String,row:Value,selected:Option<phase_key::SelectedRecoveryWrapper>)->RecoveryFuture<'a,()>{Box::pin(self.unit(Call::CacheKey(id,row,selected)))}
    fn current_key<'a>(&'a mut self,chat:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,(Value,Key)>{Box::pin(phase_key::current_key(self,chat,fence))}
    fn reconcile<'a>(&'a mut self,job:&'a CompletionRecoveryJob,key:&'a [u8;32],fence:&'a RecoveryFence)->RecoveryFuture<'a,Option<CompletionRecoveryReceipt>>{Box::pin(async move{fence.check()?;match self.call(Call::CanonicalBegin(job.clone(),zeroize::Zeroizing::new(*key))).await?{Reply::Reconciled(receipt)=>Ok(receipt),_=>Err(Error::Protocol)}})}
    fn canonical<'a>(&'a mut self,job:&'a CompletionRecoveryJob)->RecoveryFuture<'a,Option<Value>>{Box::pin(async move{match self.call(Call::Canonical(job.clone())).await?{Reply::Value(value)=>Ok(value),_=>Err(Error::Protocol)}})}
    fn foreground_socket<'a>(&'a mut self,fence:&'a RecoveryFence)->RecoveryFuture<'a,Socket>{Box::pin(phase_io::foreground_socket(self,fence))}
    fn connect_socket<'a>(&'a mut self,fence:&'a RecoveryFence)->RecoveryFuture<'a,RecoveryConnected>{Box::pin(async move{
        let preparation=match self.call(Call::SocketBegin).await?{Reply::SocketPreparation(value)=>value,_=>return Err(Error::Protocol)};
        // New owned route deliberately uses actual auth every time. No copied
        // fresh-session bool or later current endpoint can authorize this URL.
        match self.call(Call::ValidateSocket(preparation)).await?{Reply::Connected(connected)=>{fence.check()?;Ok(RecoveryConnected::Owned(Some(connected)))},_=>Err(Error::Protocol)}
    })}
    fn check_connected<'a>(&'a mut self,connected:&'a mut RecoveryConnected)->RecoveryFuture<'a,()>{Box::pin(async move{let original=match connected{RecoveryConnected::Owned(value)=>value.take().ok_or(Error::Cancelled)?,_=>return Err(Error::Cancelled)};match self.call(Call::ConnectedCheck(original)).await?{Reply::Connected(value)=>{*connected=RecoveryConnected::Owned(Some(value));Ok(())},_=>Err(Error::Protocol)}})}
    fn finish_connected<'a>(&'a mut self,connected:RecoveryConnected)->RecoveryFuture<'a,Socket>{Box::pin(async move{let original=match connected{RecoveryConnected::Owned(Some(value))=>value,_=>return Err(Error::Cancelled)};match self.call(Call::ConnectedFinish(original)).await?{Reply::Socket(socket)=>Ok(socket),_=>Err(Error::Protocol)}})}
    fn exchange<'a>(&'a mut self,socket:&'a mut Socket,kind:&'a str,payload:Value,reply:&'a str,job:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,Value>{Box::pin(phase_io::exchange(self,socket,kind,payload,reply,job,fence))}
    fn persist_main<'a>(&'a mut self,socket:&'a mut Socket,payload:Value,job:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,super::super::phase_runtime::MainPersistAttempt>{Box::pin(phase_io::persist_main(self,socket,payload,job,fence))}
    fn capture<'a>(&'a mut self,kind:&'a str,payload:&'a Value)->RecoveryFuture<'a,()>{Box::pin(self.unit(Call::Capture(kind.into(),payload.clone())))}
    fn retain_stage<'a>(&'a mut self,fence:&'a mut RecoveryFence,_cancel:&'a CancellationToken)->RecoveryFuture<'a,()>{Box::pin(async move{self.run.negative()?;if fence.operation!=self.run.original.cancel{return Err(Error::Cancelled)}Ok(())})}
    fn insert_row<'a>(&'a mut self,chat:String,row:Value)->RecoveryFuture<'a,()>{Box::pin(self.unit(Call::Insert(chat,row)))}
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="completion_recovery/owned_canonical_header_drain_tests.rs"]
mod header_drain_tests;

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="completion_recovery/owned_wrapper_publication_tests.rs"]
mod wrapper_publication_tests;

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="completion_recovery/owned_physical_continuation_tests.rs"]
mod physical_continuation_tests;
