//! Explicit API-key embed SDK: encrypted reads, restore, application preview,
//! encrypted Project links and fragment-only sharing. No installed credentials,
//! cookie fallback, account key persistence or automatic mutation retries.
use crate::{Error, OpenMates, Result};
use reqwest::Method;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::time::Duration;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

pub struct Embeds<'a> {
    client: &'a mut OpenMates,
}
impl<'a> Embeds<'a> {
    pub(crate) fn new(client: &'a mut OpenMates) -> Self {
        Self { client }
    }
    async fn request(&self, method: Method, path: String, body: Option<Value>) -> Result<Value> {
        if self.client.is_anonymous() {
            return Err(Error::Authentication);
        }
        self.client.verify_private_operation()?;
        self.client
            .task_request(method, &path, body, false, None)
            .await
    }
    async fn read(&self, path: String) -> Result<Value> {
        self.request(Method::GET, path, None).await
    }
    /// Return encrypted embed and wrappers unchanged. The endpoint enforces
    /// owner scope; an opaque wrapper is never interpreted as authorization.
    pub async fn show(&self, embed_id: &str) -> Result<Value> {
        self.read(format!("/v1/sdk/embeds/{}", segment(embed_id)?))
            .await
    }
    /// Preserve all server revision fields and server version ordering.
    pub async fn versions(&self, embed_id: &str) -> Result<Value> {
        self.read(format!("/v1/sdk/embeds/{}/versions", segment(embed_id)?))
            .await
    }
    /// Signed versions retain the maintained SDKs' server validation semantics.
    pub async fn version(&self, embed_id: &str, version: i64) -> Result<Value> {
        self.read(format!(
            "/v1/sdk/embeds/{}/versions/{version}",
            segment(embed_id)?
        ))
        .await
    }

