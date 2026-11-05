//! Bounded keyless original recovery identities. DATA only, never job access,
//! foreground mode, lease, native physical commit or completion authority.
use super::*;
#[derive(Clone,Copy,PartialEq,Eq,PartialOrd,Ord)]
pub(in crate::client) enum RecoveryHintKind {Main,Metadata}
#[derive(Default)]
pub(super) struct RecoveryHintJobs {
    jobs:BTreeMap<(RecoveryHintKind,String),String>,needs_rescan:bool,
    offers:BTreeMap<(RecoveryHintKind,String),crate::client::CompletionRecoveryJob>,
}
pub(in crate::client) struct RecoveryHintManifest {
    jobs:BTreeMap<(RecoveryHintKind,String),String>,needs_rescan:bool,
    offers:BTreeMap<(RecoveryHintKind,String),crate::client::CompletionRecoveryJob>,
}
impl RecoveryHintManifest {
    /// Exact typed notification DATA only; execution still needs original Handoff.
    pub(in crate::client) fn offered_for_chat<'a>(&'a self,chat:&'a str)->impl Iterator<Item=&'a crate::client::CompletionRecoveryJob>{self.offers.values().filter(move|job|job.chat_id==chat)}
    pub(in crate::client) fn needs_rescan(&self)->bool{self.needs_rescan}
    pub(in crate::client) fn len(&self)->usize{self.jobs.len()}
    pub(in crate::client) fn contains(&self,job:&crate::client::CompletionRecoveryJob)->bool{
        let kind=match job.kind{crate::client::CompletionRecoveryKind::Main=>RecoveryHintKind::Main,crate::client::CompletionRecoveryKind::Metadata=>RecoveryHintKind::Metadata};
        self.jobs.get(&(kind,job.job_id.clone())).is_some_and(|chat|chat==&job.chat_id)
            &&self.offers.get(&(kind,job.job_id.clone())).is_none_or(|offer|matches!((serde_json::to_value(offer),serde_json::to_value(job)),(Ok(actual),Ok(expected))if actual==expected))
    }
    pub(in crate::client) fn identities(&self)->impl Iterator<Item=(RecoveryHintKind,&str,&str)>{self.jobs.iter().map(|((kind,job),chat)|(*kind,job.as_str(),chat.as_str()))}
}
impl RecoveryHintJobs {
    /// Preserve complete actual WS offers using the existing shared parser.
    /// Keyless older notifications stay keyless; no task/stage is synthesized.
    pub(super) fn record_actual_offer(&mut self,event:&str,row:&Value)->Result<()> {
        if row.get("chat_key_version").is_none(){return Ok(())}
        let mut main=BTreeMap::new();let mut metadata=BTreeMap::new();
        if let Err(error)=super::super::completion_recovery::capture(event,&json!({"jobs":[row]}),&mut main,&mut metadata){self.needs_rescan=true;return Err(error)}
        for job in main.into_values().chain(metadata.into_values()){
            let kind=match job.kind{crate::client::CompletionRecoveryKind::Main=>RecoveryHintKind::Main,crate::client::CompletionRecoveryKind::Metadata=>RecoveryHintKind::Metadata};
            let key=(kind,job.job_id.clone());
            if !self.jobs.get(&key).is_some_and(|chat|chat==&job.chat_id){continue}
            if let Some(old)=self.offers.get(&key){if serde_json::to_value(old)?!=serde_json::to_value(&job)?{self.needs_rescan=true;return Err(Error::Protocol)}}
            self.offers.insert(key,job);
        }
        Ok(())
    }

    pub(super) fn record(&mut self,kind:RecoveryHintKind,job:&str,chat:&str)->Result<()> {
        if uuid::Uuid::parse_str(job).is_err()||uuid::Uuid::parse_str(chat).is_err(){self.needs_rescan=true;return Err(Error::Protocol)}
        let key=(kind,job.into());
        if let Some(existing)=self.jobs.get(&key){
            if existing!=chat{self.needs_rescan=true;return Err(Error::Protocol)}return Ok(())
        }
        if self.jobs.len()>=MAX_HINTS{self.needs_rescan=true;return Ok(())}
        self.jobs.insert(key,chat.into());Ok(())
    }
    pub(super) fn merge(&mut self,other:Self)->Result<()> {
        self.needs_rescan|=other.needs_rescan;
        for((kind,job),chat)in other.jobs{self.record(kind,&job,&chat)?;}
        for(key,offer)in other.offers{if let Some(old)=self.offers.get(&key){if serde_json::to_value(old)?!=serde_json::to_value(&offer)?{self.needs_rescan=true;return Err(Error::Protocol)}}if self.jobs.contains_key(&key){self.offers.insert(key,offer);}}Ok(())
    }
    pub(super) fn snapshot(&self,advertised:&BTreeSet<String>)->RecoveryHintManifest{RecoveryHintManifest{jobs:self.jobs.clone(),offers:self.offers.clone(),needs_rescan:self.needs_rescan||advertised.iter().any(|chat|!self.jobs.values().any(|known|known==chat))}}
}
#[cfg(test)]
#[path="monitor_hint_work_tests.rs"]
mod tests;
