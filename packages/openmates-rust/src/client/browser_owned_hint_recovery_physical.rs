//! Thin public opaque forwarding of exact private physical API8. No raw
//! readback/status/hash can construct a successful native/durable resource.
use super::*;
type Persist<T>=std::result::Result<T,BrowserOriginalHintRecoveryPersistenceFailure>;
struct Carry {remainder:Arc<OwnedBrowserMetadataContinuation>,handoff:Arc<crate::client::OriginalHintRecoveryHandoff>,
    #[cfg(target_arch="wasm32")]port_hold:Option<crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort>}
enum Failure {Core(recovery::OriginalRecoveryPersistenceFailure),Held{pending:recovery::OwnedRecoveryPendingPersistence,error:Error}}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryPersistenceFailure {inner:Failure,carry:Carry}
impl std::fmt::Debug for BrowserOriginalHintRecoveryPersistenceFailure{fn fmt(&self,f:&mut std::fmt::Formatter<'_>)->std::fmt::Result{f.write_str("BrowserOriginalHintRecoveryPersistenceFailure")}}
impl BrowserOriginalHintRecoveryPersistenceFailure {
    pub fn error_kind(&self)->&'static str{
        let error=match &self.inner{Failure::Core(inner)=>inner.error(),Failure::Held{error,..}=>error};
        match error{Error::Cancelled=>"cancelled",Error::Conflict=>"conflict",Error::Expired=>"expired",Error::Forbidden=>"forbidden",Error::Authentication=>"authentication",Error::Offline=>"offline",Error::Crypto=>"crypto",Error::Protocol=>"protocol",Error::Unavailable{..}=>"unavailable",_=>"failure"}
    }
    /// Negative ownership transfer only. Not retry/rearm, successful drain or a
    /// newly admitted owner. Native runtime retains/settles all started IO.
    pub fn into_pending(self)->BrowserOriginalHintRecoveryPendingPersistence{
        let pending=match self.inner{Failure::Core(inner)=>inner.into_pending(),Failure::Held{pending,..}=>pending};
        pending_wrapper(pending,self.carry)
    }
}
fn pending_wrapper(inner:recovery::OwnedRecoveryPendingPersistence,carry:Carry)->BrowserOriginalHintRecoveryPendingPersistence{
    BrowserOriginalHintRecoveryPendingPersistence{inner,remainder:carry.remainder,handoff:carry.handoff,#[cfg(target_arch="wasm32")]port_hold:carry.port_hold}
}
fn failed(inner:recovery::OriginalRecoveryPersistenceFailure,carry:Carry)->BrowserOriginalHintRecoveryPersistenceFailure{BrowserOriginalHintRecoveryPersistenceFailure{inner:Failure::Core(inner),carry}}
fn held_pending(pending:recovery::OwnedRecoveryPendingPersistence,error:Error,carry:Carry)->BrowserOriginalHintRecoveryPersistenceFailure{BrowserOriginalHintRecoveryPersistenceFailure{inner:Failure::Held{pending,error},carry}}
fn held(prepared:recovery::PreparedOriginalRecoveryCheckpoint,error:Error,carry:Carry)->BrowserOriginalHintRecoveryPersistenceFailure{held_pending(prepared.into_pending(),error,carry)}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointPreparation {inner:recovery::PreparedOriginalRecoveryCheckpoint,ticket:Arc<recovery::OriginalRecoveryCheckpointIoTicket>,carry:Carry}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointCrypto {inner:recovery::OriginalRecoveryCheckpointCrypto,carry:Carry}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointWrite {inner:recovery::PreparedOriginalRecoveryCheckpointWrite,carry:Carry}
impl BrowserOriginalHintRecoveryPendingPersistence {
    pub fn prepare_checkpoint(self,client:&Client)->Persist<BrowserOriginalHintRecoveryCheckpointPreparation>{
        let checked=self.check_original(client);
        let Self{inner,remainder,handoff,#[cfg(target_arch="wasm32")]port_hold}=self;
        let carry=Carry{remainder,handoff,#[cfg(target_arch="wasm32")]port_hold};
        if let Err(error)=checked{return Err(held_pending(inner,error,carry))}
        let prepared=match inner.prepare_checkpoint_persistence(client){Ok(value)=>value,Err(error)=>return Err(failed(error,carry))};
        let ticket=match prepared.read_ticket(client){Ok(value)=>value,Err(error)=>return Err(held(prepared,error,carry))};
        Ok(BrowserOriginalHintRecoveryCheckpointPreparation{inner:prepared,ticket,carry})
    }
}
impl BrowserOriginalHintRecoveryCheckpointPreparation {
    pub fn into_pending(self)->BrowserOriginalHintRecoveryPendingPersistence{pending_wrapper(self.inner.into_pending(),self.carry)}
}
impl BrowserOriginalHintRecoveryCheckpointCrypto {
    /// Negative ownership transfer only; does not admit IO or rearm a ticket.
    pub fn into_pending(self)->BrowserOriginalHintRecoveryPendingPersistence{pending_wrapper(self.inner.into_pending(),self.carry)}
    pub async fn drive(self)->Persist<BrowserOriginalHintRecoveryCheckpointWrite>{let Self{inner,carry}=self;match inner.drive().await{Ok(inner)=>Ok(BrowserOriginalHintRecoveryCheckpointWrite{inner,carry}),Err(error)=>Err(failed(error,carry))}}
}
impl BrowserOriginalHintRecoveryCheckpointWrite {
    /// Negative ownership transfer only; does not claim durability or drain.
    pub fn into_pending(self)->BrowserOriginalHintRecoveryPendingPersistence{pending_wrapper(self.inner.into_pending(),self.carry)}
}
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_owned_hint_recovery_physical_tests.rs"]
mod tests;
#[cfg(target_arch="wasm32")]
#[path="browser_owned_hint_recovery_native.rs"]
mod native;
#[cfg(target_arch="wasm32")]
pub use native::{BrowserOriginalHintRecoveryCheckpointReadiness,BrowserOriginalHintRecoveryCheckpointRead,BrowserOriginalHintRecoveryCheckpointReadResult,BrowserOriginalHintRecoveryCheckpointNativeWrite,BrowserOriginalHintRecoveryCheckpointNativeWriteResult,BrowserOriginalHintRecoveryCheckpointReadbackCrypto,BrowserOriginalHintRecoveryCheckpointVerified,BrowserOriginalHintRecoveryCheckpointDurable};