    /// Additive plaintext read. Existing `version` keeps its opaque encrypted
    /// response. This Personal account-key slice never interprets Project grants
    /// as account keys and does not publish snapshots or persistence receipts.
    pub async fn version_content(&mut self, embed_id: &str, version: i64) -> Result<Value> {
        if !(1..=9_007_199_254_740_991).contains(&version) {
            return Err(Error::Invalid("Supply a positive safe integer version."));
        }
        let cancel = self.client.operation_cancel_token();
        let mut response = PendingVersionResponse(
            cancel_preview_request(cancel.clone(), self.version(embed_id, version)).await?,
        );
        if response["embed_id"].as_str() != Some(embed_id)
            || response["version_number"].as_i64() != Some(version)
        {
            return Err(Error::Protocol);
        }
        let content = if let Some(content) = response["content"].as_str() {
            if content.len() > VERSION_CONTENT_LIMIT {
                return Err(Error::Protocol);
            }
            Zeroizing::new(content.to_owned())
        } else {
            let rows = response["rows"]
                .as_array()
                .filter(|rows| !rows.is_empty() && rows.len() <= VERSION_ROW_LIMIT)
                .ok_or(Error::Protocol)?;
            if rows.last().and_then(|row| row["version_number"].as_i64()) != Some(version)
                || rows.iter().any(|row| {
                    row["version_number"]
                        .as_i64()
                        .is_none_or(|n| n < 1 || n > version)
                })
            {
                return Err(Error::Protocol);
            }
            let shown = cancel_preview_request(cancel.clone(), self.show(embed_id)).await?;
            if shown["embed"]["embed_id"].as_str() != Some(embed_id) {
                return Err(Error::Forbidden);
            }
            let key = cancel_preview_request(
                cancel.clone(),
                self.account_embed_key(embed_id, &shown, true),
            )
            .await?;
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            reconstruct_version_rows_with_cancel(rows, &key, &cancel)?
        };
        self.client.verify_private_operation()?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        response["content"] = json!(content.as_str());
        Ok(std::mem::take(&mut response.0))
    }
    // Reuses exactly the pre-existing share key policy: first matching
    // master/chat wrapper, exact embed hash, account master only, no grants.
    async fn account_embed_key(
        &mut self,
        embed_id: &str,
        shown: &Value,
        version_content: bool,
    ) -> Result<Zeroizing<[u8; 32]>> {
        let master = self.client.master_key().await?;
        let hash = format!("{:x}", Sha256::digest(embed_id.as_bytes()));
        let rows = shown["embed_keys"].as_array().ok_or(Error::Forbidden)?;
        for kind in ["master", "chat"] {
            if let Some(row) = rows
                .iter()
                .find(|r| r["hashed_embed_id"] == hash && r["key_type"] == kind)
            {
                if let Some(encoded) = row["encrypted_embed_key"].as_str() {
                    if let Ok(raw) = crate::crypto::decrypt_bytes(encoded, &master) {
                        let bytes: [u8; 32] = raw.as_slice().try_into().map_err(|_| {
                            if version_content {
                                Error::Forbidden
                            } else {
                                Error::Crypto
                            }
                        })?;
                        return Ok(Zeroizing::new(bytes));
                    }
                }
            }
        }
        Err(Error::Forbidden)
    }
    /// Restore once, only after caller confirmation; never replay ambiguous writes.
    pub async fn restore_version(
        &self,
        embed_id: &str,
        version: i64,
        confirmed: bool,
    ) -> Result<Value> {
        if !confirmed {
            return Err(Error::Invalid(
                "Restoring an embed version requires explicit confirmation.",
            ));
        }
        self.request(
            Method::POST,
            format!(
                "/v1/sdk/embeds/{}/versions/{version}/restore",
                segment(embed_id)?
            ),
            Some(json!({})),
        )
        .await
    }
    pub fn preview(&mut self) -> EmbedPreview<'_> {
        EmbedPreview {
            client: self.client,
        }
    }
    /// Fragment-only local share generation; no share key is sent to the server.
    pub async fn share(&mut self, embed_id: &str, expires: i64, password: &str) -> Result<Value> {
        let shown = self.show(embed_id).await?;
        if shown["embed"]["embed_id"]
            .as_str()
            .is_some_and(|id| id != embed_id)
        {
            return Err(Error::Forbidden);
        }
        let key = self.account_embed_key(embed_id, &shown, false).await?;
        let blob = crate::Client::sdk_embed_share_blob(embed_id, &key, expires, password)?;
        let mut origin =
            url::Url::parse(&self.client.work_origin()).map_err(|_| Error::Protocol)?;
        if let Some(host) = origin.host_str().map(str::to_owned)
            && let Some(suffix) = host.strip_prefix("api.")
        {
            origin
                .set_host(Some(&format!("app.{suffix}")))
                .map_err(|_| Error::Protocol)?;
        }
        origin.set_port(None).map_err(|_| Error::Protocol)?;
        Ok(
            json!({"url":format!("{}/share/embed/{}#key={}",origin.origin().ascii_serialization(),embed_id,blob)}),
        )
    }
    /// Personal Project link creation reuses the shared resolver and crypto.
    pub async fn add_to_project(
        &mut self,
        embed_id: &str,
        project: &str,
        folder: Option<&str>,
    ) -> Result<Value> {
        if self.client.is_anonymous() {
            return Err(Error::Authentication);
        }
        self.client.verify_private_operation()?;
        segment(embed_id)?;
        let (id, key) = self
            .client
            .projects()
            .sdk_embed_link_context(project)
            .await?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| Error::Protocol)?
            .as_secs();
        let metadata = serde_json::to_string(
            &json!({"storage":"save_only_in_openmates","source":"sdk_add_to_project"}),
        )?;
        let body = json!({"project_item_id":uuid::Uuid::new_v4(),"folder_id":folder,"item_type":"embed","target_id":embed_id,"target_id_encrypted":crate::crypto::encrypt_combined(embed_id,&key)?,"encrypted_display_name":crate::crypto::encrypt_combined(embed_id,&key)?,"encrypted_note":crate::crypto::encrypt_combined("",&key)?,"encrypted_metadata":crate::crypto::encrypt_combined(&metadata,&key)?,"created_at":now,"updated_at":now,"position":now});
        let response = self
            .request(
                Method::POST,
                format!("/v1/projects/{}/items", segment(&id)?),
                Some(body),
            )
            .await?;
        response
            .get("item")
            .filter(|v| v.is_object())
            .cloned()
            .ok_or(Error::Protocol)
    }
    /// Unlink the exact target only; the linked embed is never deleted.
    pub async fn remove_from_project(&mut self, embed_id: &str, project: &str) -> Result<Value> {
        if self.client.is_anonymous() {
            return Err(Error::Authentication);
        }
        self.client.verify_private_operation()?;
        segment(embed_id)?;
        // UUID selectors need no key. Names/slugs reuse the shared personal resolver.
        let id = if uuid::Uuid::parse_str(project).is_ok() {
            project.to_owned()
        } else {
            self.client
                .projects()
                .sdk_embed_link_context(project)
                .await?
                .0
        };
        let query = url::form_urlencoded::Serializer::new(String::new())
            .append_pair("item_type", "embed")
            .append_pair("target_id", embed_id)
            .finish();
        let response = self
            .request(
                Method::DELETE,
                format!("/v1/projects/{}/items?{query}", segment(&id)?),
                None,
            )
            .await?;
        Ok(
            json!({"deleted":response["deleted"]==true,"deleted_count":response["deleted_count"].as_u64().unwrap_or(0)}),
        )
    }
}
#[derive(Default)]
pub struct PreviewStartOptions {
    pub shared_context: Option<String>,
    pub requested_runtime: Option<String>,
    pub source_message_id: Option<String>,
    pub wait: bool,
    pub timeout: Option<Duration>,
}
/// A local preview deadline is distinct from a received server HTTP response.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PreviewStartError {
    ClientError(Error),
    LocalDeadline,
}
impl PreviewStartError {
    /// SDK-compatible synthetic status for a LOCAL deadline, never HTTP evidence.
    pub fn local_status_code(&self) -> Option<u16> {
        if matches!(self, Self::LocalDeadline) {
            Some(408)
        } else {
            None
        }
    }
}
impl From<Error> for PreviewStartError {
    fn from(error: Error) -> Self {
        Self::ClientError(error)
    }
}
impl std::fmt::Display for PreviewStartError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ClientError(error) => std::fmt::Display::fmt(error, f),
            Self::LocalDeadline => {
                f.write_str("Application preview did not reach running state before timeout.")
            }
        }
    }
}
impl std::error::Error for PreviewStartError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::ClientError(error) => Some(error),
            Self::LocalDeadline => None,
        }
    }
}
pub struct EmbedPreview<'a> {
    client: &'a mut OpenMates,
}
impl EmbedPreview<'_> {
    async fn request(&self, method: Method, path: String, body: Option<Value>) -> Result<Value> {
        if self.client.is_anonymous() {
            return Err(Error::Authentication);
        }
        self.client.verify_private_operation()?;
        cancel_preview_request(
            self.client.operation_cancel_token(),
            self.client.task_request(method, &path, body, false, None),
        )
        .await
    }
    /// Preserve local deadline provenance; local_status_code() is SDK-compatible
    /// metadata and never asserts that an HTTP response was received.
    pub async fn start(
        &mut self,
        embed_id: &str,
        chat_id: &str,
        options: PreviewStartOptions,
    ) -> std::result::Result<Value, PreviewStartError> {
        let cancel = self.client.operation_cancel_token();
        if cancel.is_cancelled() {
            return Err(Error::Cancelled.into());
        }
        let mut body = json!({"chat_id":chat_id});
        for (name, value) in [
            ("shared_context", &options.shared_context),
            ("requested_runtime", &options.requested_runtime),
            ("source_message_id", &options.source_message_id),
        ] {
            if let Some(value) = value.as_deref().filter(|s| !s.is_empty()) {
                body[name] = json!(value);
            }
        }
        let started = self
            .request(
                Method::POST,
                format!("/v1/applications/{}/preview/start", segment(embed_id)?),
                Some(body),
            )
            .await?;
        if !options.wait {
            return Ok(started);
        }
        let session = started["session_id"].as_str().ok_or(Error::Protocol)?;
        let deadline = crate::platform::time::Instant::now()
            .checked_add(options.timeout.unwrap_or(Duration::from_secs(120)))
            .ok_or(Error::Invalid("Preview timeout is too large."))?;
        loop {
            if crate::platform::time::Instant::now() >= deadline {
                return Err(PreviewStartError::LocalDeadline);
            }
            let status = self.status(session).await?;
            if ["running", "failed", "timeout", "cancelled", "stopped"]
                .contains(&status["status"].as_str().unwrap_or(""))
            {
                return Ok(status);
            }
            tokio::select! { _=cancel.cancelled()=>return Err(Error::Cancelled.into()), _=crate::platform::time::sleep(Duration::from_secs(1))=>{} }
        }
    }
    pub async fn status(&self, session_id: &str) -> Result<Value> {
        self.request(
            Method::GET,
            format!("/v1/applications/preview/{}", segment(session_id)?),
            None,
        )
        .await
    }
    pub async fn open(&self, session_id: &str) -> Result<Value> {
        self.request(
            Method::POST,
            format!("/v1/applications/preview/{}/open", segment(session_id)?),
            Some(json!({})),
        )
        .await
    }
    pub async fn stop(&self, session_id: &str) -> Result<Value> {
        self.request(
            Method::POST,
            format!("/v1/applications/preview/{}/stop", segment(session_id)?),
            Some(json!({})),
        )
        .await
    }
}

