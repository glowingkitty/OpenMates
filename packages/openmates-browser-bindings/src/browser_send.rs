//! Worker-local transport handles. Client owns protocol/auth/crypto/persistence.
use super::worker_only;
use openmates_sdk::model::StreamUpdate;
use openmates_sdk::client::{PreparedSavedSend, SavedSendTerminal, SavedSendDisposition, SavedSendPublicationGuard, SavedSendOutcome};
use std::{cell::{Cell, RefCell}, rc::Rc};
use tokio::sync::{Notify, mpsc};
use tokio_util::sync::CancellationToken;
use wasm_bindgen::prelude::*;
use zeroize::{Zeroize, Zeroizing};

struct State {
    handle: String, generation: f64, principal: String, operation: String, chat_id: String,
    creation: Option<RefCell<owned::new_chat::CreationIdentity>>,
    publication: SavedSendPublicationGuard, final_publication: RefCell<Option<SavedSendPublicationGuard>>,
    cancel: CancellationToken, finished: Cell<bool>, closed: Cell<bool>,
    terminal: RefCell<Option<Result<(), &'static str>>>, revoked:Cell<bool>, changed: Notify, receiver: RefCell<mpsc::Receiver<StreamUpdate>>,
}
impl State {
    fn check(&self, handle: &str, generation: f64, operation: &str) -> Result<(), JsValue> {
        worker_only()?;
        if self.closed.get() || handle != self.handle || generation != self.generation || operation != self.operation {
            return Err(JsValue::from_str("session_expired"));
        }
        Ok(())
    }
    fn erase_queued(&self){
        if let Ok(mut receiver)=self.receiver.try_borrow_mut(){receiver.close();while let Ok(mut update)=receiver.try_recv(){update.zeroize();}}
    }
    fn context_revoked(&self)->bool {self.revoked.get()}
    fn finish(&self, terminal: Result<(), &'static str>) {
        if !self.finished.replace(true) {self.revoked.set(matches!(terminal,Err("session_expired"))); *self.terminal.borrow_mut() = Some(terminal); }
        if self.context_revoked(){self.erase_queued();}
        self.changed.notify_waiters();
    }
    fn cancel(&self) {
        self.cancel.cancel();
        // Unblock an SDK sender even when the page has stopped pulling. If an
        // event borrow is pending, its notification branch performs this close.
        if let Ok(mut receiver) = self.receiver.try_borrow_mut() { receiver.close(); }
        self.changed.notify_waiters();
    }
    fn close(&self) {
        self.closed.set(true);
        if !self.finished.get() { self.cancel(); }
        self.erase_queued();
        self.changed.notify_waiters();
    }
}
impl Drop for State {
    fn drop(&mut self){let receiver=self.receiver.get_mut();receiver.close();while let Ok(mut update)=receiver.try_recv(){update.zeroize();}}
}
#[wasm_bindgen]
pub struct BrowserPreparedSend {
    state: Rc<State>, prepared: Option<PreparedSavedSend>, sender: Option<mpsc::Sender<StreamUpdate>>, receiver_taken: bool,
}
#[wasm_bindgen]
pub struct BrowserSendTerminal { state: Rc<State>, terminal: Option<SavedSendTerminal> }
impl BrowserSendTerminal {
    pub(super) fn take(&mut self, handle:&str, generation:f64, principal:&str)->Result<SavedSendTerminal,JsValue> {
        self.state.check(handle,generation,&self.state.operation)?;
        if self.state.principal != principal { return Err(JsValue::from_str("session_expired")); }
        self.terminal.take().ok_or_else(||JsValue::from_str("session_expired"))
    }
    pub(super) fn publish(&self, disposition:&SavedSendDisposition)->Result<String,JsValue> {
        if disposition.operation_id()!=self.state.operation { return Err(JsValue::from_str("session_expired")); }
        let outcome = match disposition.outcome() {
            SavedSendOutcome::Completed => "completed", SavedSendOutcome::Cancelled => "cancelled",
            SavedSendOutcome::Uncertain => "uncertain", SavedSendOutcome::Backpressure=>"backpressure", SavedSendOutcome::SessionExpired => "session_expired",
            SavedSendOutcome::Unavailable => "unavailable",
        };
        let guard=disposition.publication_guard();
        // Nonreusable dispositions carry only fixed negative metadata; no
        // private result or recovery identity is serialized across this seam.
        if disposition.reusable() { guard.check_release().map_err(|_|JsValue::from_str("session_expired"))?; }
        let receipt=serde_json::json!({"operationId":self.state.operation,"receiptId":disposition.receipt_id(),
            "scopeEpoch":disposition.scope_epoch(),"outcome":outcome,"canContinueParent":disposition.can_continue_parent(),"originalTurnSettled":disposition.original_turn_settled()}).to_string();
        if disposition.reusable() { guard.check_release().map_err(|_|JsValue::from_str("session_expired"))?; }
        *self.state.final_publication.borrow_mut()=Some(guard);
        self.state.finish(match disposition.outcome() {
            SavedSendOutcome::Completed=>Ok(()),SavedSendOutcome::Cancelled=>Err("cancelled"),
            SavedSendOutcome::Uncertain if disposition.original_cancelled_result()=>Err("cancelled"),
            SavedSendOutcome::SessionExpired=>Err("session_expired"),_=>Err("unavailable"),
        });
        Ok(receipt)
    }
}
impl Drop for BrowserSendTerminal {
    fn drop(&mut self) { if self.terminal.is_some() {self.state.cancel();self.state.finish(Err("session_expired"));} }
}
#[wasm_bindgen]
pub struct BrowserSendControl { state: Rc<State> }
#[wasm_bindgen]
pub struct BrowserSendEvents { state: Rc<State> }

