//! Selected saved-chat reads retain core authority across the foreign join.
//! No new IO, credentials, cache receipt or persistence acknowledgement.
use super::work::{WorkGuard, work_authority};
use super::*;
use openmates_sdk::client::saved_chat_read::{
    SavedChatExactOptions, SavedChatReadAdmission, SavedChatReadOptions,
};
use zeroize::Zeroize;
enum ReadAdmission {
    Saved(SavedChatReadAdmission),
    Full(openmates_sdk::client::full_chat_read::FullChatReadAdmission),
}
impl ReadAdmission {
    fn check(&self,client:&Client)->openmates_sdk::Result<()> {
        match self {Self::Saved(value)=>value.check(client),Self::Full(value)=>value.check(client)}
    }
}
type PendingSavedRead = (Zeroizing<String>, ReadAdmission);
enum Request {
    Full(String),
    Window(
        String,
        openmates_sdk::client::message_window::MessageWindowOptions,
    ),
    Read(String, SavedChatReadOptions),
    Exact(String, SavedChatExactOptions),
}
impl SessionBridge {
    pub(super) async fn full_chat_read_transaction(&self, id: String) -> Result<String> {
        self.full_chat_read_prepare(id).await?.release_json()
    }
    /// Same typed one-page protocol and output, now fenced through host return.
    pub async fn chat_message_window(&self, id: String, options_json: String) -> Result<String> {
        let guard = Arc::new(self.admit_work()?);
        self.chat_message_window_admitted(id, options_json, guard).await
    }
    async fn chat_message_window_admitted(&self, id: String, options_json: String, guard: Arc<work::WorkGuard>) -> Result<String> {
        work::work_authority(&guard)?;
        use openmates_sdk::client::message_window::MessageWindowOptions;
        if options_json.len() > 4096 {
            return Err(Error::Invalid("Message window options exceed the supported size.").into());
        }
        let options: MessageWindowOptions = serde_json::from_str(&options_json)
            .map_err(|_| BindingError::from(Error::Invalid("Invalid message window options.")))?;
        self.saved_read_transaction(Request::Window(id, options), guard)
            .await
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_chat_message_window(&self, id: String, options_json: String) -> impl Future<Output = Result<String>> + Send + 'static {
        let mut id = Zeroizing::new(id);
        let mut options_json = Zeroizing::new(options_json);
        let original = self.admit_work().map(Arc::new);
        let bridge = self.clone();
        async move {
            let guard = original?;
            work::work_authority(&guard)?;
            bridge.chat_message_window_admitted(std::mem::take(&mut *id), std::mem::take(&mut *options_json), guard).await
        }
    }


    pub async fn saved_chat_read(&self, id: String, options_json: String) -> Result<String> {
        let guard = Arc::new(self.admit_work()?);
        self.saved_chat_read_admitted(id, options_json, guard).await
    }
    async fn saved_chat_read_admitted(&self, id: String, options_json: String, guard: Arc<work::WorkGuard>) -> Result<String> {
        work::work_authority(&guard)?;
        if options_json.len() > 4096 {
            return Err(Error::Invalid("Saved chat options exceed the supported size.").into());
        }
        let options: SavedChatReadOptions = serde_json::from_str(&options_json)
            .map_err(|_| BindingError::from(Error::Invalid("Invalid saved chat options.")))?;
        self.saved_read_transaction(Request::Read(id, options), guard)
            .await
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_saved_chat_read(&self, id: String, options_json: String) -> impl Future<Output = Result<String>> + Send + 'static {
        let mut id = Zeroizing::new(id);
        let mut options_json = Zeroizing::new(options_json);
        let original = self.admit_work().map(Arc::new);
        let bridge = self.clone();
        async move {
            let guard = original?;
            work::work_authority(&guard)?;
            bridge.saved_chat_read_admitted(std::mem::take(&mut *id), std::mem::take(&mut *options_json), guard).await
        }
    }