// Apply cancellation to pending preview IO and recheck before returning a result.
// A terminal server state cannot turn a locally cancelled operation into success.
async fn cancel_preview_request<T, F>(
    cancel: tokio_util::sync::CancellationToken,
    request: F,
) -> Result<T>
where
    F: std::future::Future<Output = Result<T>>,
{
    let result = tokio::select! {
        biased;
        _ = cancel.cancelled() => return Err(Error::Cancelled),
        result = request => result,
    };
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    result
}

struct PendingVersionResponse(Value);
impl std::ops::Deref for PendingVersionResponse {
    type Target = Value;
    fn deref(&self) -> &Value {
        &self.0
    }
}
impl std::ops::DerefMut for PendingVersionResponse {
    fn deref_mut(&mut self) -> &mut Value {
        &mut self.0
    }
}
impl Drop for PendingVersionResponse {
    fn drop(&mut self) {
        crate::model::zeroize_json(&mut self.0);
    }
}
const VERSION_CONTENT_LIMIT: usize = 16 * 1024 * 1024;
const VERSION_ROW_LIMIT: usize = 10_000;
/// Stateless local reconstruction, shared with the foreign SDK bindings. A key
/// authenticates ciphertext only: this helper grants no server/account access.
/// The supplied rows must already belong to the caller's authorized response.
pub fn reconstruct_version_rows(rows: &[Value], key: &[u8; 32]) -> Result<Zeroizing<String>> {
    reconstruct_version_rows_with_cancel(rows, key, &CancellationToken::new())
}
pub(crate) fn reconstruct_version_rows_with_cancel(
    rows: &[Value],
    key: &[u8; 32],
    cancel: &CancellationToken,
) -> Result<Zeroizing<String>> {
    if rows.is_empty() || rows.len() > VERSION_ROW_LIMIT {
        return Err(Error::Protocol);
    }
    let mut sorted = rows.iter().collect::<Vec<_>>();
    sorted.sort_by_key(|row| row["version_number"].as_u64().unwrap_or(0));
    let mut expected = sorted[0]["version_number"]
        .as_u64()
        .filter(|n| *n > 0)
        .ok_or(Error::Protocol)?;
    let mut content: Option<Zeroizing<String>> = None;
    let mut cipher_bytes = 0usize;
    for row in sorted {
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let version = row["version_number"]
            .as_u64()
            .filter(|n| *n > 0 && *n <= 9_007_199_254_740_991)
            .ok_or(Error::Protocol)?;
        if version != expected {
            return Err(Error::Protocol);
        }
        expected = expected.checked_add(1).ok_or(Error::Protocol)?;
        if row
            .get("encrypted_snapshot")
            .is_some_and(|value| !value.is_null() && !value.is_string())
        {
            return Err(Error::Protocol);
        }
        let snapshot = row["encrypted_snapshot"].as_str().filter(|s| !s.is_empty());
        let encrypted = snapshot
            .or_else(|| row["encrypted_patch"].as_str().filter(|s| !s.is_empty()))
            .ok_or(Error::Protocol)?;
        cipher_bytes = cipher_bytes
            .checked_add(encrypted.len())
            .ok_or(Error::Protocol)?;
        if cipher_bytes > 64 * 1024 * 1024 {
            return Err(Error::Protocol);
        }
        let decoded = Zeroizing::new(crate::crypto::decrypt_combined(encrypted, key)?);
        if decoded.len() > VERSION_CONTENT_LIMIT {
            return Err(Error::Protocol);
        }
        content = Some(if snapshot.is_some() {
            decoded
        } else {
            let old = content.as_ref().ok_or(Error::Protocol)?;
            Zeroizing::new(crate::client::apply_embed_version_patch(old, &decoded)?)
        });
    }
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    content.ok_or(Error::Protocol)
}