pub(super) fn prepare(handle: &str, generation: f64, principal: &str, chat_id: &str, prepared:PreparedSavedSend) -> BrowserPreparedSend {
    // One bounded pull channel: neither SDK updates nor a page postMessage queue
    // are silently accumulated/coalesced or treated as durable history.
    let (sender, receiver) = mpsc::channel(1);
    BrowserPreparedSend { state: Rc::new(State { handle: handle.into(), generation, principal: principal.into(),
        operation: prepared.id().into(), chat_id: chat_id.into(), creation:None, cancel: prepared.cancellation_request(),
        publication:prepared.publication_guard(),final_publication:RefCell::new(None),
        finished: Cell::new(false), closed: Cell::new(false), terminal: RefCell::new(None), revoked:Cell::new(false), changed: Notify::new(), receiver: RefCell::new(receiver) }),
        prepared:Some(prepared),sender: Some(sender), receiver_taken: false }
}
impl BrowserPreparedSend {
    pub(super) fn check_client(&self, handle: &str, generation: f64, principal: &str) -> Result<(), JsValue> {
        self.state.check(handle, generation, &self.state.operation)?;
        if self.state.principal != principal || self.state.finished.get() { return Err(JsValue::from_str("session_expired")); }
        Ok(())
    }
    pub(super) fn take_prepared(&mut self)->Result<PreparedSavedSend,JsValue> {
        self.prepared.take().ok_or_else(||JsValue::from_str("session_expired"))
    }
    pub(super) fn terminal(&self, terminal:SavedSendTerminal)->BrowserSendTerminal {
        BrowserSendTerminal {state:self.state.clone(),terminal:Some(terminal)}
    }
    pub(super) fn take_sender(&mut self) -> Result<mpsc::Sender<StreamUpdate>, JsValue> {
        if !self.receiver_taken { return Err(JsValue::from_str("invalid_request")); }
        self.sender.take().ok_or_else(|| JsValue::from_str("session_expired"))
    }
}
#[wasm_bindgen]
impl BrowserPreparedSend {
    #[wasm_bindgen(getter)] pub fn operation_id(&self) -> String { self.state.operation.clone() }
    pub fn control(&self) -> Result<BrowserSendControl, JsValue> { worker_only()?; Ok(BrowserSendControl { state: self.state.clone() }) }
    pub fn take_events(&mut self) -> Result<BrowserSendEvents, JsValue> {
        worker_only()?;
        if self.receiver_taken { return Err(JsValue::from_str("session_expired")); }
        self.receiver_taken = true;
        Ok(BrowserSendEvents { state: self.state.clone() })
    }
}
impl Drop for BrowserPreparedSend {
    fn drop(&mut self) {
        // Early validation/drop before handing the sender to Client must settle
        // already-created event readers; it cannot leave a future operation live.
        if self.sender.is_some() { self.state.cancel(); self.state.finish(Err("cancelled")); }
    }
}
#[wasm_bindgen]
impl BrowserSendControl {
    /// A pending encoded frame cannot outlive authoritative core revocation.
    pub fn publication_current(&self,handle:&str,generation:f64,operation:&str)->Result<bool,JsValue>{
        self.state.check(handle,generation,operation)?;Ok(!self.state.context_revoked() && self.state.publication.check_release().is_ok())
    }
    /// Request cooperative SDK cancellation. This is not a server stop ACK.
    pub fn cancel(&self, handle: &str, generation: f64, operation: &str) -> Result<(), JsValue> {
        self.state.check(handle, generation, operation)?;
        if self.state.finished.get() { return Err(JsValue::from_str("session_expired")); }
        self.state.cancel();
        Ok(())
    }
    pub fn close(&self) { self.state.close(); }
}
fn encoded_update(update: &StreamUpdate) -> Result<Zeroizing<String>, JsValue> {
    let allowed = match update {
        StreamUpdate::Content { content, thinking, mate } => content.len() <= 64*1024 && thinking.len() <= 64*1024 && mate.len() <= 4096,
        StreamUpdate::Completed { content, .. } => content.len() <= 64*1024,
        StreamUpdate::Status(value) => value.len() <= 4096,
        StreamUpdate::Consent { items, request_id } => items.len() <= 64 && request_id.len() <= 128,
        _ => true,
    };
    if !allowed { return Err(JsValue::from_str("unavailable")); }
    // Borrow the SDK value directly. No json! intermediate clones private text.
    // The writer's partial bytes wipe on serialization failure as well.
    let mut bytes=Zeroizing::new(Vec::<u8>::new());
    bytes.extend_from_slice(br#"{"type":"update","update":"#);
    serde_json::to_writer(&mut *bytes,update).map_err(|_|JsValue::from_str("unavailable"))?;
    bytes.push(b'}');
    let encoded=String::from_utf8(std::mem::take(&mut *bytes)).map(Zeroizing::new).map_err(|error|{
        let mut bytes=error.into_bytes();bytes.zeroize();JsValue::from_str("unavailable")
    })?;
    if encoded.len() + 8192 > 256*1024 { return Err(JsValue::from_str("unavailable")); }
    Ok(encoded)
}
#[wasm_bindgen]
impl BrowserSendEvents {
    /// Pull exactly one bounded SDK update or one final scoped outcome. The
    /// independent control object remains callable while this borrow is pending.
    pub async fn next_event(&mut self, handle: &str, generation: f64, operation: &str) -> Result<Option<String>, JsValue> {
        loop {
            self.state.check(handle, generation, operation)?;
            let changed = self.state.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            let next = {
                let mut receiver = self.state.receiver.borrow_mut();
                if self.state.cancel.is_cancelled() { receiver.close(); }
                let next = tokio::select! { biased; _ = &mut changed => None, item = receiver.recv() => Some(item) };
                if self.state.cancel.is_cancelled() { receiver.close(); }
                next
            };
            let Some(mut next) = next else {if self.state.closed.get()||self.state.context_revoked(){self.state.erase_queued();}continue;};
            if let Err(error)=self.state.check(handle,generation,operation){if let Some(update)=next.as_mut(){update.zeroize();}self.state.erase_queued();return Err(error);}
            if let Some(mut update) = next {
                // Once the core reports failure, queued plaintext/consent is no
                // longer a current publication. Preserve admission metadata only.
                let failed = matches!(*self.state.terminal.borrow(), Some(Err(_)));
                if failed && !matches!(&update, StreamUpdate::Started { .. } | StreamUpdate::Submitted { .. } | StreamUpdate::Admitted { .. }) { update.zeroize(); continue; }
                if self.state.publication.check_release().is_err() { update.zeroize(); continue; }
                if let Some(identity)=self.state.creation.as_ref(){
                    if !identity.borrow_mut().observe(&update){update.zeroize();self.state.cancel();return Err(JsValue::from_str("session_expired"));}
                }
                let encoded=encoded_update(&update);
                update.zeroize();
                if self.state.publication.check_release().is_err() { continue; }
                // Accepted synchronous ownership transfer to wasm-bindgen.
                // Rust scratch is wiping until here; JS/foreign heap lifetime
                // after transfer is outside the Rust-owned zeroization claim.
                return encoded.map(|mut encoded|Some(std::mem::take(&mut *encoded)))
                    .map_err(|error| { self.state.cancel(); error });
            }
            if !self.state.finished.get() {
                // Receiver.close can precede the cooperative SDK transaction
                // boundary. Wait for its real outcome, never synthesize an ACK.
                let done = self.state.changed.notified();
                tokio::pin!(done);
                done.as_mut().enable();
                if !self.state.finished.get() { done.await; }
                continue;
            }
            if matches!(*self.state.terminal.borrow(),Some(Ok(()))) {
                self.state.final_publication.borrow().as_ref().ok_or_else(||JsValue::from_str("session_expired"))?
                    .check_release().map_err(|_|JsValue::from_str("session_expired"))?;
            }
            let terminal = self.state.terminal.borrow_mut().take();
            return Ok(terminal.map(|terminal| match terminal {
                Ok(()) => serde_json::json!({"type":"completed","chatId":self.state.creation.as_ref().map(|identity|identity.borrow().chat_id().to_owned()).unwrap_or_else(||self.state.chat_id.clone())}),
                // Even a local failure may follow dispatch. The caller must not
                // infer that retry is safe or that cancellation was acknowledged.
                Err(code) => serde_json::json!({"type":"error","error":code,"mayHaveSubmitted":true}),
            }.to_string()));
        }
    }
}
impl Drop for BrowserSendEvents { fn drop(&mut self) { self.state.close(); } }

#[path="browser_owned_send.rs"]
mod owned;
pub use owned::{BrowserOwnedPreparedSend,BrowserOwnedSendDriver,BrowserOwnedSendStep,BrowserOwnedSendResume};
pub(super) use owned::prepare_owned;