    pub async fn saved_chat_exact_message(
        &self,
        id: String,
        options_json: String,
    ) -> Result<String> {
        let guard = Arc::new(self.admit_work()?);
        self.saved_chat_exact_message_admitted(id, options_json, guard).await
    }
    async fn saved_chat_exact_message_admitted(
        &self,
        id: String,
        options_json: String, guard: Arc<work::WorkGuard>) -> Result<String> {
        work::work_authority(&guard)?;
        if options_json.len() > 4096 {
            return Err(Error::Invalid("Saved chat options exceed the supported size.").into());
        }
        let options: SavedChatExactOptions = serde_json::from_str(&options_json)
            .map_err(|_| BindingError::from(Error::Invalid("Invalid saved chat options.")))?;
        self.saved_read_transaction(Request::Exact(id, options), guard)
            .await
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_saved_chat_exact_message(&self, id: String, options_json: String) -> impl Future<Output = Result<String>> + Send + 'static {
        let mut id = Zeroizing::new(id);
        let mut options_json = Zeroizing::new(options_json);
        let original = self.admit_work().map(Arc::new);
        let bridge = self.clone();
        async move {
            let guard = original?;
            work::work_authority(&guard)?;
            bridge.saved_chat_exact_message_admitted(std::mem::take(&mut *id), std::mem::take(&mut *options_json), guard).await
        }
    }