fn segment(id: &str) -> Result<String> {
    if id.is_empty() || matches!(id, "." | "..") || id.chars().any(char::is_control) {
        return Err(Error::Invalid("Supply a nonempty embed identifier."));
    }
    let mut result = String::with_capacity(id.len());
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    for byte in id.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.!~*'()".contains(&byte) {
            result.push(char::from(byte));
        } else {
            result.push('%');
            result.push(char::from(HEX[(byte >> 4) as usize]));
            result.push(char::from(HEX[(byte & 15) as usize]));
        }
    }
    Ok(result)
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ApiKey, ClientOptions, SdkCredentials, SdkOptions};
    #[tokio::test]
    async fn cancellation_during_blocked_poll_never_returns_terminal_success_or_replays() {
        use std::sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        };
        let cancel = tokio_util::sync::CancellationToken::new();
        let (started_tx, started_rx) = tokio::sync::oneshot::channel();
        let (release_tx, release_rx) = tokio::sync::oneshot::channel();
        let requests = Arc::new(AtomicUsize::new(0));
        let observed = requests.clone();
        let operation_cancel = cancel.clone();
        let poll = tokio::spawn(async move {
            cancel_preview_request(operation_cancel, async move {
                observed.fetch_add(1, Ordering::SeqCst);
                started_tx.send(()).unwrap();
                release_rx.await.unwrap();
                Ok(json!({"status":"running"}))
            })
            .await
        });
        started_rx.await.unwrap();
        cancel.cancel();
        // Either the cancelled request has already been dropped or both branches
        // become ready together. Cancellation must win in either ordering.
        let _ = release_tx.send(());
        assert_eq!(poll.await.unwrap(), Err(Error::Cancelled));
        assert_eq!(requests.load(Ordering::SeqCst), 1);
    }
    #[tokio::test]
    async fn cancellation_just_before_terminal_response_is_rechecked() {
        let cancel = tokio_util::sync::CancellationToken::new();
        let request_cancel = cancel.clone();
        let response = cancel_preview_request(cancel, async move {
            request_cancel.cancel();
            Ok(json!({"status":"running"}))
        })
        .await;
        assert_eq!(response, Err(Error::Cancelled));
    }
    #[test]
    fn local_deadline_metadata_never_claims_received_http_status() {
        let local = PreviewStartError::LocalDeadline;
        assert_eq!(local.local_status_code(), Some(408));
        assert!(std::error::Error::source(&local).is_none());
        let transport = PreviewStartError::ClientError(Error::Authentication);
        assert_eq!(transport.local_status_code(), None);
        assert!(std::error::Error::source(&transport).is_some());
    }
    #[test]
    fn ids_are_single_encoded_segments() {
        assert_eq!(
            segment("a /?#+%界").unwrap(),
            "a%20%2F%3F%23%2B%25%E7%95%8C"
        );
        assert_eq!(segment("a!~*'()").unwrap(), "a!~*'()");
        for id in ["", ".", "..", "a\nb", "a\0b"] {
            assert!(segment(id).is_err());
        }
    }
    fn client(credentials: SdkCredentials) -> OpenMates {
        OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials,
            device_id: "synthetic-embed-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap()
    }
    #[tokio::test]
    async fn anonymous_and_cancelled_reads_fail_before_transport() {
        let mut anonymous = client(SdkCredentials::Anonymous {
            anonymous_id: "fixture".into(),
        });
        assert_eq!(
            anonymous.embeds().show("embed-a").await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anonymous.embeds().versions("embed-a").await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anonymous.embeds().version("embed-a", 1).await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anonymous.embeds().restore_version("embed-a", 1, true).await,
            Err(Error::Authentication)
        );
        assert!(matches!(
            anonymous
                .embeds()
                .restore_version("embed-a", 1, false)
                .await,
            Err(Error::Invalid(_))
        ));
        assert_eq!(
            anonymous.embeds().share("embed-a", 0, "").await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anonymous
                .embeds()
                .add_to_project("embed-a", "project-a", None)
                .await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anonymous
                .embeds()
                .remove_from_project("embed-a", "project-a")
                .await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anonymous
                .embeds()
                .preview()
                .start("embed-a", "chat-a", Default::default())
                .await,
            Err(PreviewStartError::ClientError(Error::Authentication))
        );
        assert_eq!(
            anonymous.embeds().preview().status("session-a").await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anonymous.embeds().preview().open("session-a").await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anonymous.embeds().preview().stop("session-a").await,
            Err(Error::Authentication)
        );
        let mut owner = client(SdkCredentials::ApiKey(
            ApiKey::new("sk-api-embedOwnerA.localSetupSuffix").unwrap(),
        ));
        let cancel = tokio_util::sync::CancellationToken::new();
        cancel.cancel();
        owner.set_operation_cancel(cancel);
        assert_eq!(owner.embeds().show("embed-a").await, Err(Error::Cancelled));
        assert_eq!(
            owner.embeds().versions("embed-a").await,
            Err(Error::Cancelled)
        );
        assert_eq!(
            owner.embeds().version("embed-a", 1).await,
            Err(Error::Cancelled)
        );
        assert_eq!(
            owner.embeds().restore_version("embed-a", 1, true).await,
            Err(Error::Cancelled)
        );
        assert_eq!(
            owner.embeds().share("embed-a", 0, "").await,
            Err(Error::Cancelled)
        );
        assert_eq!(
            owner
                .embeds()
                .preview()
                .start("embed-a", "chat-a", Default::default())
                .await,
            Err(PreviewStartError::ClientError(Error::Cancelled))
        );
        assert_eq!(
            owner.embeds().preview().status("session-a").await,
            Err(Error::Cancelled)
        );
        assert_eq!(
            owner.embeds().preview().open("session-a").await,
            Err(Error::Cancelled)
        );
        assert_eq!(
            owner.embeds().preview().stop("session-a").await,
            Err(Error::Cancelled)
        );
    }
}

