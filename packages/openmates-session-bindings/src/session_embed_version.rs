//! Explicit Cookie version-content delegation; no CLI/credential discovery.
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement
use super::{work::work_authority, *};
use zeroize::Zeroize;
pub(super) fn wipe(value: &mut Value) {
    match value {
        Value::String(s) => s.zeroize(),
        Value::Array(a) => {
            for v in a {
                wipe(v)
            }
        }
        Value::Object(o) => {
            for (mut key, mut v) in std::mem::take(o) {
                key.zeroize();
                wipe(&mut v)
            }
        }
        _ => {}
    }
    *value = Value::Null;
}
struct Pending(Value);
impl Drop for Pending {
    fn drop(&mut self) {
        wipe(&mut self.0)
    }
}
impl SessionBridge {
    pub async fn embeds_version_content(&self, id: String, version_json: String) -> Result<String> {
        let guard = Arc::new(self.admit_work()?);
        self.embeds_version_content_admitted(id, version_json, guard).await
    }
    async fn embeds_version_content_admitted(&self, id: String, version_json: String, guard: Arc<work::WorkGuard>) -> Result<String> {
        work::work_authority(&guard)?;
        if id.len() != 36 || version_json.len() > 128 {
            return Err(
                Error::Invalid("A full embed ID and safe integer version are required.").into(),
            );
        }
        let version: i64 = serde_json::from_str(&version_json)
            .map_err(|_| BindingError::from(Error::Invalid("Invalid integer version.")))?;
        let worker_guard = guard.clone();
        let state = self.state.clone();
        let joined = self
            .transaction(async move {
                let mut client = Self::live_client(&state).await?;
                work_authority(&worker_guard)?;
                client.set_operation_cancel(worker_guard.token());
                let result = client
                    .embed_version_content_with_admission(&id, version)
                    .await;
                let (value, admission) = match result {
                    Ok(value) => value,
                    Err(error) => {
                        client.set_operation_cancel(CancellationToken::new());
                        return Err(BindingError::from(error));
                    }
                };
                let value = Pending(value);
                let output = Zeroizing::new(
                    serde_json::to_string(&value.0)
                        .map_err(|_| BindingError::from(Error::Protocol))?,
                );
                if output.len() > 64 * 1024 * 1024 {
                    return Err(Error::Invalid("Version output exceeds the supported size.").into());
                }
                work_authority(&worker_guard)?;
                admission.check(&client).map_err(BindingError::from)?;
                Ok((output, admission))
            })
            .await;
        if let Err(error) = work_authority(&guard) {
            if let Ok((mut output, _)) = joined {
                output.zeroize();
            }
            return Err(error);
        }
        let (mut output, admission) = joined?;
        let mut client = match Self::live_client(&self.state).await {
            Ok(client) => client,
            Err(error) => {
                output.zeroize();
                return Err(error);
            }
        };
        if let Err(error) = work_authority(&guard)
            .and_then(|_| admission.check(&client).map_err(BindingError::from))
            .and_then(|_| work_authority(&guard))
        {
            output.zeroize();
            return Err(error);
        }
        // This exact child remains registered until the locked final check.
        // Reset only our accepted completed call, synchronously before return.
        client.set_operation_cancel(CancellationToken::new());
        Ok(std::mem::take(&mut *output))
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_embeds_version_content(&self, id: String, version_json: String) -> impl Future<Output = Result<String>> + Send + 'static {
        let mut id = Zeroizing::new(id);
        let mut version_json = Zeroizing::new(version_json);
        let original = self.admit_work().map(Arc::new);
        let bridge = self.clone();
        async move {
            let guard = original?;
            work::work_authority(&guard)?;
            bridge.embeds_version_content_admitted(std::mem::take(&mut *id), std::mem::take(&mut *version_json), guard).await
        }
    }

}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn scalar_schema_and_missing_credentials_are_explicit_and_sanitized() {
        let bridge=SessionBridge::new(r#"{"api_url":"https://api.example.org","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#).unwrap_or_else(|_|panic!("synthetic bridge"));
        for input in ["true", "1.5", "\"synthetic-private-value\""] {
            let error = bridge
                .embeds_version_content("33333333-3333-4333-8333-333333333333".into(), input.into())
                .await
                .err()
                .unwrap_or_else(|| panic!("bad scalar accepted"));
            assert_eq!(error.code, "invalid_argument");
            assert!(!error.message.contains("synthetic-private-value"));
        }
        let error = bridge
            .embeds_version_content("33333333-3333-4333-8333-333333333333".into(), "1".into())
            .await
            .err()
            .unwrap_or_else(|| panic!("missing credentials accepted"));
        assert_eq!(error.code, "authentication");
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="session_embed_version_cancel_tests.rs"]
mod cancel_tests;
