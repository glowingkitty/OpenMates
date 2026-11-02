//! Saved stream lifetime and actual foreign allocation. Core owns rearm policy.
use super::*;
use openmates_sdk::client::{OwnedSavedSendDisposition, OwnedSavedSendStep, SavedSendPublicationGuard};
use zeroize::Zeroize;
struct Publication {
    privacy: PrivacyOptions,
    gate: Option<Arc<dyn Fn() -> openmates_sdk::Result<()> + Send + Sync>>,
    core: SavedSendPublicationGuard,
}
/// Typed terminal for a driver error without a returned-refusal proof: the
/// caller's own cancellation stays `cancelled`; otherwise the transport was
/// lost before the outcome could be proven, which callers see as `offline`.
fn unproven_drain_error(request: &CancellationToken, context: &CancellationToken) -> Error {
    if request.is_cancelled() || context.is_cancelled() { Error::Cancelled } else { Error::Offline }
}
pub(super) struct SavedStreamScope {
    guard: Arc<essential::EssentialGuard>,
    state: std::sync::Weak<State>,
    identity_epoch: u64,
    request: CancellationToken,
    publication: std::sync::OnceLock<Publication>,
    updates_outstanding: std::sync::atomic::AtomicUsize,
    updates_changed: tokio::sync::Notify,
    settled: AtomicBool,
    settlement: tokio::sync::Notify,
}
impl SavedStreamScope {
    fn check_context(&self) -> Result<()> {
        // Work cancellation revokes old outputs, not this authenticated parent.
        // Only negative identity retirement/close plus the original policy is
        // checked here; core terminal take still validates every real resource.
        let state = self
            .state
            .upgrade()
            .ok_or(Error::Cancelled)
            .map_err(BindingError::from)?;
        if state.closed.load(Ordering::Acquire)
            || self.identity_epoch != state.identity_epoch.load(Ordering::Acquire)
        {
            return Err(Error::Cancelled.into());
        }
        let original = self.publication.get()
            .ok_or(Error::Cancelled)
            .map_err(BindingError::from)?;
        original.privacy.verify().map_err(BindingError::from)?;
        if let Some(gate) = &original.gate {
            gate().map_err(BindingError::from)?;
        }
        if state.closed.load(Ordering::Acquire)
            || self.identity_epoch != state.identity_epoch.load(Ordering::Acquire)
        {
            return Err(Error::Cancelled.into());
        }
        Ok(())
    }
    fn check_live(&self) -> Result<()> {
        if self.request.is_cancelled() {
            return Err(Error::Cancelled.into());
        }
        self.guard.check()?;
        let original = self.publication.get()
            .ok_or(Error::Cancelled)
            .map_err(BindingError::from)?;
        original.privacy.verify().map_err(BindingError::from)?;
        if let Some(gate) = &original.gate {
            gate().map_err(BindingError::from)?;
        }
        original.core.check_release().map_err(BindingError::from)?;
        self.guard.check()
    }
    fn check_terminal(&self, publication: &SavedSendPublicationGuard) -> Result<()> {
        if self.request.is_cancelled() {
            return Err(Error::Cancelled.into());
        }
        self.guard.check()?;
        let original = self.publication.get()
            .ok_or(Error::Cancelled)
            .map_err(BindingError::from)?;
        original.privacy.verify().map_err(BindingError::from)?;
        if let Some(gate) = &original.gate {
            gate().map_err(BindingError::from)?;
        }
        publication.check_release().map_err(BindingError::from)?;
        self.guard.check()
    }
    async fn updates_drained(&self) {
        loop {
            let changed=self.updates_changed.notified();
            tokio::pin!(changed); changed.as_mut().enable();
            if self.updates_outstanding.load(Ordering::Acquire)==0 { return; }
            // Cancellation refuses retained outputs using their ORIGINAL live
            // guard. It never relabels a queued update with the terminal sibling.
            tokio::select! {biased; _=self.request.cancelled()=>return, _=changed=>{}}
        }
    }
    pub(super) async fn settled(&self) {
        loop {
            let changed = self.settlement.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            if self.settled.load(Ordering::Acquire) {
                return;
            }
            changed.await;
        }
    }
    pub(super) fn is_settled(&self)->bool { self.settled.load(Ordering::Acquire) }
    fn mark_settled(&self) {
        self.settled.store(true, Ordering::Release);
        self.settlement.notify_waiters();
    }
}
struct UpdateReceipt(Arc<SavedStreamScope>);
impl UpdateReceipt {
    fn new(scope:Arc<SavedStreamScope>)->Self {
        scope.updates_outstanding.fetch_add(1,Ordering::AcqRel); Self(scope)
    }
}
impl Drop for UpdateReceipt {
    fn drop(&mut self) {
        self.0.updates_outstanding.fetch_sub(1,Ordering::AcqRel);
        self.0.updates_changed.notify_waiters();
    }
}
pub(super) enum SavedStreamEvent {
    Update(Zeroizing<StreamUpdate>, UpdateReceipt),
    Completed {
        output: Zeroizing<String>,
        disposition: Arc<Mutex<OwnedSavedSendDisposition>>,
        publication: SavedSendPublicationGuard,
    },
    Failure(BindingError),
}
pub(super) struct SavedStreamReceiver {
    scope: Arc<SavedStreamScope>,
    receiver: mpsc::Receiver<SavedStreamEvent>,
}
enum Release {
    Live { scope: Arc<SavedStreamScope>, _receipt: UpdateReceipt },
    Terminal {
        scope: Arc<SavedStreamScope>,
        state: Arc<State>,
        disposition: Arc<Mutex<OwnedSavedSendDisposition>>,
        publication: SavedSendPublicationGuard,
    },
    // Fixed typed failures contain no caller/private diagnostics or chat data.
    PublicFailure,
    Anonymous,
}
/// No Clone/Debug/Serialize/plaintext getter. Foreign output is allocated once.
pub(crate) struct SavedStreamOutput {
    release: Release,
    output: Zeroizing<String>,
    delivered: bool,
    terminal: bool,
}
impl SavedStreamOutput {
    pub(crate) fn is_terminal(&self) -> bool {
        self.terminal
    }
    fn check(&self) -> Result<()> {
        match &self.release {
            Release::Live { scope, .. } => scope.check_live(),
            Release::Terminal {
                scope,
                state,
                disposition,
                publication,
            } => {
                scope.check_terminal(publication)?;
                let client = state
                    .client
                    .try_lock()
                    .map_err(|_| BindingError::from(Error::Conflict))?;
                let disposition = disposition
                    .try_lock()
                    .map_err(|_| BindingError::from(Error::Conflict))?;
                disposition
                    .check_current(&client)
                    .map_err(BindingError::from)?;
                scope.check_terminal(publication)
            }
            Release::PublicFailure | Release::Anonymous => Ok(()),
        }
    }
    fn encode_original<T>(&self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        if let Release::Terminal {
            scope,
            state,
            disposition,
            publication,
        } = &self.release
        {
            scope.check_terminal(publication)?;
            let client = state
                .client
                .try_lock()
                .map_err(|_| BindingError::from(Error::Conflict))?;
            let disposition = disposition
                .try_lock()
                .map_err(|_| BindingError::from(Error::Conflict))?;
            disposition
                .check_current(&client)
                .map_err(BindingError::from)?;
            let value = encode(&self.output)?;
            disposition
                .check_current(&client)
                .map_err(BindingError::from)?;
            scope.check_terminal(publication)?;
            return Ok(value);
        }
        self.check()?;
        let value = encode(&self.output)?;
        self.check()?;
        Ok(value)
    }
    fn encode_checked<T>(&mut self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        let result = self.encode_original(encode);
        self.output.zeroize();
        if result.is_ok() {
            self.delivered = true;
        }
        result
    }
    pub(crate) fn encode_with<T>(mut self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        self.encode_checked(encode)
    }
    pub(super) fn release_json(self) -> Result<String> {
        let mut value = self.encode_with(|text| Ok(Zeroizing::new(text.to_owned())))?;
        Ok(std::mem::take(&mut *value))
    }
}
impl Drop for SavedStreamOutput {
    fn drop(&mut self) {
        if !self.delivered {
            if let Release::Live { scope, .. } | Release::Terminal { scope, .. } = &self.release {
                scope.request.cancel();
            }
        }
    }
}
impl SessionBridge {
    pub(super) async fn drain_saved_driver(state:&State)->Result<()> {
        let original=state.saved_driver.lock().map_err(|_|BindingError::from(Error::Protocol))?.clone();
        if let Some(original)=original { original.settled().await; }
        Ok(())
    }
    pub(super) async fn start_saved_stream(
        &self,
        text: String,
        chat_id: Option<String>,
    ) -> Result<String> {
        let text = Zeroizing::new(text);
        let guard = essential::EssentialGuard::new(self, false)?;
        let identity_epoch = self.state.identity_epoch.load(Ordering::Acquire);
        self.start_saved_stream_admitted(text, chat_id, guard, identity_epoch).await
    }
    async fn start_saved_stream_admitted(
        &self,
        text: Zeroizing<String>,
        chat_id: Option<String>, guard: Arc<essential::EssentialGuard>, identity_epoch: u64) -> Result<String> {
        let identity = self.identity_admission()?;
        guard.check()?;
        let mut events = self
            .state
            .events
            .try_lock()
            .map_err(|_| BindingError::from(Error::Conflict))?;
        let request = CancellationToken::new();
        let scope = Arc::new(SavedStreamScope {
            guard,
            state: Arc::downgrade(&self.state),
            identity_epoch,
            request: request.clone(),
            publication: std::sync::OnceLock::new(),
            updates_outstanding: std::sync::atomic::AtomicUsize::new(0),
            updates_changed: tokio::sync::Notify::new(),
            settled: AtomicBool::new(false),
            settlement: tokio::sync::Notify::new(),
        });
        let id = uuid::Uuid::new_v4().to_string();
        {
            let mut active = self
                .state
                .active
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            if active.is_some() {
                return Err(Error::Conflict.into());
            }
            *active = Some(Active {
                id: id.clone(),
                cancel: request.clone(),
            });
        }
        let (events_tx, events_rx) = mpsc::channel(8);
        let (consent_tx, consent_rx) = mpsc::unbounded_channel();
        *self
            .state
            .consent
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))? = Some(consent_tx);
        *events = Some(Events {
            id: id.clone(),
            receiver: EventReceiver::Saved(SavedStreamReceiver {
                scope: scope.clone(),
                receiver: events_rx,
            }),
        });
        *self.state.saved_driver.lock().map_err(|_| BindingError::from(Error::Protocol))? = Some(scope.clone());
        drop(events);
        drop(identity);
        let state = self.state.clone();
        let joined_scope=scope.clone();
        let original_driver=tokio::spawn(async move {
            let legacy_lane = state.legacy_client_lane.lock().await;
            let (updates, mut receiver) = mpsc::channel::<StreamUpdate>(1);
            let forward_state = state.clone();
            let forward_scope = scope.clone();
            let forward_events = events_tx.clone();
            let mut forward = Some(tokio::spawn(async move {
                while let Some(update) = receiver.recv().await {
                    let update = Zeroizing::new(update);
                    if forward_scope.check_live().is_err() {
                        forward_scope.request.cancel();
                        continue;
                    }
                    if let StreamUpdate::Consent { request_id, items } = &*update {
                        if let Ok(mut pending) = forward_state.pending_consent.lock() {
                            pending.insert(
                                request_id.clone(),
                                items.iter().map(|item| item.id.clone()).collect(),
                            );
                        }
                    }
                    let receipt=UpdateReceipt::new(forward_scope.clone());
                    tokio::select! {biased;_=forward_scope.request.cancelled()=>{},result=forward_events.send(SavedStreamEvent::Update(update,receipt))=>{if result.is_err(){forward_scope.request.cancel();}}}
                }
            }));
            let result: Result<SavedStreamEvent> = async {
                let mut driver = {
                    let mut client = state.client.lock().await;
                    scope.guard.check()?;
                    if state.closed.load(Ordering::Acquire) {
                        return Err(Error::Cancelled.into());
                    }
                    client.set_consent_receiver(consent_rx);
                    // Capture bridge policy once before actual validation/send IO.
                    let privacy = client.options().privacy.clone();
                    let gate = client.options().private_operation_gate.clone();
                    let prepared = client
                        .prepare_validated_owned_saved_send(chat_id.as_deref(), request.clone())
                        .await
                        .map_err(BindingError::from)?;
                    scope.guard.check()?;
                    let original = prepared.publication_guard().map_err(BindingError::from)?;
                    // Captured once from the original prepared Core resource.
                    // Concurrent negative observers never exclude one another;
                    // every original token/policy/Core fence remains checked.
                    scope.publication.set(Publication {
                        privacy,
                        gate,
                        core: original,
                    }).map_err(|_| BindingError::from(Error::Protocol))?;
                    client.start_owned_saved_send(prepared, &text, updates).map_err(BindingError::from)?
                };
                let control=driver.control();
                let context_cancel=scope.guard.token();
                let terminal=loop {
                    // The actual receive/host-queue future owns no Client guard.
                    let step=tokio::select! {biased;
                        result=driver.drive_next()=>result,
                        _=context_cancel.cancelled()=>{request.cancel();control.cancel();driver.drive_next().await}
                    };
                    match step {
                        Ok(OwnedSavedSendStep::Apply(step))=>{
                            let resumed={let mut client=state.client.lock().await;client.apply_owned_saved_send_step(step).await};
                            if let Ok(resumed)=resumed { let _=driver.resume(resumed); }
                            // An apply refusal is delivered through the original
                            // envelope; continue draining that SAME future.
                        },
                        Ok(OwnedSavedSendStep::Terminal(terminal))=>break terminal,
                        Err(error)=>{
                            if let Some(proof)=driver.take_returned_refusal() {
                                if proof.consume_for(&control).is_ok() {
                                    return Err(BindingError::from(error));
                                }
                            }
                            // No returned proof: the drain of this send is
                            // unknown. Never park the stream (a consumer would
                            // wait forever). Dropping the driver without a
                            // returned terminal retires this send through the
                            // core: its gate refuses every later send on this
                            // Client (fail closed), so no successor can start
                            // while old IO might still be in flight.
                            drop(driver);
                            return Err(BindingError::from(unproven_drain_error(&request, &context_cancel)));
                        },
                    }
                };
                drop(driver);
                // EOF of the ORIGINAL bounded Core queue is observed before
                // finish retires A's child. Normal live outputs acknowledge their
                // actual foreign allocation/drop before typed terminal apply.
                if let Some(forward)=forward.take() { forward.await.map_err(|_|BindingError::from(Error::Protocol))?; }
                scope.updates_drained().await;
                let mut client=state.client.lock().await;
                    // Actual driver has returned. No fabricated flag may rearm it.
                    if state.closed.load(Ordering::Acquire) {
                        return Err(Error::Cancelled.into());
                    }
                    scope.check_context()?;
                    let mut disposition = client
                        .finish_owned_saved_send(terminal)
                        .map_err(BindingError::from)?;
                    disposition
                        .check_current(&client)
                        .map_err(BindingError::from)?;
                    // Core alone retains uncertain immutable envelopes/IDs/keys
                    // and applies shared count/byte resource backpressure. The
                    // adapter neither clones them nor invents a replay/reset.
                    let chat = disposition
                        .encode_result_json(&client)
                        .map_err(BindingError::from)?;
                    disposition
                        .check_current(&client)
                        .map_err(BindingError::from)?;
                    let output = Zeroizing::new(format!(
                        "{{\"type\":\"completed\",\"chat\":{}}}",
                        chat.as_str()
                    ));
                    disposition
                        .check_current(&client)
                        .map_err(BindingError::from)?;
                    let publication = disposition.publication_guard();
                    Ok(SavedStreamEvent::Completed {
                        output,
                        disposition: Arc::new(Mutex::new(disposition)),
                        publication,
                    })
            }.await;
            if result.is_err() { request.cancel(); }
            if let Some(forward)=forward.take() { let _=forward.await; }
            if let Ok(mut pending) = state.pending_consent.lock() {
                pending.clear();
            }
            if let Ok(mut consent) = state.consent.lock() {
                consent.take();
            }
            let final_event = result.unwrap_or_else(SavedStreamEvent::Failure);
            // Return the owned terminal payload to the unique join observer.
            // No consumer can see it or admit a successor before actual join.
            drop(legacy_lane);
            (final_event,events_tx,request)
        });
        // The unique actual JoinHandle is never owned by a foreign future.
        // Auth/close wait this SAME join's notification outside the Client lock;
        // abandoning a caller cannot drop the handle or manufacture drain proof.
        tokio::spawn(async move {
            if let Ok((final_event,events_tx,request))=original_driver.await {
                joined_scope.mark_settled();
                // Queue publication follows the SAME actual join. Cancellation
                // cannot pin completed transport/Client cleanup behind a full
                // foreign queue; retained old outputs still check their guard.
                tokio::select! {biased;
                    _=request.cancelled()=>{let _=events_tx.try_send(final_event);},
                    permit=events_tx.reserve()=>{if let Ok(permit)=permit{permit.send(final_event);}}
                }
            }
            // A panic/abort is a held refusal, never successful task drain.
        });
        Ok(id)
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_start_saved_stream(&self, text: String, chat_id: Option<String>) -> impl Future<Output = Result<String>> + Send + 'static {
        let text = Zeroizing::new(text);
        let mut chat_id = Zeroizing::new(chat_id);
        let original = essential::EssentialGuard::new(self, false);
        let identity_epoch = self.state.identity_epoch.load(Ordering::Acquire);
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.start_saved_stream_admitted(text, std::mem::take(&mut *chat_id), guard, identity_epoch).await
        }
    }

    pub(crate) async fn next_event_prepare(&self, id: String) -> Result<SavedStreamOutput> {
        self.next_event_inner(id, false).await
    }
    async fn next_event_inner(
        &self,
        id: String,
        anonymous_only: bool,
    ) -> Result<SavedStreamOutput> {
        let mut events = self.state.events.lock().await;
        let stream = events
            .as_mut()
            .filter(|stream| stream.id == id)
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?;
        if anonymous_only && !matches!(&stream.receiver, EventReceiver::Anonymous(_)) {
            return Err(Error::Conflict.into());
        }
        let mut refused = false;
        let output = match &mut stream.receiver {
            EventReceiver::Anonymous(receiver) => {
                let value = receiver.recv().await;
                let terminal = value
                    .as_ref()
                    .is_none_or(|event| event["type"] == "completed" || event["type"] == "error");
                match value {
                    None => Err(Error::Cancelled.into()),
                    Some(value) => {
                        let text = Zeroizing::new(
                            serde_json::to_string(&value)
                                .map_err(|_| BindingError::from(Error::Protocol))?,
                        );
                        if !terminal {
                            return Ok(SavedStreamOutput {
                                release: Release::Anonymous,
                                output: text,
                                delivered: false,
                                terminal,
                            });
                        }
                        Ok(SavedStreamOutput {
                            release: Release::Anonymous,
                            output: text,
                            delivered: false,
                            terminal,
                        })
                    }
                }
            }
            EventReceiver::Saved(saved) => loop {
                let item = saved.receiver.recv().await;
                match item {
                    Some(SavedStreamEvent::Update(update, receipt)) => {
                        if refused || saved.scope.check_live().is_err() {
                            refused = true;
                            saved.scope.request.cancel();
                            continue;
                        }
                        #[derive(Serialize)]
                        struct Update<'a> {
                            r#type: &'static str,
                            update: &'a StreamUpdate,
                        }
                        let output = Zeroizing::new(
                            serde_json::to_string(&Update {
                                r#type: "update",
                                update: &update,
                            })
                            .map_err(|_| BindingError::from(Error::Protocol))?,
                        );
                        if saved.scope.check_live().is_err() {
                            refused = true;
                            saved.scope.request.cancel();
                            continue;
                        }
                        return Ok(SavedStreamOutput {
                            release: Release::Live { scope: saved.scope.clone(), _receipt: receipt },
                            output,
                            delivered: false,
                            terminal: false,
                        });
                    }
                    Some(SavedStreamEvent::Completed {
                        output,
                        disposition,
                        publication,
                    }) => {
                        saved.scope.settled().await;
                        if refused || saved.scope.check_terminal(&publication).is_err() {
                            break Err(Error::Cancelled.into());
                        }
                        break Ok(SavedStreamOutput {
                            release: Release::Terminal {
                                scope: saved.scope.clone(),
                                state: self.state.clone(),
                                disposition,
                                publication,
                            },
                            output,
                            delivered: false,
                            terminal: true,
                        });
                    }
                    Some(SavedStreamEvent::Failure(error)) => {
                        saved.scope.settled().await;
                        // These are fixed public codes/messages only. They are
                        // never recast as successful/idle authority or Chat data.
                        let output = Zeroizing::new(
                            serde_json::to_string(&json!({"type":"error","error":error}))
                                .map_err(|_| BindingError::from(Error::Protocol))?,
                        );
                        break Ok(SavedStreamOutput {
                            release: Release::PublicFailure,
                            output,
                            delivered: false,
                            terminal: true,
                        });
                    }
                    None => {
                        saved.scope.settled().await;
                        break Err(Error::Cancelled.into());
                    }
                }
            },
        };
        *events = None;
        let mut active = self
            .state
            .active
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        if active.as_ref().is_some_and(|active| active.id == id) {
            *active = None;
        }
        output
    }
    pub(crate) async fn next_anonymous_event(&self, id: String) -> Result<String> {
        // The kind check and receiver read share one exact event-lane guard.
        self.next_event_inner(id, true).await?.release_json()
    }
}
#[cfg(test)]
#[path = "session_saved_stream_tests.rs"]
mod tests;