#[cfg(test)]
mod version_content_tests {
    use super::*;
    #[test]
    fn shared_ciphertext_rows_cover_exact_legacy_reconstruction_and_refusals() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../tests/fixtures/sdk-embed-version-content.json"
        ))
        .unwrap();
        let suite = &fixture["capabilities"]["sdk.embeds.version-content"];
        for case in suite["reconstruction"].as_array().unwrap() {
            let key = case["key"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_u64().unwrap() as u8)
                .collect::<Vec<_>>();
            let key: [u8; 32] = key.try_into().unwrap();
            let result = reconstruct_version_rows(case["rows"].as_array().unwrap(), &key);
            match case["error"].as_str() {
                None => assert_eq!(
                    result.unwrap().as_str(),
                    case["expected"].as_str().unwrap(),
                    "{}",
                    case["id"]
                ),
                Some("crypto") => assert!(matches!(result, Err(Error::Crypto)), "{}", case["id"]),
                _ => assert!(matches!(result, Err(Error::Protocol)), "{}", case["id"]),
            }
        }
    }
    #[test]
    fn local_reconstruction_honors_cancellation_and_never_treats_ciphertext_as_plaintext() {
        let cancel = CancellationToken::new();
        cancel.cancel();
        assert!(matches!(
            reconstruct_version_rows_with_cancel(
                &[json!({"version_number":1,"encrypted_snapshot":"corrupt"})],
                &[7; 32],
                &cancel
            ),
            Err(Error::Cancelled)
        ));
    }
}
