//! Fixed Account reminders read. Shared Core owns HTTP/decode/retry policy.
use super::*;
use super::work::{WorkGuard, work_authority};

pub(crate) struct SettingsReadFailure {
    code: &'static str,
    message: String,
    http_status: Option<u16>,
}
impl SettingsReadFailure {
    fn binding(error: BindingError) -> Self {
        Self { code: error.code, message: error.message.into(), http_status: None }
    }
    fn core(error: openmates_sdk::account::SettingsReadError) -> Self {
        let code = BindingError::from(error.core_error()).code;
        Self { code, message: error.to_string(), http_status: error.http_status() }
    }
    pub(crate) fn json(&self) -> String {
        serde_json::json!({"code":self.code,"message":self.message,"http_status":self.http_status}).to_string()
    }
}
/// Original guard is captured synchronously, before a foreign future exists.
pub(crate) struct PreparedSettingsReminders { bridge: SessionBridge, guard: Arc<WorkGuard> }
pub(crate) struct SettingsRemindersControl(Arc<WorkGuard>);
impl SettingsRemindersControl { pub(crate) fn cancel(&self) { self.0.cancel(); } }
impl PreparedSettingsReminders {
    pub(crate) fn control(&self) -> SettingsRemindersControl { SettingsRemindersControl(self.guard.clone()) }
    pub(crate) async fn run(self) -> std::result::Result<SettingsRemindersOutput, SettingsReadFailure> {
        let Self { bridge, guard } = self;
        work_authority(&guard).map_err(SettingsReadFailure::binding)?;
        let state = bridge.state.clone();
        let retained = guard.clone();
        // The detached canonical task drains actual headers/credentials even if
        // its foreign future is abandoned. A successful body stays wiping.
        let joined = bridge.transaction(async move {
            work_authority(&retained)?;
            let mut client = SessionBridge::live_client(&state).await?;
            work_authority(&retained)?;
            client.set_operation_cancel(retained.token());
            let result = client.account().reminders_ordered().await;
            let result = match result {
                Ok(value) => {
                    // Serialize the Core ordered response directly. Its Drop
                    // wipes both payload and root-order keys on every exit.
                    let encoded = Zeroizing::new(serde_json::to_string(&value)
                        .map_err(|_| BindingError::from(Error::Protocol))?);
                    Ok(encoded)
                }
                Err(error) => Err(SettingsReadFailure::core(error)),
            };
            Ok(result)
        }).await.map_err(SettingsReadFailure::binding)?;
        work_authority(&guard).map_err(SettingsReadFailure::binding)?;
        match joined {
            Ok(encoded) => Ok(SettingsRemindersOutput { guard, encoded }),
            Err(error) => Err(error),
        }
    }
}
impl SessionBridge {
    pub(crate) fn prepare_account_reminders(&self) -> Result<PreparedSettingsReminders> {
        let guard = Arc::new(self.admit_work()?);
        Ok(PreparedSettingsReminders { bridge: self.clone(), guard })
    }
}

/// No plaintext getter, Clone, Debug or serde. Retains the original guard through
/// actual foreign allocation; opaque-handle allocation carries no plaintext.
pub(crate) struct SettingsRemindersOutput { guard: Arc<WorkGuard>, encoded: Zeroizing<String> }
impl SettingsRemindersOutput {
    pub(crate) fn encode_with<T>(self, encode: impl FnOnce(&str) -> Result<T>) -> std::result::Result<T, SettingsReadFailure> {
        work_authority(&self.guard).map_err(SettingsReadFailure::binding)?;
        let value = encode(&self.encoded).map_err(SettingsReadFailure::binding)?;
        work_authority(&self.guard).map_err(SettingsReadFailure::binding)?;
        Ok(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn bridge() -> SessionBridge {
        SessionBridge::new(r#"{"api_url":"https://api.example.invalid","app_url":"https://app.example.invalid","enhanced_privacy":false,"allow_private_operations":false}"#).unwrap_or_else(|_| panic!("synthetic bridge setup"))
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn original_cancel_before_allocator_cannot_publish_or_cancel_sibling() {
        let bridge = bridge();
        let a = bridge.prepare_account_reminders().unwrap_or_else(|_| panic!("synthetic original admission"));
        let b = bridge.prepare_account_reminders().unwrap_or_else(|_| panic!("synthetic original admission"));
        let control = a.control();
        let output = SettingsRemindersOutput { guard:a.guard.clone(), encoded:Zeroizing::new("synthetic-private-A".into()) };
        control.cancel();
        let invoked = std::sync::atomic::AtomicBool::new(false);
        let result = output.encode_with(|_| { invoked.store(true, Ordering::SeqCst); Ok(()) });
        assert_eq!(result.err().unwrap().code,"cancelled");
        assert!(!invoked.load(Ordering::SeqCst));
        assert!(work_authority(&b.guard).is_ok());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn cancellation_inside_allocator_is_checked_before_publication() {
        let bridge = bridge();
        let prepared = bridge.prepare_account_reminders().unwrap_or_else(|_| panic!("synthetic original admission"));
        let control = prepared.control();
        let output = SettingsRemindersOutput { guard:prepared.guard.clone(), encoded:Zeroizing::new("synthetic-private-A".into()) };
        let result = output.encode_with(|text| { assert_eq!(text,"synthetic-private-A"); control.cancel(); Ok("allocated opaque handle") });
        assert_eq!(result.err().unwrap().code,"cancelled");
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn output_drop_retires_only_its_original_registration() {
        let bridge = bridge();
        let a = bridge.prepare_account_reminders().unwrap_or_else(|_| panic!("synthetic original admission"));
        let b = bridge.prepare_account_reminders().unwrap_or_else(|_| panic!("synthetic original admission"));
        let output = SettingsRemindersOutput { guard:a.guard.clone(), encoded:Zeroizing::new("synthetic-private-A".into()) };
        drop(a);
        assert_eq!(bridge.state.work_operations.lock().unwrap().len(),2);
        drop(output);
        assert_eq!(bridge.state.work_operations.lock().unwrap().len(),1);
        assert!(work_authority(&b.guard).is_ok());
    }
}
