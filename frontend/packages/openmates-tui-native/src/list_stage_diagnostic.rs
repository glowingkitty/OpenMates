//! Finite, opt-in isolated-CI CLI list timing. No SDK authority or product IO.
//! No arbitrary strings/IDs/errors enter a record; the original result is never
//! changed by diagnostic encoding or delivery. Normal command output is separate.
use openmates::cli::ListReadDiagnosticStage;
use serde::Serialize;
use std::{ffi::OsStr, io::{self, Write}, sync::{Arc, Mutex}, time::Instant};

const MAX_RECORDS: usize = 16;
const MAX_BYTES: usize = 2048;
const MAX_ELAPSED_US: u64 = 90_000_000;
const INVALID: &[u8] = b"{\"schemaVersion\":1,\"kind\":\"native-list-stages-v1\",\"status\":\"invalid\",\"reason\":\"bounds\"}\n";

const UNAVAILABLE: &[u8] = b"{\"schemaVersion\":1,\"kind\":\"native-list-stages-v1\",\"status\":\"invalid\",\"reason\":\"unavailable\"}\n";

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Stage {
    Started,
    StoreOpenStarted,
    StoreOpened,
    CredentialsLoaded,
    CacheRestored,
    AdmissionStarted,
    AdmissionFinished,
    ReadDispatchStarted,
    ReadDispatchFinished,
    FinalPublicationStarted,
    RecoveryCheckStarted,
    RecoveryChecked,
    CachedHit,
    FeedHit,
    ForegroundStarted,
    PreDispatchPersisted,
    ForegroundFinished,
    Returned,
    Refused,
}
#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
enum Branch { Unobserved, CachedHit, FeedHit, Foreground }
#[derive(Clone, Copy, Serialize)]
struct Event { stage: Stage, elapsed_us: u64 }
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Report<'a> {
    schema_version: u8,
    kind: &'static str,
    status: &'static str,
    origin: &'static str,
    branch: Branch,
    pending_or_uncertain: Option<bool>,
    admission_split: &'static str,
    output_and_exit: &'static str,
    stages: &'a [Option<Event>],
}
struct State {
    origin: Instant,
    events: [Option<Event>; MAX_RECORDS],
    used: usize,
    invalid: bool,
    unavailable: bool,
    branch: Branch,
    pending_or_uncertain: Option<bool>,
}
impl State {
    fn push(&mut self, stage: Stage, elapsed_us: u64) {
        if self.invalid { return; }
        if self.used >= MAX_RECORDS || elapsed_us > MAX_ELAPSED_US
            || self.used > 0 && self.events[self.used - 1].is_some_and(|event| event.elapsed_us > elapsed_us) {
            self.invalid = true;
            return;
        }
        self.events[self.used] = Some(Event { stage, elapsed_us });
        self.used += 1;
    }
}
// Only the explicit enabled CLI operation allocates state. A borrowed scoped
// callback uses this mutex; there is no process-global or task-local observer.
pub(super) struct ListStages { inner: Option<Arc<Mutex<State>>> }
fn enabled_for(list: bool, ci: Option<&OsStr>, isolated: Option<&OsStr>, opt_in: Option<&OsStr>) -> bool {
    cfg!(panic = "unwind") && list && ci == Some(OsStr::new("true")) && isolated == Some(OsStr::new("1"))
        && opt_in == Some(OsStr::new("1"))
}
impl ListStages {
    pub(super) fn capture(list: bool) -> Self {
        // Only explicit CLI diagnostic configuration is read. No account,
        // credential, SDK, path, provider or model environment is captured.
        let enabled = list && enabled_for(list, std::env::var_os("CI").as_deref(),
            std::env::var_os("OPENMATES_CI_ISOLATED").as_deref(),
            std::env::var_os("OPENMATES_CI_LIST_STAGE_DIAGNOSTIC").as_deref());
        Self::new(enabled)
    }
    fn new(enabled: bool) -> Self {
        if !enabled { return Self { inner: None }; }
        let mut state = State { origin: Instant::now(), events: [None; MAX_RECORDS], used: 0, invalid: false, unavailable: false,
            branch: Branch::Unobserved, pending_or_uncertain: None };
        state.push(Stage::Started, 0);
        Self { inner: Some(Arc::new(Mutex::new(state))) }
    }
    pub(super) fn is_enabled(&self) -> bool { self.inner.is_some() }
    pub(super) fn record(&self, stage: Stage) {
        self.noninterfering(|| self.record_observation(stage, None, None));
    }
    fn mark_unavailable(&self) {
        if let Some(inner) = &self.inner { if let Ok(mut state) = inner.lock() { state.unavailable = true; } }
    }
    fn noninterfering(&self, observe: impl FnOnce()) {
        if !self.is_enabled() { return; }
        if let Err(payload) = std::panic::catch_unwind(std::panic::AssertUnwindSafe(observe)) {
            // Dropping an arbitrary caught payload can itself panic. Diagnostic
            // failures must never unwind through the original command result.
            std::mem::forget(payload);
            self.mark_unavailable();
        }
    }
    fn record_observation(&self, stage: Stage, branch: Option<Branch>, pending: Option<bool>) {
        let Some(inner) = &self.inner else { return; };
        let Ok(mut state) = inner.lock() else { return; };
        if let Some(branch) = branch { state.branch = branch; }
        if let Some(pending) = pending { state.pending_or_uncertain = Some(pending); }
        let elapsed = state.origin.elapsed().as_micros();
        if elapsed > u128::from(MAX_ELAPSED_US) { state.invalid = true; return; }
        state.push(stage, elapsed as u64);
    }
    pub(super) fn observe(&self, event: ListReadDiagnosticStage) {
        self.noninterfering(|| self.observe_inner(event));
    }
    fn observe_inner(&self, event: ListReadDiagnosticStage) {
        match event {
            ListReadDiagnosticStage::RecoveryCheckStarted => self.record(Stage::RecoveryCheckStarted),
            ListReadDiagnosticStage::RecoveryChecked { pending_or_uncertain } =>
                self.record_observation(Stage::RecoveryChecked, None, Some(pending_or_uncertain)),
            ListReadDiagnosticStage::CachedHit => self.record_observation(Stage::CachedHit, Some(Branch::CachedHit), None),
            ListReadDiagnosticStage::FeedHit => self.record_observation(Stage::FeedHit, Some(Branch::FeedHit), None),
            ListReadDiagnosticStage::ForegroundStarted => self.record_observation(Stage::ForegroundStarted, Some(Branch::Foreground), None),
            ListReadDiagnosticStage::PreDispatchPersisted => self.record(Stage::PreDispatchPersisted),
            ListReadDiagnosticStage::ForegroundFinished => self.record(Stage::ForegroundFinished),
        }
    }
    #[cfg(test)]
    fn record_at(&self, stage: Stage, elapsed_us: u64) {
        if let Some(inner) = &self.inner { if let Ok(mut state) = inner.lock() { state.push(stage, elapsed_us); } }
    }
    pub(super) fn finish(&self, returned: bool) { self.record(if returned { Stage::Returned } else { Stage::Refused }); }
    fn encoded(&self) -> Option<Vec<u8>> {
        let inner = self.inner.as_ref()?;
        let Ok(state) = inner.lock() else { return Some(UNAVAILABLE.to_vec()); };
        if state.unavailable { return Some(UNAVAILABLE.to_vec()); }
        if state.invalid { return Some(INVALID.to_vec()); }
        struct Bounded(Vec<u8>);
        impl Write for Bounded {
            fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
                if bytes.len() > MAX_BYTES.saturating_sub(self.0.len()).saturating_sub(1) {
                    return Err(io::ErrorKind::InvalidData.into());
                }
                self.0.extend_from_slice(bytes);Ok(bytes.len())
            }
            fn flush(&mut self) -> io::Result<()> { Ok(()) }
        }
        let mut output = Bounded(Vec::with_capacity(MAX_BYTES));
        let report = Report { schema_version: 1, kind: "native-list-stages-v1", status: "observed",
            origin: "command-runtime-entry", branch: state.branch, pending_or_uncertain: state.pending_or_uncertain,
            admission_split: "auth-and-initial-persist-combined", output_and_exit: "unobserved",
            stages: &state.events[..state.used] };
        if serde_json::to_writer(&mut output, &report).is_err() { return Some(INVALID.to_vec()); }
        output.0.push(b'\n');Some(output.0)
    }
    fn emit_to(&self, destination: &mut impl Write) {
        self.noninterfering(|| {
            if let Some(encoded) = self.encoded() {
                // No write error/panic becomes a product error or raw diagnostic.
                if destination.write_all(&encoded).is_err() { self.mark_unavailable(); }
            }
        });
    }
    pub(super) fn emit(&self) {
        if !self.is_enabled() { return; }
        self.emit_to(&mut io::stderr());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    fn report(stages: &ListStages) -> Value { serde_json::from_slice(&stages.encoded().unwrap()).unwrap() }
    #[test]
    fn default_off_and_non_list_scope_never_capture_or_emit() {
        for (list, ci, isolated, opt_in) in [
            (true,None,None,None),(false,Some("true"),Some("1"),Some("1")),
            (true,Some("false"),Some("1"),Some("1")),(true,Some("true"),Some("0"),Some("1")),
            (true,Some("true"),Some("1"),Some("true")),(true,Some("true"),Some("1"),None),
        ] { assert!(!enabled_for(list,ci.map(OsStr::new),isolated.map(OsStr::new),opt_in.map(OsStr::new))); }
        assert!(enabled_for(true,Some(OsStr::new("true")),Some(OsStr::new("1")),Some(OsStr::new("1"))));
        let stages = ListStages::new(false);
        for _ in 0..32 { stages.record(Stage::ReadDispatchStarted); }
        stages.finish(false);assert!(stages.inner.is_none());assert!(stages.encoded().is_none());
        let mut output = Vec::new();stages.emit_to(&mut output);assert!(output.is_empty());
    }
    #[test]
    fn all_fields_are_closed_and_private_data_has_no_input_slot() {
        let variants=[Stage::StoreOpenStarted,Stage::StoreOpened,Stage::CredentialsLoaded,Stage::CacheRestored,
            Stage::AdmissionStarted,Stage::AdmissionFinished,Stage::ReadDispatchStarted,Stage::ReadDispatchFinished,
            Stage::FinalPublicationStarted,Stage::RecoveryCheckStarted,Stage::RecoveryChecked,Stage::CachedHit,
            Stage::ForegroundStarted,Stage::PreDispatchPersisted,Stage::ForegroundFinished,Stage::Returned,Stage::Refused];
        for stage in variants {
            let stages=ListStages::new(true);stages.record_at(stage,MAX_ELAPSED_US);let value=report(&stages);
            assert_eq!(value.as_object().unwrap().keys().map(String::as_str).collect::<std::collections::BTreeSet<_>>(),
                ["schemaVersion","kind","status","origin","branch","pendingOrUncertain","admissionSplit","outputAndExit","stages"].into_iter().collect());
            assert_eq!(value["outputAndExit"],"unobserved");assert_eq!(value["admissionSplit"],"auth-and-initial-persist-combined");
            for event in value["stages"].as_array().unwrap() { assert_eq!(event.as_object().unwrap().len(),2);assert!(event["stage"].is_string());assert!(event["elapsed_us"].as_u64().is_some()); }
            let encoded=stages.encoded().unwrap();assert!(encoded.len()<=MAX_BYTES);let text=String::from_utf8(encoded).unwrap();
            for forbidden in ["PRIVATE","cookie","ownerId","chatId","path","count","credential-key","errorMessage","http:"] {assert!(!text.contains(forbidden));}
        }
    }
    #[test]
    fn actual_scoped_events_record_branch_and_unknown_recovery_without_new_policy_reads() {
        for pending in [false,true] {
            let stages=ListStages::new(true);stages.observe(ListReadDiagnosticStage::RecoveryCheckStarted);
            stages.observe(ListReadDiagnosticStage::RecoveryChecked{pending_or_uncertain:pending});
            if pending { stages.observe(ListReadDiagnosticStage::ForegroundStarted); }
            else { stages.observe(ListReadDiagnosticStage::CachedHit); }
            stages.finish(true);
            let value=report(&stages);assert_eq!(value["pendingOrUncertain"],pending);assert_eq!(value["branch"],if pending {"foreground"} else {"cached_hit"});
        }
        let stages=ListStages::new(true);stages.observe(ListReadDiagnosticStage::ForegroundStarted);
        stages.observe(ListReadDiagnosticStage::PreDispatchPersisted);stages.observe(ListReadDiagnosticStage::ForegroundFinished);stages.finish(false);
        assert_eq!(report(&stages)["branch"],"foreground");assert!(report(&stages)["pendingOrUncertain"].is_null());
    }
    #[test]
    fn seventeenth_record_refuses_diagnostic_without_truncating_to_a_valid_trace() {
        let stages=ListStages::new(true);
        for _ in 1..MAX_RECORDS {stages.record_at(Stage::ReadDispatchStarted,MAX_ELAPSED_US);}
        assert_eq!(report(&stages)["stages"].as_array().unwrap().len(),MAX_RECORDS);
        stages.record_at(Stage::Returned,MAX_ELAPSED_US);
        assert_eq!(report(&stages),serde_json::json!({"schemaVersion":1,"kind":"native-list-stages-v1","status":"invalid","reason":"bounds"}));
        assert!(stages.encoded().unwrap().len()<=MAX_BYTES);
    }
    #[test]
    fn non_monotonic_or_out_of_bound_time_is_invalid_not_clamped_into_success() {
        for times in [[10,9],[MAX_ELAPSED_US+1,MAX_ELAPSED_US+1]] {let stages=ListStages::new(true);for time in times{stages.record_at(Stage::ReadDispatchStarted,time);}assert_eq!(report(&stages)["status"],"invalid");}
    }
    #[test]
    fn failed_delivery_never_changes_command_or_error_result() {
        struct Refuse;
        impl Write for Refuse {fn write(&mut self,_:&[u8])->io::Result<usize>{Err(io::ErrorKind::BrokenPipe.into())}fn flush(&mut self)->io::Result<()>{Err(io::ErrorKind::BrokenPipe.into())}}
        let stages=ListStages::new(true);stages.finish(false);stages.emit_to(&mut Refuse);
        assert_eq!(report(&stages)["status"],"invalid");assert_eq!(report(&stages)["reason"],"unavailable");
    }
    #[test]
    fn poisoned_or_panicking_observer_is_unavailable_without_escaping() {
        let stages=ListStages::new(true);
        stages.noninterfering(|| panic!("synthetic diagnostic callback refusal"));
        assert_eq!(report(&stages)["reason"],"unavailable");
        let poisoned=ListStages::new(true);
        let _=std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard=poisoned.inner.as_ref().unwrap().lock().unwrap();
            panic!("synthetic diagnostic poison");
        }));
        poisoned.record(Stage::Returned);assert_eq!(report(&poisoned)["reason"],"unavailable");
    }
    #[test]
    fn panicking_writer_is_unavailable_without_changing_the_result() {
        struct PanicWrite;
        impl Write for PanicWrite {fn write(&mut self,_:&[u8])->io::Result<usize>{panic!("synthetic diagnostic writer refusal")}fn flush(&mut self)->io::Result<()>{Ok(())}}
        let stages=ListStages::new(true);let original:Result<(),&str>=Err("original");
        stages.emit_to(&mut PanicWrite);assert_eq!(original,Err("original"));assert_eq!(report(&stages)["reason"],"unavailable");
    }

    struct DropPanic;
    impl Drop for DropPanic { fn drop(&mut self) { panic!("synthetic payload drop refusal"); } }
    #[test]
    fn diagnostic_callback_drop_panicking_payload_cannot_replace_original_result() {
        let stages=ListStages::new(true); let original:Result<(),&str>=Err("original");
        stages.noninterfering(|| std::panic::panic_any(DropPanic));
        assert_eq!(original,Err("original")); assert_eq!(report(&stages)["reason"],"unavailable");
    }
    #[test]
    fn diagnostic_writer_drop_panicking_payload_cannot_replace_original_result() {
        struct Writer;
        impl Write for Writer {
            fn write(&mut self,_:&[u8])->io::Result<usize>{std::panic::panic_any(DropPanic)}
            fn flush(&mut self)->io::Result<()>{Ok(())}
        }
        let stages=ListStages::new(true);let original:Result<(),&str>=Err("original");
        stages.emit_to(&mut Writer);assert_eq!(original,Err("original"));
        assert_eq!(report(&stages)["reason"],"unavailable");
    }

}
