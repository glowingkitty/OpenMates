//! Explicit full-ID Personal Cookie share. The admitted read/key never crosses FFI.
use super::{work::work_authority, *};
use zeroize::Zeroize;

impl SessionBridge {
    /// Deliberate secret URL export from a fresh saved read, not cached key access.
    pub fn embeds_share_url(&self, id: String, expires_json: String, password: String) -> impl Future<Output = Result<String>> + Send + 'static {
        self.capture_embeds_share_url(id, expires_json, password)
    }

    async fn embeds_share_url_admitted(&self, id: String, expires_json: String, password: Zeroizing<String>, guard: Arc<work::WorkGuard>) -> Result<String> {
        work_authority(&guard)?;
        if id.len() != 36 || expires_json.len() > 128 {
            return Err(Error::Invalid("A full embed ID and signed integer duration are required.").into());
        }
        let expires: i64 = serde_json::from_str(&expires_json)
            .map_err(|_| BindingError::from(Error::Invalid("Invalid signed integer duration.")))?;
        let worker_guard = guard.clone();
        let state = self.state.clone();
        let joined = self.transaction(async move {
            let mut client = Self::live_client(&state).await?;
            work_authority(&worker_guard)?;
            client.set_operation_cancel(worker_guard.token());
            let result = client.saved_embed(&id).await;
            let read = match result {
                Ok(read) => read,
                Err(error) => {
                    client.set_operation_cancel(CancellationToken::new());
                    return Err(BindingError::from(error));
                }
            };
            let output = read.share_url(&client, expires, &password)?;
            work_authority(&worker_guard)?;
            read.check(&client).map_err(BindingError::from)?;
            Ok((output, read))
        }).await;
        if let Err(error) = work_authority(&guard) {
            if let Ok((mut output, _)) = joined { output.zeroize(); }
            return Err(error);
        }
        let (mut output, read) = joined?;
        let mut client = match Self::live_client(&self.state).await {
            Ok(client) => client,
            Err(error) => { output.zeroize(); return Err(error); }
        };
        if let Err(error) = work_authority(&guard)
            .and_then(|_| read.check(&client).map_err(BindingError::from))
            .and_then(|_| work_authority(&guard)) {
            output.zeroize();
            return Err(error);
        }
        // No await follows this original read/identity check and URL release.
        client.set_operation_cancel(CancellationToken::new());
        Ok(std::mem::take(&mut *output))
    }

    pub(crate) fn capture_embeds_share_url(&self, id: String, expires_json: String, password: String) -> impl Future<Output = Result<String>> + Send + 'static {
        let id = Zeroizing::new(id);
        let expires = Zeroizing::new(expires_json);
        let password = Zeroizing::new(password);
        let original = self.admit_work().map(Arc::new);
        let bridge = self.clone();
        async move {
            let guard = original?;
            work_authority(&guard)?;
            bridge.embeds_share_url_admitted(id.to_string(), expires.to_string(), password, guard).await
        }
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="session_embed_share_cancel_tests.rs"]
mod cancel_tests;

#[cfg(test)]
mod tests {
    use super::*;
    fn bridge() -> SessionBridge {
        SessionBridge::new(r#"{"api_url":"https://api.example.org","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#).unwrap_or_else(|_| panic!("synthetic bridge"))
    }
    #[tokio::test]
    async fn closed_scalar_and_no_auth_never_release_secret_or_accept_key_dto() {
        let b = bridge();
        for expires in ["true", "1.5", "9223372036854775808", r#"{"key":"synthetic-secret"}"#] {
            let error = b.embeds_share_url("33333333-3333-4333-8333-333333333333".into(), expires.into(), "synthetic-password".into()).await.err().unwrap_or_else(|| panic!("bad duration accepted"));
            assert_eq!(error.code, "invalid_argument");
            assert!(!error.message.contains("synthetic"));
        }
        let error = b.embeds_share_url("33333333-3333-4333-8333-333333333333".into(), "-7".into(), "synthetic-password".into()).await.err().unwrap_or_else(|| panic!("no auth accepted"));
        assert_eq!(error.code, "authentication");
        assert!(!error.message.contains("synthetic"));
    }
    #[tokio::test]
    async fn captured_unpolled_share_is_retired_by_cancel_and_close() {
        for close in [false, true] {
            let b = bridge();
            let original = b.capture_embeds_share_url("33333333-3333-4333-8333-333333333333".into(), "0".into(), "synthetic-password".into());
            assert_eq!(b.state.work_operations.lock().unwrap().len(), 1);
            if close { b.close().await.unwrap_or_else(|_| panic!("close")); } else { b.cancel().unwrap_or_else(|_| panic!("cancel")); }
            assert_eq!(original.await.err().map(|e| e.code), Some("cancelled"));
            assert!(b.state.work_operations.lock().unwrap().is_empty());
        }
    }
}
