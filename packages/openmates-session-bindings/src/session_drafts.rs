//! Explicit Cookie-session draft calls. Reuses the shared Rust owner/key/cache
//! policy and essential/work admission; no CLI, profiles, terminal or fallback.
use super::essential::EssentialGuard;
use super::*;
use zeroize::Zeroize;
const MAX_OUTPUT: usize = 64 * 1024 * 1024;
#[derive(Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionDraftReadOptions {
    #[serde(default)]
    pub force_refresh: bool,
}
fn options(input: String) -> Result<SessionDraftReadOptions> {
    let input = Zeroizing::new(input);
    if input.len() > 4096 {
        return Err(Error::Invalid("Draft options exceed the supported size.").into());
    }
    serde_json::from_str(&input).map_err(|_| Error::Invalid("Invalid typed draft options.").into())
}
fn encoded<T: Serialize>(value: &T) -> openmates_sdk::Result<Zeroizing<String>> {
    let output = Zeroizing::new(serde_json::to_string(value).map_err(|_| Error::Protocol)?);
    if output.len() > MAX_OUTPUT {
        return Err(Error::Invalid("Draft output exceeds the supported size."));
    }
    Ok(output)
}
fn wipe_record(value: &mut openmates_sdk::sdk_drafts::DraftRecord) {
    value.markdown.zeroize();
    if let Some(preview) = &mut value.preview {
        preview.zeroize();
    }
}
fn encoded_records(
    mut records: Vec<openmates_sdk::sdk_drafts::DraftRecord>,
) -> openmates_sdk::Result<Zeroizing<String>> {
    let result = encoded(&records);
    for record in &mut records {
        wipe_record(record);
    }
    result
}
fn encoded_record(
    mut record: Option<openmates_sdk::sdk_drafts::DraftRecord>,
) -> openmates_sdk::Result<Zeroizing<String>> {
    let result = encoded(&record);
    if let Some(record) = &mut record {
        wipe_record(record);
    }
    result
}
enum Request {
    CachedList,
    List(SessionDraftReadOptions),
    Get(Zeroizing<String>, SessionDraftReadOptions),
    Sync,
}
impl SessionBridge {
    pub async fn drafts_list_cached(&self) -> Result<String> {
        let guard = EssentialGuard::new(self, false)?;
        self.drafts_list_cached_admitted(guard).await
    }
    async fn drafts_list_cached_admitted(&self, guard: Arc<essential::EssentialGuard>) -> Result<String> {
        guard.check()?;
        self.draft_transaction(Request::CachedList, guard).await
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_drafts_list_cached(&self) -> impl Future<Output = Result<String>> + Send + 'static {
        let original = essential::EssentialGuard::new(self, false);
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.drafts_list_cached_admitted(guard).await
        }
    }

    pub async fn drafts_list(&self, options_json: String) -> Result<String> {
        let guard = EssentialGuard::new(self, false)?;
        self.drafts_list_admitted(options_json, guard).await
    }
    async fn drafts_list_admitted(&self, options_json: String, guard: Arc<essential::EssentialGuard>) -> Result<String> {
        guard.check()?;
        self.draft_transaction(Request::List(options(options_json)?), guard)
            .await
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_drafts_list(&self, options_json: String) -> impl Future<Output = Result<String>> + Send + 'static {
        let mut options_json = Zeroizing::new(options_json);
        let original = essential::EssentialGuard::new(self, false);
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.drafts_list_admitted(std::mem::take(&mut *options_json), guard).await
        }
    }

    pub async fn drafts_get(&self, id: String, options_json: String) -> Result<String> {
        let guard = EssentialGuard::new(self, false)?;
        self.drafts_get_admitted(id, options_json, guard).await
    }
    async fn drafts_get_admitted(&self, id: String, options_json: String, guard: Arc<essential::EssentialGuard>) -> Result<String> {
        guard.check()?;
        if id.len() > 128 {
            return Err(Error::Invalid("Invalid chat ID.").into());
        }
        self.draft_transaction(Request::Get(Zeroizing::new(id), options(options_json)?), guard)
            .await
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_drafts_get(&self, id: String, options_json: String) -> impl Future<Output = Result<String>> + Send + 'static {
        let mut id = Zeroizing::new(id);
        let mut options_json = Zeroizing::new(options_json);
        let original = essential::EssentialGuard::new(self, false);
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.drafts_get_admitted(std::mem::take(&mut *id), std::mem::take(&mut *options_json), guard).await
        }
    }

    pub async fn drafts_sync(&self) -> Result<String> {
        let guard = EssentialGuard::new(self, false)?;
        self.drafts_sync_admitted(guard).await
    }
    async fn drafts_sync_admitted(&self, guard: Arc<essential::EssentialGuard>) -> Result<String> {
        guard.check()?;
        self.draft_transaction(Request::Sync, guard).await
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_drafts_sync(&self) -> impl Future<Output = Result<String>> + Send + 'static {
        let original = essential::EssentialGuard::new(self, false);
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.drafts_sync_admitted(guard).await
        }
    }

    async fn draft_transaction(&self, request: Request, guard: Arc<essential::EssentialGuard>) -> Result<String> {
        guard.check()?;
        let transaction_guard = guard.clone();
        let state = self.state.clone();
        let joined = self
            .transaction(async move {
                let guard = transaction_guard;
                let mut client = Self::live_client(&state).await?;
                guard.check()?;
                client.set_operation_cancel(guard.token());
                let result = match request {
                    Request::CachedList => client.list_cached_drafts().and_then(encoded_records),
                    Request::List(options) => client
                        .list_drafts(options.force_refresh)
                        .await
                        .and_then(encoded_records),
                    Request::Get(id, options) => client
                        .get_draft(&id, options.force_refresh)
                        .await
                        .and_then(encoded_record),
                    Request::Sync => client
                        .reconcile_draft_versions()
                        .await
                        .and_then(|value| encoded(&value)),
                };
                // Complete accepted transport/credential rotation before resetting the
                // lane. The guard's own token remains registered through host return.
                client.set_operation_cancel(CancellationToken::new());
                let output = result.map_err(BindingError::from)?;
                guard.check()?;
                let admission = client.draft_read_admission().map_err(BindingError::from)?;
                Ok((output, admission))
            })
            .await;
        #[cfg(test)]
        let barrier = self
            .state
            .draft_return_barrier
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .clone();
        #[cfg(test)]
        if let Some(barrier) = &barrier {
            barrier.completed.notify_one();
            barrier.resume.notified().await;
        }
        // A queued context change or cancellation masks stale errors too. This
        // does not manufacture a host cache-publish or credential-save receipt.
        if let Err(error) = guard.check() {
            if let Ok((mut output, _)) = joined {
                output.zeroize();
                #[cfg(test)]
                if let Some(barrier) = &barrier {
                    barrier.wiped.store(output.is_empty(), Ordering::Release);
                }
            }
            return Err(error);
        }
        let (mut output, admission) = joined?;
        // Bridge epochs do not describe authoritative Client revocation performed
        // by validate_session/transport. Keep the current Client mutex through
        // the return expression and recheck its opaque core owner/key/generation
        // fence together with bridge cancellation before releasing plaintext.
        let client = match Self::live_client(&self.state).await {
            Ok(client) => client,
            Err(error) => {
                output.zeroize();
                #[cfg(test)]
                if let Some(barrier) = &barrier {
                    barrier.wiped.store(output.is_empty(), Ordering::Release);
                }
                return Err(error);
            }
        };
        let allowed = guard
            .check()
            .and_then(|_| admission.check(&client).map_err(BindingError::from))
            .and_then(|_| guard.check());
        if let Err(error) = allowed {
            output.zeroize();
            #[cfg(test)]
            if let Some(barrier) = &barrier {
                barrier.wiped.store(output.is_empty(), Ordering::Release);
            }
            return Err(error);
        }
        Ok(std::mem::take(&mut *output))
    }
}
#[cfg(test)]
#[derive(Default)]
pub(super) struct DraftReturnBarrier {
    completed: tokio::sync::Notify,
    resume: tokio::sync::Notify,
    wiped: AtomicBool,
}
#[cfg(test)]
mod tests {
    use super::*;
    fn bridge(allow: bool) -> SessionBridge {
        SessionBridge::new(&json!({"api_url":"http://127.0.0.1:9","app_url":null,"enhanced_privacy":false,"allow_private_operations":allow}).to_string()).unwrap_or_else(|_|panic!("draft binding fixture"))
    }
    fn session(owner: &str) -> String {
        json!({"api_url":"http://127.0.0.1:9","session_id":"synthetic-session","cookies":{"auth_refresh_token":"synthetic-cookie"},"ws_token":null,"master_key":"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=","hashed_email":owner,"user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()
    }
    #[test]
    fn closed_options_cannot_select_owner_team_or_credentials() {
        for raw in [
            "null",
            r#"{"force_refresh":"true"}"#,
            r#"{"owner":"foreign"}"#,
            r#"{"team_id":"foreign"}"#,
            r#"{"api_key":"synthetic"}"#,
        ] {
            assert!(options(raw.into()).is_err());
        }
        assert!(
            !options("{}".into())
                .unwrap_or_else(|_| panic!("draft binding fixture"))
                .force_refresh
        );
        assert!(
            options(r#"{"force_refresh":true}"#.into())
                .unwrap_or_else(|_| panic!("draft options"))
                .force_refresh
        );
    }
    #[tokio::test]
    async fn absence_and_explicit_policy_refuse_without_network() {
        let b = bridge(true);
        assert_eq!(
            b.drafts_get("11111111-1111-4111-8111-111111111111".into(), "{}".into())
                .await
                .err()
                .map(|e| e.code),
            Some("authentication")
        );
        let b = bridge(false);
        b.import_session(session("synthetic-owner"))
            .await
            .unwrap_or_else(|_| panic!("draft binding import"));
        assert_eq!(
            b.drafts_sync().await.err().map(|e| e.code),
            Some("forbidden")
        );
    }
    #[tokio::test]
    async fn completed_result_cancel_or_identity_replacement_is_wiped_before_host_return() {
        for replacement in [false, true] {
            let b = bridge(true);
            b.import_session(session("synthetic-owner"))
                .await
                .unwrap_or_else(|_| panic!("draft binding import"));
            let barrier = Arc::new(DraftReturnBarrier::default());
            *b.state
                .draft_return_barrier
                .lock()
                .unwrap_or_else(|_| panic!("draft binding fixture")) = Some(barrier.clone());
            let other = b.clone();
            let call = tokio::spawn(async move { other.drafts_sync().await });
            barrier.completed.notified().await;
            if replacement {
                b.import_session(session("other-owner"))
                    .await
                    .unwrap_or_else(|_| panic!("draft binding import"));
            } else {
                b.cancel()
                    .unwrap_or_else(|_| panic!("draft binding fixture"));
            }
            barrier.resume.notify_one();
            assert_eq!(call.await.unwrap().err().map(|e| e.code), Some("cancelled"));
            assert!(barrier.wiped.load(Ordering::Acquire));
            assert!(
                b.state
                    .work_operations
                    .lock()
                    .unwrap_or_else(|_| panic!("draft binding fixture"))
                    .is_empty()
            );
        }
    }
    #[tokio::test]
    async fn authoritative_core_revocation_after_completion_wipes_pending_output() {
        let b = bridge(true);
        b.import_session(session("synthetic-owner"))
            .await
            .unwrap_or_else(|_| panic!("draft binding import"));
        let barrier = Arc::new(DraftReturnBarrier::default());
        *b.state
            .draft_return_barrier
            .lock()
            .unwrap_or_else(|_| panic!("draft barrier")) = Some(barrier.clone());
        // Observe the existing bridge authority through its supported guard;
        // Registry's private epoch is owned by the essential module.
        let proof_guard = EssentialGuard::new(&b, false)
            .unwrap_or_else(|_| panic!("draft live bridge guard"));
        let identity = b.state.identity_epoch.load(Ordering::Acquire);
        let other = b.clone();
        let call = tokio::spawn(async move { other.drafts_sync().await });
        barrier.completed.notified().await;
        // Exact core hook used by authoritative failed validate_session; unlike
        // import/cancel, this intentionally leaves bridge epochs unchanged.
        b.state.client.lock().await.forget_session();
        assert!(proof_guard.check().is_ok(), "core revocation must leave the old bridge guard live");
        assert_eq!(identity, b.state.identity_epoch.load(Ordering::Acquire));
        barrier.resume.notify_one();
        let error = call
            .await
            .unwrap_or_else(|_| panic!("draft task"))
            .err()
            .unwrap_or_else(|| panic!("revoked draft output released"));
        assert_eq!(error.code, "authentication");
        assert!(barrier.wiped.load(Ordering::Acquire));
        assert!(proof_guard.check().is_ok(), "the completed return must fail on core authority, not bridge cancellation");
        assert_eq!(identity, b.state.identity_epoch.load(Ordering::Acquire));
        // This observer admits one independent work item. Drop it before the
        // original cleanup assertion so only the call's registry cleanup counts.
        drop(proof_guard);
        assert!(
            b.state
                .work_operations
                .lock()
                .unwrap_or_else(|_| panic!("draft work"))
                .is_empty()
        );
    }
}
