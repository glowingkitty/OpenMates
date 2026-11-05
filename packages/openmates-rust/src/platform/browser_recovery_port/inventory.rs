//! Sealed original-port ciphertext inventory DATA, never checkpoint durability.
use super::*;
use crate::client::OriginalHintDraftInventoryTicket;
use zeroize::Zeroizing;
const MAX_BYTES:usize=2*1024*1024;
pub(super) struct Slot{ticket:Arc<OriginalHintDraftInventoryTicket>,sender:oneshot::Sender<NativeDraftInventoryPortDelivery>,actual_terminal:Rc<Cell<bool>>,cancel_sent:bool,_keepalive:Rc<Inner>}
impl OriginalBrowserRecoveryPort{
 pub(crate) async fn inventory_ready(&self)->Result<()>{loop{
  let wait=self.inner.changed.notified();tokio::pin!(wait);wait.as_mut().enable();self.inner.check()?;
  if self.inner.context.borrow().is_some()&&self.inner.inventory_ready.get(){return Ok(())}
  tokio::select!{_=self.inner.root.cancelled()=>return Err(Error::Cancelled),_=&mut wait=>{}}
 }}
 pub(crate) fn start_draft_inventory(&self,client:&Client,ticket:Arc<OriginalHintDraftInventoryTicket>)->Result<NativeDraftInventoryPortPending>{
  self.check_original(client)?;ticket.check_original(client)?;
  if !self.inner.inventory_ready.get(){return Err(unavailable())}
  let context=self.inner.context.borrow().clone().ok_or_else(unavailable)?;
  if self.inner.pending.borrow().len()+self.inner.inventory.borrow().len()>=MAX_PENDING{return Err(Error::Conflict)}
  let sequence=self.inner.next.get().checked_add(1).filter(|v|*v<=MAX_SEQUENCE).ok_or_else(unavailable)?;
  let effect=ticket.effect_json(client)?;ticket.claim_dispatch(client)?;
  self.check_negative()?;ticket.check_original_negative()?;
  let(sender,receiver)=oneshot::channel();let actual_terminal=Rc::new(Cell::new(false));self.inner.next.set(sequence);
  self.inner.inventory.borrow_mut().insert(sequence,Slot{ticket:ticket.clone(),sender,actual_terminal:actual_terminal.clone(),cancel_sent:false,_keepalive:self.inner.clone()});
  if inventory_request(&self.inner.port,&context,sequence as f64,ticket.operation_id(),&effect).is_err(){self.inner.inventory.borrow_mut().remove(&sequence);self.inner.changed.notify_waiters();return Err(unavailable())}
  Ok(NativeDraftInventoryPortPending{inner:self.inner.clone(),ticket,sequence,receiver:Some(receiver),actual_terminal,finished:false})
 }
}
pub(super) fn cancel_slot(inner:&Inner,sequence:u64){
 let value={let mut slots=inner.inventory.borrow_mut();slots.get_mut(&sequence).and_then(|slot|{if slot.cancel_sent{return None}slot.cancel_sent=true;Some(slot.ticket.operation_id().to_owned())})};
 if let(Some(operation),Some(context))=(value,inner.context.borrow().clone()){
  if cancel(&inner.port,&context,sequence as f64,&operation).is_err(){inner.failed.set(true);inner.changed.notify_waiters();}
 }
}
pub(super) fn receive(inner:&Rc<Inner>,frame:&Array){
 let Some(sequence)=frame.get(2).as_f64().filter(|v|v.is_finite()&&v.fract()==0.0&&*v>=1.0&&*v<=MAX_SEQUENCE as f64).map(|v|v as u64)else{inner.fail();return};
 let Some(operation)=frame.get(3).as_string()else{inner.fail();return};
 if !inner.inventory.borrow().get(&sequence).is_some_and(|slot|slot.ticket.operation_id()==operation){return}
 let Some(slot)=inner.inventory.borrow_mut().remove(&sequence)else{return};slot.actual_terminal.set(true);
 let result=if frame.get(4).as_bool()==Some(true){frame.get(5).as_string().filter(|v|v.len()<=MAX_BYTES).map(Zeroizing::new).ok_or(Error::Protocol)}
  else{Err(match frame.get(5).as_string().as_deref(){Some("conflict")=>Error::Conflict,Some("cancelled")=>Error::Cancelled,_=>unavailable()})};
 let result=inner.check().and_then(|_|slot.ticket.check_original_negative()).and(result);
 let delivery=NativeDraftInventoryPortDelivery{inner:inner.clone(),ticket:slot.ticket,sequence,result};let _=slot.sender.send(delivery);inner.changed.notify_waiters();
}
pub(crate) struct NativeDraftInventoryPortPending{inner:Rc<Inner>,ticket:Arc<OriginalHintDraftInventoryTicket>,sequence:u64,receiver:Option<oneshot::Receiver<NativeDraftInventoryPortDelivery>>,actual_terminal:Rc<Cell<bool>>,finished:bool}
impl NativeDraftInventoryPortPending{
 pub(crate) async fn drive(mut self)->Result<NativeDraftInventoryPortDelivery>{
  let mut receiver=self.receiver.take().ok_or_else(unavailable)?;
  let delivery=tokio::select!{biased;result=&mut receiver=>result.map_err(|_|unavailable())?,_=self.ticket.cancelled()=>{self.inner.cancel_slot(self.sequence);receiver.await.map_err(|_|unavailable())?}};
  self.finished=true;Ok(delivery)
 }
 pub(crate) fn actual_terminal_observed(&self)->bool{self.actual_terminal.get()}
}
impl Drop for NativeDraftInventoryPortPending{fn drop(&mut self){if !self.finished{self.inner.cancel_slot(self.sequence);}}}
pub(crate) struct NativeDraftInventoryPortDelivery{inner:Rc<Inner>,ticket:Arc<OriginalHintDraftInventoryTicket>,sequence:u64,result:Result<Zeroizing<String>>}
impl NativeDraftInventoryPortDelivery{
 pub(crate) fn consume_for(self,port:&OriginalBrowserRecoveryPort,ticket:&Arc<OriginalHintDraftInventoryTicket>)->Result<NativeDraftInventoryObservation>{
  if !Rc::ptr_eq(&self.inner,&port.inner)||!Arc::ptr_eq(&self.ticket,ticket)||self.sequence==0{return Err(Error::Cancelled)}
  port.check_negative()?;ticket.check_original_negative()?;
  let observed=NativeDraftInventoryObservation{port:port.clone(),ticket:self.ticket,data:self.result?};observed.check_original_negative()?;Ok(observed)
 }
}
/// SAME real native port/ticket remains owned across crypto, reread and floor
/// hydration. DATA/EOF alone never constructs this proof or authorizes an ACK.
pub(crate) struct NativeDraftInventoryObservation{port:OriginalBrowserRecoveryPort,ticket:Arc<OriginalHintDraftInventoryTicket>,data:Zeroizing<String>}
impl NativeDraftInventoryObservation{
 pub(crate) fn check_original(&self,client:&Client)->Result<()>{self.port.check_original(client)?;self.ticket.check_original(client)?;self.check_original_negative()}
 pub(crate) fn check_original_negative(&self)->Result<()>{self.port.check_negative()?;self.ticket.check_original_negative()?;self.port.check_negative()}
 pub(crate) fn data<'a>(&'a self,client:&Client)->Result<&'a str>{self.check_original(client)?;Ok(&self.data)}
 pub(crate) fn ticket(&self)->&Arc<OriginalHintDraftInventoryTicket>{&self.ticket}
}
