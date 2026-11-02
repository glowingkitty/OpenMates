//! One active driver per SAME original browser Context, independent of adapters.
//! Reserved typed preparation has no effects. Started/unknown/drop never settles.
use super::*;
#[derive(Default)]
pub(in crate::client) struct OriginalRecoveryActiveState {active:Mutex<Option<Arc<Marker>>>}
struct Marker {started:AtomicBool,settled:AtomicBool}
/// Not Clone/serde/publicly constructible. All actual phase/checkpoint/result
/// resources retain the OwnedRecoveryContext which owns this SAME permit.
pub(in crate::client) struct OriginalRecoveryActivePermit {state:Arc<OriginalRecoveryActiveState>,marker:Arc<Marker>}
impl OriginalRecoveryActiveState {
    pub(in crate::client) fn claim(self:&Arc<Self>,one_use:&AtomicBool)->Result<OriginalRecoveryActivePermit>{
        let mut active=self.active.lock().map_err(|_|Error::Protocol)?;
        if active.is_some(){return Err(Error::Conflict)}
        one_use.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        let marker=Arc::new(Marker{started:AtomicBool::new(false),settled:AtomicBool::new(false)});
        *active=Some(marker.clone());
        Ok(OriginalRecoveryActivePermit{state:self.clone(),marker})
    }
    #[cfg(test)]
    pub(in crate::client) fn held_for_test(&self)->bool{self.active.lock().unwrap().is_some()}
}
impl OriginalRecoveryActivePermit {
    pub(super) fn activate(&self)->Result<()> {
        let active=self.state.active.lock().map_err(|_|Error::Protocol)?;
        if !active.as_ref().is_some_and(|actual|Arc::ptr_eq(actual,&self.marker))||self.marker.settled.load(Ordering::Acquire){return Err(Error::Conflict)}
        self.marker.started.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;Ok(())
    }
    /// Only OwnedRecoveryDriver's actual typed Deferred/Canonical transfer calls
    /// this. Pending checkpoint, error, cancel and resource drops cannot call it.
    pub(super) fn settle_after_return(&self)->Result<()> {
        let mut active=self.state.active.lock().map_err(|_|Error::Protocol)?;
        if !self.marker.started.load(Ordering::Acquire)||!active.as_ref().is_some_and(|actual|Arc::ptr_eq(actual,&self.marker)){return Err(Error::Conflict)}
        self.marker.settled.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        active.take();Ok(())
    }
}
impl Drop for OriginalRecoveryActivePermit {
    fn drop(&mut self){
        // Exact typed preparation dropped before into_driver: no future/IO was
        // activated. This finite no-effect boundary can return only its slot.
        if !self.marker.started.load(Ordering::Acquire){
            if let Ok(mut active)=self.state.active.lock(){
                if active.as_ref().is_some_and(|actual|Arc::ptr_eq(actual,&self.marker)){active.take();}
            }
        }
        // A started abandoned attempt leaves the Context-owned marker retained.
    }
}