    async fn saved_read_transaction(&self, request: Request, guard: Arc<work::WorkGuard>) -> Result<String> {
        work::work_authority(&guard)?;
        let transaction_guard = guard.clone();
        let state = self.state.clone();
        let joined = self
            .transaction(async move {
                let guard = transaction_guard;
                let mut client = Self::live_client(&state).await?;
                work_authority(&guard)?;
                client.set_operation_cancel(guard.token());
                // Full metadata reads retain the ORIGINAL admission and exact
                // operation child through the existing queued final-release check.
                // Never reset stale A's token after another operation B starts.
                if let Request::Full(id) = &request {
                    let (read,admission)=client.open_chat_with_metadata_and_admission(id).await.map_err(BindingError::from)?;
                    let output=Zeroizing::new(serde_json::to_string(&read).map_err(|_|BindingError::from(Error::Protocol))?);
                    admission.check(&client).map_err(BindingError::from)?;
                    work_authority(&guard)?;
                    return Ok((output,ReadAdmission::Full(admission)));
                }
                let encoded = match request {
                    Request::Full(_) => unreachable!("handled original full read"),
                    Request::Window(id, options) => client
                        .chat_message_window(&id, options)
                        .await
                        .and_then(|page| {
                            serde_json::to_string(&page)
                                .map(Zeroizing::new)
                                .map_err(|_| Error::Protocol)
                        }),
                    Request::Read(id, options) => {
                        client.saved_chat_read(&id, options).await.and_then(|page| {
                            serde_json::to_string(&page)
                                .map(Zeroizing::new)
                                .map_err(|_| Error::Protocol)
                        })
                    }
                    Request::Exact(id, options) => client
                        .saved_chat_exact_message(&id, options)
                        .await
                        .and_then(|page| {
                            serde_json::to_string(&page)
                                .map(Zeroizing::new)
                                .map_err(|_| Error::Protocol)
                        }),
                };
                // Accepted HTTP/credential rotation finishes before token reset.
                client.set_operation_cancel(CancellationToken::new());
                let encoded = encoded.map_err(BindingError::from)?;
                work_authority(&guard)?;
                let admission = client
                    .saved_chat_read_admission()
                    .map_err(BindingError::from)?;
                work_authority(&guard)?;
                Ok((encoded, ReadAdmission::Saved(admission)))
            })
            .await;
        self.release_saved_read(guard, joined).await
    }
    async fn release_saved_read(
        &self,
        guard: Arc<WorkGuard>,
        joined: Result<PendingSavedRead>,
    ) -> Result<String> {
        #[cfg(test)]
        let barrier = self
            .state
            .saved_read_return_barrier
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .clone();
        #[cfg(test)]
        if let Some(barrier) = &barrier {
            barrier.completed.notify_one();
            barrier.resume.notified().await;
        }
        if let Err(error) = work_authority(&guard) {
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
        // Keep this current Client mutex guard through the return expression.
        // validate_session may revoke core authority without any bridge epoch
        // changing; checking only WorkGuard would release a revoked plaintext.
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
        let allowed = work_authority(&guard)
            .and_then(|_| admission.check(&client).map_err(BindingError::from))
            .and_then(|_| work_authority(&guard));
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
pub(super) struct SavedReadReturnBarrier {
    completed: tokio::sync::Notify,
    resume: tokio::sync::Notify,
    wiped: AtomicBool,
}
#[cfg(test)]
mod tests {
    use super::*;
    async fn bridge() -> SessionBridge {
        let b=SessionBridge::new(r#"{"api_url":"http://127.0.0.1:9","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#).unwrap_or_else(|_| panic!("saved read fixture"));
        b.import_session(json!({"api_url":"http://127.0.0.1:9","session_id":"synthetic-session","cookies":{"auth_refresh_token":"synthetic-cookie"},"ws_token":null,"master_key":"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=","hashed_email":"synthetic-owner","user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.unwrap_or_else(|_| panic!("saved read import"));
        b
    }
    async fn pending(b: &SessionBridge) -> (Arc<WorkGuard>, Result<PendingSavedRead>) {
        let guard = Arc::new(
            b.admit_work()
                .unwrap_or_else(|_| panic!("saved read admission")),
        );
        let admission = b
            .state
            .client
            .lock()
            .await
            .saved_chat_read_admission()
            .unwrap_or_else(|_| panic!("saved core admission"));
        (
            guard,
            Ok((
                Zeroizing::new(r#"{"private":"synthetic-saved-content"}"#.into()),
                ReadAdmission::Saved(admission),
            )),
        )
    }
    #[tokio::test]
    async fn shared_final_release_preserves_json_and_does_not_mint_receipts() {
        let b = bridge().await;
        let (guard, result) = pending(&b).await;
        assert_eq!(
            b.release_saved_read(guard, result)
                .await
                .unwrap_or_else(|_| panic!("saved release")),
            r#"{"private":"synthetic-saved-content"}"#
        );
        assert!(
            b.state
                .work_operations
                .lock()
                .unwrap_or_else(|_| panic!("saved guard"))
                .is_empty()
        );
    }
    #[tokio::test]
    async fn post_completion_core_revocation_cancel_and_owner_change_wipe_output() {
        for change in ["core-revoke", "cancel", "replace-owner", "close"] {
            let b = bridge().await;
            let (guard, result) = pending(&b).await;
            let barrier = Arc::new(SavedReadReturnBarrier::default());
            *b.state
                .saved_read_return_barrier
                .lock()
                .unwrap_or_else(|_| panic!("saved barrier")) = Some(barrier.clone());
            let epoch = b.state.identity_epoch.load(Ordering::Acquire);
            let other = b.clone();
            let call = tokio::spawn(async move { other.release_saved_read(guard, result).await });
            barrier.completed.notified().await;
            match change {
                "core-revoke" => {
                    b.state.client.lock().await.forget_session();
                    assert_eq!(epoch, b.state.identity_epoch.load(Ordering::Acquire));
                }
                "cancel" => b.cancel().unwrap_or_else(|_| panic!("saved cancel")),
                "replace-owner" => {
                    let replacement = bridge().await;
                    let raw = replacement
                        .export_session(true)
                        .await
                        .unwrap_or_else(|_| panic!("saved export"))
                        .replace("synthetic-owner", "other-owner");
                    // export_session returns a credential snapshot envelope;
                    // import_session accepts the bare explicit Session only.
                    let exported: Value = serde_json::from_str(&raw)
                        .unwrap_or_else(|_| panic!("saved export envelope"));
                    let session = exported
                        .get("session")
                        .filter(|value| value.is_object())
                        .unwrap_or_else(|| panic!("saved export session"));
                    assert_eq!(session["hashed_email"], "other-owner");
                    b.import_session(session.to_string())
                        .await
                        .unwrap_or_else(|_| panic!("saved replacement"));
                }
                _ => b.close().await.unwrap_or_else(|_| panic!("saved close")),
            }
            barrier.resume.notify_one();
            let error = call
                .await
                .unwrap_or_else(|_| panic!("saved task"))
                .err()
                .unwrap_or_else(|| panic!("stale saved content released"));
            assert_eq!(
                error.code,
                if change == "core-revoke" {
                    "authentication"
                } else {
                    "cancelled"
                }
            );
            assert!(barrier.wiped.load(Ordering::Acquire));
            assert!(
                b.state
                    .work_operations
                    .lock()
                    .unwrap_or_else(|_| panic!("saved guard"))
                    .is_empty()
            );
        }
    }
    // Private queued-release obligation only; this synthetic pending output is
    // not a fabricated successful full read or genuine transport proof.
    #[tokio::test]
    async fn stale_full_read_a_cannot_reset_competing_operation_b() {
        let b=bridge().await;
        let (guard,result)=pending(&b).await;
        let Ok(successor)=b.admit_work() else {panic!("successor work admission");};
        let successor=Arc::new(successor);
        let next_admission={let mut client=b.state.client.lock().await;
            client.set_operation_cancel(successor.token());
            client.saved_chat_read_admission().unwrap()};
        let error=b.release_saved_read(guard,result).await.err().expect("stale A refused");
        assert_eq!(error.code,"cancelled");
        let client=b.state.client.lock().await;
        assert!(next_admission.check(&client).is_ok());
        assert!(work_authority(&successor).is_ok());
    }

    #[tokio::test]
    async fn full_read_queued_original_gate_revoked_after_replacement_wipes_output() {
        let b=bridge().await;
        let (guard,_discard)=pending(&b).await;
        let allowed=Arc::new(AtomicBool::new(true));let original=allowed.clone();
        let admission={let mut client=b.state.client.lock().await;
            client.set_private_operation_gate(Some(Arc::new(move||if original.load(Ordering::Acquire){Ok(())}else{Err(Error::Forbidden)})));
            client.full_chat_read_admission("22222222-2222-4222-8222-222222222222").unwrap()};
        let barrier=Arc::new(SavedReadReturnBarrier::default());
        *b.state.saved_read_return_barrier.lock().unwrap()=Some(barrier.clone());
        let other=b.clone();let call=tokio::spawn(async move{other.release_saved_read(guard,Ok((Zeroizing::new("synthetic-full-output".into()),ReadAdmission::Full(admission)))).await});
        barrier.completed.notified().await;
        b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(||Ok(()))));
        allowed.store(false,Ordering::Release);barrier.resume.notify_one();
        let Ok(result)=call.await else {panic!("full policy join");};
        assert!(result.is_err());assert!(barrier.wiped.load(Ordering::Acquire));
    }
    #[tokio::test]
    async fn full_read_original_policy_ordinary_queued_release_is_exact() {
        let b=bridge().await;let (guard,_discard)=pending(&b).await;
        let admission=b.state.client.lock().await.full_chat_read_admission("22222222-2222-4222-8222-222222222222").unwrap();
        let result=b.release_saved_read(guard,Ok((Zeroizing::new("synthetic-full-output".into()),ReadAdmission::Full(admission)))).await;
        let Ok(value)=result else {panic!("ordinary full release");};assert_eq!(value,"synthetic-full-output");
    }

}
