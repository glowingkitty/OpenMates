//! Original API-key negative publication scope and owned JSON; no new authority.
use super::*;
use std::{ops::{Deref,DerefMut},sync::Arc};
pub(super) struct SkillRelease {
    privacy:crate::privacy::PrivacyOptions,
    gate:Option<Arc<dyn Fn()->Result<()>+Send+Sync>>,
    caller:CancellationToken,
    operation:CancellationToken,
}
impl SkillRelease {
    pub(super) fn capture(sdk:&OpenMates,caller:CancellationToken)->Self {
        Self{privacy:sdk.options.privacy.clone(),gate:sdk.options.private_operation_gate.clone(),caller,operation:sdk.operation_cancel.clone()}
    }
    pub(super) fn check(&self)->Result<()> {
        self.privacy.verify()?;
        if let Some(gate)=&self.gate{gate()?;}
        // The callback above may revoke either original token while returning Ok.
        self.check_negative()
    }
    pub(super) fn check_negative(&self)->Result<()> {
        if self.caller.is_cancelled()||self.operation.is_cancelled(){return Err(Error::Cancelled);}Ok(())
    }
    pub(super) async fn caller_cancelled(&self){self.caller.cancelled().await;}
    pub(super) async fn operation_cancelled(&self){self.operation.cancelled().await;}
}
pub(super) struct SkillValue(Value);
impl SkillValue {
    pub(super) fn new(value:Value)->Self{Self(value)}
    pub(super) fn into_inner(mut self)->Value{std::mem::take(&mut self.0)}
    pub(super) fn release(self,scope:&SkillRelease)->Result<Value>{scope.check()?;Ok(self.into_inner())}
}
impl Deref for SkillValue{type Target=Value;fn deref(&self)->&Value{&self.0}}
impl DerefMut for SkillValue{fn deref_mut(&mut self)->&mut Value{&mut self.0}}
impl Drop for SkillValue{fn drop(&mut self){crate::model::zeroize_json(&mut self.0);}}
pub(super) struct SkillValues(Vec<Value>);
impl SkillValues {
    pub(super) fn new(values:Vec<Value>)->Self{Self(values)}
    pub(super) fn into_inner(mut self)->Vec<Value>{std::mem::take(&mut self.0)}
}
impl Deref for SkillValues{type Target=Vec<Value>;fn deref(&self)->&Vec<Value>{&self.0}}
impl DerefMut for SkillValues{fn deref_mut(&mut self)->&mut Vec<Value>{&mut self.0}}
impl Drop for SkillValues{fn drop(&mut self){for value in &mut self.0{crate::model::zeroize_json(value);}}}
