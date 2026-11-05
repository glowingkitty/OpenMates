//! Thin platform ownership for the portable original-resource send driver.
//! No protocol, crypto, policy, copied status authority, or second Client.
use super::*;
use openmates_sdk::client::{PreparedOwnedSavedSend,OwnedSavedSendDriver,OwnedSavedSendStep,OwnedSavedSendResume,OwnedSavedSendDisposition};
#[wasm_bindgen]
pub struct BrowserOwnedPreparedSend {state:Rc<State>,prepared:Option<PreparedOwnedSavedSend>,sender:Option<mpsc::Sender<StreamUpdate>>,receiver_taken:bool}
#[wasm_bindgen]
pub struct BrowserOwnedSendDriver {state:Rc<State>,driver:Option<OwnedSavedSendDriver>}
#[wasm_bindgen]
pub struct BrowserOwnedSendStep {state:Rc<State>,step:Option<OwnedSavedSendStep>}
#[wasm_bindgen]
pub struct BrowserOwnedSendResume {state:Rc<State>,resume:Option<OwnedSavedSendResume>}
// Draining a close still processes the exact original native resource. closed
// denies page output via existing State.check, not actual driver settlement.
fn check_original(state:&State,handle:&str,generation:f64,principal:Option<&str>)->Result<(),JsValue>{
    worker_only()?;
    if handle!=state.handle||generation!=state.generation||principal.is_some_and(|p|p!=state.principal){return Err(JsValue::from_str("session_expired"))}Ok(())
}
pub(in crate::browser) fn prepare_owned(handle:&str,generation:f64,principal:&str,chat:&str,prepared:PreparedOwnedSavedSend)->Result<BrowserOwnedPreparedSend,JsValue>{
    let operation=prepared.id().map_err(|_|JsValue::from_str("session_expired"))?.to_owned();
    let cancel=prepared.cancellation_request().map_err(|_|JsValue::from_str("session_expired"))?;
    let publication=prepared.publication_guard().map_err(|_|JsValue::from_str("session_expired"))?;
    let(sender,receiver)=mpsc::channel(1);
    Ok(BrowserOwnedPreparedSend{state:Rc::new(State{handle:handle.into(),generation,principal:principal.into(),operation,chat_id:chat.into(),creation:None,
        publication,final_publication:RefCell::new(None),cancel,finished:Cell::new(false),closed:Cell::new(false),terminal:RefCell::new(None),
        revoked:Cell::new(false),changed:Notify::new(),receiver:RefCell::new(receiver)}),prepared:Some(prepared),sender:Some(sender),receiver_taken:false})
}
impl BrowserOwnedPreparedSend {
    pub(in crate::browser) fn start(&mut self,client:&mut openmates_sdk::Client,handle:&str,generation:f64,principal:&str,text:&str)->Result<BrowserOwnedSendDriver,JsValue>{
        check_original(&self.state,handle,generation,Some(principal))?;
        if self.state.closed.get()||self.state.finished.get()||!self.receiver_taken{return Err(JsValue::from_str("session_expired"))}
        let prepared=self.prepared.take().ok_or_else(||JsValue::from_str("session_expired"))?;
        let sender=self.sender.take().ok_or_else(||JsValue::from_str("session_expired"))?;
        let driver=client.start_owned_saved_send(prepared,text,sender).map_err(|_|JsValue::from_str("session_expired"))?;
        Ok(BrowserOwnedSendDriver{state:self.state.clone(),driver:Some(driver)})
    }
}
#[wasm_bindgen]
impl BrowserOwnedPreparedSend {
    #[wasm_bindgen(getter)]pub fn operation_id(&self)->String{self.state.operation.clone()}
    pub fn control(&self)->Result<BrowserSendControl,JsValue>{worker_only()?;Ok(BrowserSendControl{state:self.state.clone()})}
    pub fn take_events(&mut self)->Result<BrowserSendEvents,JsValue>{
        worker_only()?;if self.receiver_taken{return Err(JsValue::from_str("session_expired"))}self.receiver_taken=true;Ok(BrowserSendEvents{state:self.state.clone()})
    }
}
impl Drop for BrowserOwnedPreparedSend {fn drop(&mut self){if self.sender.is_some(){self.state.cancel();self.state.finish(Err("cancelled"));}}}
#[wasm_bindgen]
impl BrowserOwnedSendDriver {
    /// This await owns only portable driver state; BrowserCoreClient is absent.
    pub async fn next_phase(&mut self,handle:&str,generation:f64,operation:&str)->Result<BrowserOwnedSendStep,JsValue>{
        check_original(&self.state,handle,generation,None)?;
        if operation!=self.state.operation{return Err(JsValue::from_str("session_expired"))}
        let step=self.driver.as_mut().ok_or_else(||JsValue::from_str("session_expired"))?.drive_next().await.map_err(|_|JsValue::from_str("session_expired"))?;
        check_original(&self.state,handle,generation,None)?;
        Ok(BrowserOwnedSendStep{state:self.state.clone(),step:Some(step)})
    }
    pub fn resume(&mut self,mut resume:BrowserOwnedSendResume)->Result<(),JsValue>{
        worker_only()?;if !Rc::ptr_eq(&self.state,&resume.state){return Err(JsValue::from_str("session_expired"))}
        self.driver.as_mut().ok_or_else(||JsValue::from_str("session_expired"))?.resume(resume.resume.take().ok_or_else(||JsValue::from_str("session_expired"))?).map_err(|_|JsValue::from_str("session_expired"))
    }
}
impl Drop for BrowserOwnedSendDriver {fn drop(&mut self){if !self.state.finished.get(){self.state.cancel();self.state.finish(Err("session_expired"));}}}
#[wasm_bindgen]
impl BrowserOwnedSendStep {
    #[wasm_bindgen(getter)]pub fn kind(&self)->Result<String,JsValue>{worker_only()?;match self.step.as_ref(){Some(OwnedSavedSendStep::Apply(_))=>Ok("apply".into()),Some(OwnedSavedSendStep::Terminal(_))=>Ok("terminal".into()),None=>Err(JsValue::from_str("session_expired"))}}
}
impl BrowserOwnedSendStep {
    pub(in crate::browser) async fn apply(&mut self,client:&mut openmates_sdk::Client,handle:&str,generation:f64,principal:&str)->Result<BrowserOwnedSendResume,JsValue>{
        check_original(&self.state,handle,generation,Some(principal))?;
        let phase=match self.step.take(){Some(OwnedSavedSendStep::Apply(phase))=>phase,_=>return Err(JsValue::from_str("session_expired"))};
        let resume=client.apply_owned_saved_send_step(phase).await.map_err(|_|JsValue::from_str("session_expired"))?;
        check_original(&self.state,handle,generation,Some(principal))?;
        Ok(BrowserOwnedSendResume{state:self.state.clone(),resume:Some(resume)})
    }
    pub(in crate::browser) fn finish(&mut self,client:&mut openmates_sdk::Client,handle:&str,generation:f64,principal:&str)->Result<String,JsValue>{
        check_original(&self.state,handle,generation,Some(principal))?;
        let terminal=match self.step.take(){Some(OwnedSavedSendStep::Terminal(terminal))=>terminal,_=>return Err(JsValue::from_str("session_expired"))};
        let disposition=client.finish_owned_saved_send(terminal).map_err(|_|JsValue::from_str("session_expired"))?;
        disposition.check_current(client).map_err(|_|JsValue::from_str("session_expired"))?;
        if disposition.outcome()==SavedSendOutcome::Completed {
            if let Some(identity)=self.state.creation.as_ref(){
                let actual=disposition.recovery_identity(client).map_err(|_|JsValue::from_str("session_expired"))?.ok_or_else(||JsValue::from_str("session_expired"))?;
                if !identity.borrow().matches(actual.chat_id(),actual.message_id()){return Err(JsValue::from_str("session_expired"))}
            }
        }
        let receipt=publish_owned(&self.state,&disposition)?;
        disposition.check_current(client).map_err(|_|JsValue::from_str("session_expired"))?;
        Ok(receipt)
    }
}
fn publish_owned(state:&State,disposition:&OwnedSavedSendDisposition)->Result<String,JsValue>{
    if disposition.operation_id()!=state.operation{return Err(JsValue::from_str("session_expired"))}
    let outcome=match disposition.outcome(){SavedSendOutcome::Completed=>"completed",SavedSendOutcome::Cancelled=>"cancelled",SavedSendOutcome::Uncertain=>"uncertain",SavedSendOutcome::Backpressure=>"backpressure",SavedSendOutcome::SessionExpired=>"session_expired",SavedSendOutcome::Unavailable=>"unavailable"};
    let guard=disposition.publication_guard();
    if disposition.reusable(){guard.check_release().map_err(|_|JsValue::from_str("session_expired"))?;}
    let receipt=serde_json::json!({"operationId":state.operation,"receiptId":disposition.receipt_id(),"scopeEpoch":disposition.scope_epoch(),
        "outcome":outcome,"canContinueParent":disposition.can_continue_parent(),"originalTurnSettled":disposition.original_turn_settled()}).to_string();
    if disposition.reusable(){guard.check_release().map_err(|_|JsValue::from_str("session_expired"))?;}
    *state.final_publication.borrow_mut()=Some(guard);
    state.finish(match disposition.outcome(){SavedSendOutcome::Completed=>Ok(()),SavedSendOutcome::Cancelled=>Err("cancelled"),SavedSendOutcome::Uncertain if disposition.original_cancelled_result()=>Err("cancelled"),SavedSendOutcome::SessionExpired=>Err("session_expired"),_=>Err("unavailable")});
    Ok(receipt)
}

#[path="browser_new_chat_send.rs"]
pub(in crate::browser) mod new_chat;
