//! API-key and anonymous SDK transport. Explicit credentials are never mixed
//! with cookie sessions, installed profiles, browser UI or durable local state.
pub use crate::sdk_drafts as drafts;
use crate::{
    Client, ClientOptions, Error, Result,
    crypto::{self, Key},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use reqwest::Method;
use futures_util::{stream::FuturesUnordered, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::time::Duration;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

#[path="sdk_skill_release.rs"]
mod skill_release;
#[path="sdk_raw.rs"]
mod raw;
use skill_release::{SkillRelease,SkillValue,SkillValues};
const MAX_BODY: usize = 16 * 1024 * 1024;

/// The setup/decryption suffix is kept locally and never becomes a bearer token.
#[derive(Clone)]
pub struct ApiKey {
    bearer: Zeroizing<String>,
    decryption_secret: Option<Zeroizing<String>>,
}
impl ApiKey {
    pub fn new(value: &str) -> Result<Self> {
        let mut parts = value.split('.');
        let bearer = parts.next().ok_or(Error::Authentication)?;
        let secret = parts.next();
        if parts.next().is_some()
            || !bearer.starts_with("sk-api-")
            || bearer.len() <= 7
            || bearer.len() > 512
            || !bearer[7..].bytes().all(|b| b.is_ascii_alphanumeric())
            || secret.is_some_and(|s| {
                s.is_empty() || s.len() > 512 || !s.bytes().all(|b| b.is_ascii_alphanumeric())
            })
        {
            return Err(Error::Invalid("Invalid API key setup credential."));
        }
        Ok(Self {
            bearer: Zeroizing::new(bearer.into()),
            decryption_secret: secret.map(|s| Zeroizing::new(s.into())),
        })
    }
    pub fn has_decryption_secret(&self) -> bool {
        self.decryption_secret.is_some()
    }
}
pub enum SdkCredentials {
    ApiKey(ApiKey),
    Anonymous { anonymous_id: String },
}
pub struct SdkOptions {
    pub api_url: String,
    pub credentials: SdkCredentials,
    pub device_id: String,
    pub client_options: ClientOptions,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct AnonymousMessage {
    pub role: String,
    pub content: String,
    #[serde(default)]
    pub created_at: i64,
}
pub struct OpenMates {
    base: url::Url,
    http: crate::platform::http::Client,
    credentials: SdkCredentials,
    device_id: String,
    options: ClientOptions,
    origin: String,
    session: Option<Value>,
    master: Option<Key>,
    operation_cancel: CancellationToken,
}
impl OpenMates {
    pub fn new(options: SdkOptions) -> Result<Self> {
        let base = crate::client::transport::validate_base(&options.api_url)?;
        if !identity(&options.device_id) {
            return Err(Error::Invalid(
                "Supply a stable device identity of 1–128 header-safe characters.",
            ));
        }
        if let SdkCredentials::Anonymous { anonymous_id } = &options.credentials
            && !identity(anonymous_id)
        {
            return Err(Error::Invalid(
                "Supply an anonymous identity of 1–128 header-safe characters.",
            ));
        }
        let origin =
            Client::with_options(&options.api_url, None, options.client_options.clone())?.app_url();
        let http = crate::platform::http::client()?;
        Ok(Self {
            base,
            http,
            credentials: options.credentials,
            device_id: options.device_id,
            options: options.client_options,
            origin,
            session: None,
            master: None,
            operation_cancel: CancellationToken::new(),
        })
    }
    pub(crate) fn operation_cancel_token(&self) -> CancellationToken { self.operation_cancel.clone() }
    /// Authenticated API-key documentation; the public Client facade stays independent.
    pub fn docs(&self) -> crate::sdk_docs::Docs<'_> { crate::sdk_docs::Docs::new(self) }
    pub fn wikipedia(&self) -> crate::sdk_wikipedia::Wikipedia<'_> { crate::sdk_wikipedia::Wikipedia::new(self) }
    pub fn billing(&self) -> crate::sdk_billing::Billing<'_> { crate::sdk_billing::Billing::new(self) }
    pub fn settings(&self) -> crate::sdk_settings::Settings<'_> { crate::sdk_settings::Settings::new(self) }
    pub fn reminders(&self) -> crate::sdk_reminders::Reminders<'_> { crate::sdk_reminders::Reminders::new(self) }
    pub fn notifications(&self) -> crate::sdk_notifications::Notifications<'_> { crate::sdk_notifications::Notifications::new(self) }
    pub fn finance(&self) -> crate::sdk_finance::Finance<'_> { crate::sdk_finance::Finance::new(self) }
    pub fn connected_accounts(&mut self) -> crate::sdk_connected_accounts::ConnectedAccounts<'_> { crate::sdk_connected_accounts::ConnectedAccounts::new(self) }
    pub fn embeds(&mut self) -> crate::sdk_embeds::Embeds<'_> { crate::sdk_embeds::Embeds::new(self) }
    pub fn set_operation_cancel(&mut self, cancel: CancellationToken) {
        self.operation_cancel.cancel();
        self.operation_cancel = cancel.child_token();
    }
    /// Encrypted chat reads, decrypted locally with the API-key-wrapped key.
    pub fn chats(&mut self) -> crate::sdk_chats::Chats<'_> {
        crate::sdk_chats::Chats::new(self)
    }
    pub fn history(&mut self) -> crate::sdk_history::History<'_> {
        crate::sdk_history::History::api_key(self)
    }
    /// Read-only drafts for the explicit authenticated API-key owner.
    pub fn drafts(&mut self) -> drafts::Drafts<'_> {
        drafts::Drafts::new(self)
    }
    pub fn workflows(&mut self) -> crate::work::Workflows<'_> {
        crate::work::Workflows::api_key(self)
    }
    pub fn projects(&mut self) -> crate::work::Projects<'_> {
        let cancel = self.operation_cancel.clone();
        crate::work::Projects::api_key(self, cancel)
    }
    pub fn plans(&mut self) -> crate::work::Plans<'_> {
        crate::work::Plans::api_key(self)
    }
    pub fn tasks(&mut self) -> crate::work::Tasks<'_> {
        crate::work::Tasks::api_key(self)
    }
    pub(crate) fn work_app_origin(&self) -> String {
        self.origin.clone()
    }
    pub(crate) fn work_origin(&self) -> String {
        self.base.origin().ascii_serialization()
    }
    /// Fixed account read for an explicitly supplied API-key credential.
    pub async fn account_info(&self) -> Result<Value> {
        let release=SkillRelease::capture(self,self.operation_cancel.clone());
        release.check()?;
        if self.is_anonymous() { return Err(Error::Authentication); }
        let value=SkillValue::new(self.request(Method::GET, "/v1/sdk/account", None, false).await?);
        value.release(&release)
    }
    /// Dynamic equivalent of generated App skill methods, using the same policy.
    /// Cancellation never retries a POST with an ambiguous committed outcome.
    pub async fn run_app_skill(&self, app: &str, skill: &str, input: Value,
        cancel: CancellationToken) -> Result<Value> {
        self.run_skill_cancellable(app, skill, input, cancel).await
    }
    pub fn is_anonymous(&self) -> bool {
        matches!(self.credentials, SdkCredentials::Anonymous { .. })
    }
    pub fn apps(&self) -> crate::generated::AppSkills<'_> {
        crate::generated::AppSkills::new(self)
    }
    pub async fn anonymous_status(&self) -> Result<Value> {
        self.request(Method::GET, "/v1/anonymous/free-usage/status", None, true)
            .await
    }
    pub async fn send_anonymous_chat(
        &self,
        message: &str,
        history: &[AnonymousMessage],
    ) -> Result<Value> {
        let SdkCredentials::Anonymous { anonymous_id } = &self.credentials else {
            return Err(Error::Invalid(
                "Use explicit anonymous credentials for anonymous chat.",
            ));
        };
        self.verify_private_operation()?;
        if message.trim().is_empty()
            || message.chars().count() > 20_000
            || history.len() > 50
            || history.iter().any(|m| {
                !matches!(m.role.as_str(), "user" | "assistant")
                    || m.content.chars().count() > 20_000
            })
        {
            return Err(Error::Invalid(
                "Anonymous chat requires a nonempty message up to 20000 characters and at most 50 user/assistant history entries.",
            ));
        }
        let mut result=self.request(Method::POST,"/v1/anonymous/chat/stream",Some(json!({"anonymous_id":anonymous_id,"client_chat_id":uuid::Uuid::new_v4(),"client_message_id":uuid::Uuid::new_v4(),"plaintext_message":message,"message_history":history})),true).await?;
        result["content"] = result["assistant"]
            .as_str()
            .map(|s| json!(s))
            .unwrap_or(json!(""));
        Ok(result)
    }
    pub(crate) async fn run_skill(&self, app: &str, skill: &str, input: Value) -> Result<Value> {
        self.run_skill_cancellable(app, skill, input, self.operation_cancel.clone())
            .await
    }
    pub(crate) async fn run_skill_cancellable(
        &self,
        app: &str,
        skill: &str,
        input: Value,
        cancel: CancellationToken,
    ) -> Result<Value> {
        let release=SkillRelease::capture(self,cancel);
        let input=SkillValue::new(input);
        release.check()?;
        if !identifier(app)
            || !identifier(skill)
            || !input.is_object()
            || zeroize::Zeroizing::new(serde_json::to_vec(&*input)?).len() > 1024 * 1024
        {
            return Err(Error::Invalid(
                "Supply an App/skill identifier and an input object up to 1 MB.",
            ));
        }
        reject_routing_override(&input, 0)?;
        if self.is_anonymous() && app == "ai" && skill == "ask" {
            return Err(Error::Invalid(
                "Use send_anonymous_chat for anonymous AI with automatic routing.",
            ));
        }
        let path = format!(
            "/v1/{}apps/{app}/skills/{skill}",
            if self.is_anonymous() {
                "anonymous/"
            } else {
                ""
            }
        );
        // Never retry POST after an ambiguous commit. Cancellation after dispatch
        // is observed at safe polling boundaries, without resubmitting input.
        release.check_negative()?;
        let response = SkillValue::new(self
            .request(Method::POST, &path, Some(input.into_inner()), self.is_anonymous())
            .await?);
        // The actual original POST/body has settled; own its JSON before any
        // final policy callback and check both original negative tokens AFTER it.
        release.check()?;
        if self.is_anonymous() {
            return response.release(&release);
        }
        if app == "code" && skill == "run" {
            return self.resolve_code(response, &release).await?.release(&release);
        }
        let data = response
            .get("data")
            .filter(|v| v.is_object())
            .unwrap_or(&response);
        // Wire shape matters: task_ids always merges, even one original task.
        let single_task = data["task_id"].as_str().is_some_and(|id| !id.is_empty());
        let mut tasks = vec![];
        if let Some(id) = data["task_id"].as_str().filter(|s| !s.is_empty()) {
            tasks.push(id.to_owned());
        } else if let Some(ids) = data["task_ids"].as_array() {
            for id in ids {
                let id = id
                    .as_str()
                    .filter(|s| identifier(s))
                    .ok_or(Error::Protocol)?;
                tasks.push(id.to_owned());
            }
        }
        if tasks.len() > 100 {
            return Err(Error::Protocol);
        }
        if tasks.is_empty() {
            return response.release(&release);
        }
        // Start every validated original task under the SAME immutable SDK,
        // HTTP pool and captured release. No task waves, replacement IDs or POST
        // replay. The existing 100-task/16-MB-per-body bounds still apply.
        let mut ordered: Vec<Option<SkillValue>> = (0..tasks.len()).map(|_| None).collect();
        let mut pending = FuturesUnordered::new();
        let original_release = &release;
        for (index, id) in tasks.into_iter().enumerate() {
            pending.push(async move {
                (index, self.poll(&format!("/v1/tasks/{id}"), false, original_release).await)
            });
        }
        while let Some((index, result)) = pending.next().await {
            // Failure drops pending futures and every held wiping SkillValue;
            // an earlier held task cannot hide a completed/failed later peer.
            ordered[index] = Some(result?);
        }
        let mut results = SkillValues::new(vec![]);
        for task in ordered {
            results.push(task.ok_or(Error::Protocol)?["result"].clone());
        }
        let result = if single_task {
            results.remove(0)
        } else {
            merge_results(results.into_inner())
        };
        SkillValue::new(wrap_result(response.into_inner(), result)).release(&release)
    }
    pub async fn sdk_session(&mut self) -> Result<Value> {
        if self.is_anonymous() {
            return Err(Error::Authentication);
        }
        if self.session.is_none() {
            self.session = Some(
                self.request(
                    Method::POST,
                    "/v1/sdk/session",
                    Some(json!({"sdk_name":self.options.identity.header(),"device_identity":self.device_id})),
                    false,
                )
                .await?,
            );
        }
        self.session.clone().ok_or(Error::Protocol)
    }
    /// Recover the API-key-wrapped account key. The setup suffix stays local.
    pub async fn master_key(&mut self) -> Result<Key> {
        if let Some(key) = &self.master {
            return Ok(key.clone());
        }
        let session = self.sdk_session().await?;
        let wrapper = &session["key_wrapper"];
        if !wrapper.is_object() {
            return Err(Error::Forbidden);
        }
        let key = self.unwrap_credential_key(wrapper)?;
        self.master = Some(key.clone());
        Ok(key)
    }
    fn unwrap_credential_key(&self, wrapper: &Value) -> Result<Key> {
        let SdkCredentials::ApiKey(credential) = &self.credentials else {
            return Err(Error::Authentication);
        };
        let decode = |name: &str| -> Result<Vec<u8>> {
            STANDARD
                .decode(wrapper[name].as_str().ok_or(Error::Protocol)?)
                .map_err(|_| Error::Crypto)
        };
        let salt = decode("salt")?;
        let iv = decode("key_iv")?;
        let ciphertext = decode("encrypted_key")?;
        if !(8..=128).contains(&salt.len()) || iv.len() != 12 || ciphertext.len() != 48 {
            return Err(Error::Crypto);
        }
        let secret = credential
            .decryption_secret
            .as_ref()
            .map(|s| s.as_bytes())
            .unwrap_or(credential.bearer.as_bytes());
        let mut wrapping = Zeroizing::new([0; 32]);
        pbkdf2::pbkdf2_hmac::<sha2::Sha256>(secret, &salt, 100_000, &mut *wrapping);
        let bytes = crypto::decrypt_aead(&ciphertext, &wrapping, &iv, &[])?;
        let raw: [u8; 32] = bytes.as_slice().try_into().map_err(|_| Error::Crypto)?;
        let key = Zeroizing::new(raw);
        Ok(key)
    }
    pub(crate) async fn project_grant_key(&mut self, id: &str) -> Result<Option<Key>> {
        let session = self.sdk_session().await?;
        if session["key_wrapper"].is_object() {
            return Ok(None);
        }
        let grants = session["resource_key_grants"]
            .as_array()
            .ok_or(Error::Forbidden)?;
        let grants = grants
            .iter()
            .filter(|grant| grant["resource_type"] == "project" && grant["resource_id"] == id)
            .collect::<Vec<_>>();
        match grants.as_slice() {
            [grant] => self.unwrap_credential_key(grant).map(Some),
            [] => Err(Error::Forbidden),
            _ => Err(Error::Protocol),
        }
    }
    pub(crate) fn verify_private_operation(&self) -> Result<()> {
        self.options.privacy.verify()?;
        if let Some(gate) = &self.options.private_operation_gate {
            gate()?;
        }
        Ok(())
    }
    async fn resolve_code(&self, mut response: SkillValue, release: &SkillRelease) -> Result<SkillValue> {
        let wrapped = response.get("success").is_some();
        let data = if wrapped {
            &mut response["data"]
        } else {
            &mut *response
        };
        if let Some(results) = data["results"].as_array_mut() {
            if results.len() > 100 {
                return Err(Error::Protocol);
            }
            // All original code jobs share this SDK/pool and the SAME captured
            // release. Preserve result positions; no waves or resubmission.
            let mut pending = FuturesUnordered::new();
            for (index, result) in results.iter().enumerate() {
                if let Some(path) = result["status_path"].as_str().map(str::to_owned) {
                    if !path.starts_with("/v1/code/run/") {
                        return Err(Error::Protocol);
                    }
                    pending.push(async move { (index, self.poll(&path, true, release).await) });
                }
            }
            while let Some((index, status)) = pending.next().await {
                // The original response owns/wipes every completed value; any
                // peer error drops it and all remaining original poll futures.
                results[index]["final"] = status?.into_inner();
            }
        }
        release.check_negative()?;
        Ok(response)
    }
    async fn poll(&self, path: &str, code: bool, release: &SkillRelease) -> Result<SkillValue> {
        let deadline = crate::platform::time::Instant::now() + Duration::from_secs(1200);
        loop {
            release.check_negative()?;
            if crate::platform::time::Instant::now() >= deadline {
                return Err(Error::Offline);
            }
            match self.request(Method::GET, path, None, false).await {
                Ok(value) => {
                    let value=SkillValue::new(value);
                    release.check()?;
                    let status = value["status"].as_str().ok_or(Error::Protocol)?;
                    if code && ["finished", "failed", "timeout", "cancelled"].contains(&status)
                        || !code && status == "completed"
                    {
                        release.check_negative()?;
                        return Ok(value);
                    }
                    if !code && ["failed", "cancelled"].contains(&status) {
                        return Err(Error::Invalid("App skill task failed."));
                    }
                }
                Err(Error::Offline) => {}
                Err(error) => return Err(error),
            }
            tokio::select! {_=release.caller_cancelled()=>return Err(Error::Cancelled),_=release.operation_cancelled()=>return Err(Error::Cancelled),_=crate::platform::time::sleep(Duration::from_secs(if code{1}else{2}))=>{}}
        }
    }
    async fn request(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
        anonymous: bool,
    ) -> Result<Value> {
        self.task_request(method, path, body, anonymous, None).await
    }
    pub(crate) async fn task_request(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
        anonymous: bool,
        task: Option<&crate::work::TaskHeaders>,
    ) -> Result<Value> {
        self.task_request_observed(method, path, body, anonymous, task, None).await
    }
    /// Request-local status evidence for CLI-compatible history errors only.
    /// Ordinary SDK errors and every auth/transport decision remain unchanged.
    pub(crate) async fn task_request_observed(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
        anonymous: bool,
        task: Option<&crate::work::TaskHeaders>,
        mut http_failure_status: Option<&mut Option<u16>>,
    ) -> Result<Value> {
        if let Some(slot) = http_failure_status.as_deref_mut() { *slot = None; }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if !path.starts_with("/v1/") || path.contains(['\\', '#']) || path.contains("//") {
            return Err(Error::Forbidden);
        }
        let url = self.base.join(path).map_err(|_| Error::Protocol)?;
        if url.origin() != self.base.origin() {
            return Err(Error::Forbidden);
        }
        let mut request = self
            .http
            .request(method, url)
            .header("Accept", "application/json")
            .header("X-OpenMates-SDK", self.options.identity.header())
            .header("X-OpenMates-Client-Capabilities", "agentic-storage-v2")
            .header("X-OpenMates-Device-Identity", &self.device_id)
            .header("Origin", &self.origin);
        if let Some(task) = task {
            for (name, value) in task.headers()? {
                request = request.header(name, value);
            }
        }
        if anonymous {
            if let SdkCredentials::Anonymous { anonymous_id } = &self.credentials {
                request = request.header("X-OpenMates-Anonymous-ID", anonymous_id);
            }
        } else {
            let SdkCredentials::ApiKey(key) = &self.credentials else {
                return Err(Error::Authentication);
            };
            request = request.bearer_auth(key.bearer.as_str());
        }
        if let Some(body) = body {
            request = request.json(&body);
        }
        let mut response = request.send().await.map_err(|_| Error::Offline)?;
        let status = response.status();
        if !status.is_success() && let Some(slot) = http_failure_status {
            *slot = Some(status.as_u16());
        }
        if status.is_redirection() {
            return Err(Error::Forbidden);
        }
        if response
            .content_length()
            .is_some_and(|n| n > MAX_BODY as u64)
        {
            return Err(Error::Protocol);
        }
        let mut bytes = vec![];
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
            if bytes.len() + chunk.len() > MAX_BODY {
                return Err(Error::Protocol);
            }
            bytes.extend_from_slice(&chunk);
        }
        let value: Value = if bytes.is_empty() {
            json!({})
        } else {
            if status.is_success() {
                serde_json::from_slice(&bytes)?
            } else {
                serde_json::from_slice(&bytes).unwrap_or(Value::Null)
            }
        };
        if !status.is_success() {
            let detail = &value["detail"];
            if anonymous
                && matches!(status.as_u16(), 403 | 429)
                && (detail["signup_required"] == true
                    || ["reason", "code"].iter().any(|k| {
                        [
                            "signup_required",
                            "budget_exhausted",
                            "per_identity_exhausted",
                            "inactive",
                        ]
                        .contains(&detail[*k].as_str().unwrap_or(""))
                    }))
            {
                return Err(Error::SignupRequired);
            }
            return Err(match status.as_u16() {
                409 => Error::Conflict,
                400 | 422 => Error::Invalid("The server rejected the requested operation."),
                404 | 410 => Error::Invalid("The requested item is unavailable."),
                401 => Error::Authentication,
                403 => Error::Forbidden,
                429 | 500..=599 => Error::Offline,
                _ => Error::Protocol,
            });
        }
        Ok(value)
    }
}
fn identity(value: &str) -> bool {
    !value.is_empty() && value.len() <= 128 && value.bytes().all(|b| b > 32 && b < 127)
}
pub(crate) fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
}
fn reject_routing_override(value: &Value, depth: usize) -> Result<()> {
    if depth > 32 {
        return Err(Error::Invalid(
            "App input nesting exceeds the supported limit.",
        ));
    }
    match value {
        Value::Object(map) => {
            for (key, value) in map {
                if [
                    "provider",
                    "provider_id",
                    "model",
                    "model_id",
                    "model_name",
                    "preferred_model",
                ]
                .contains(&key.as_str())
                {
                    return Err(Error::Invalid(
                        "Use automatic model routing without a model or provider override.",
                    ));
                }
                reject_routing_override(value, depth + 1)?;
            }
        }
        Value::Array(items) => {
            for value in items {
                reject_routing_override(value, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}
fn wrap_result(mut original: Value, result: Value) -> Value {
    if original.get("success").is_some() {
        original["data"] = result;
        original
    } else if result.is_object() {
        result
    } else {
        json!({"result":result})
    }
}
fn merge_results(results: Vec<Value>) -> Value {
    let mut results=SkillValues::new(results);
    let grouped = results
        .iter()
        .filter_map(|v| v["results"].as_array())
        .flatten()
        .cloned()
        .collect::<Vec<_>>();
    if grouped.is_empty() {
        // Move the existing guarded values into the final JSON owner. Do not
        // serialize the wiping wrapper or clone the original result payloads.
        let mut object = serde_json::Map::new();
        object.insert("results".into(), Value::Array(std::mem::take(&mut *results)));
        Value::Object(object)
    } else {
        let mut first = results
            .iter()
            .find(|v| v.is_object())
            .cloned()
            .unwrap_or(json!({}));
        first["results"] = json!(grouped);
        first
    }
}

impl Drop for OpenMates {
    fn drop(&mut self) {
        self.operation_cancel.cancel();
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    pub(crate) async fn server(
        responses: Vec<(u16, Value)>,
    ) -> (String, tokio::task::JoinHandle<Vec<(String, Value)>>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let task = tokio::spawn(async move {
            let mut requests = vec![];
            for (status, response) in responses {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut bytes = vec![];
                let mut buffer = [0; 4096];
                let (header_end, len) = loop {
                    let n = stream.read(&mut buffer).await.unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&buffer[..n]);
                    if let Some(end) = bytes.windows(4).position(|s| s == b"\r\n\r\n") {
                        let header = String::from_utf8_lossy(&bytes[..end]);
                        let len = header
                            .lines()
                            .find_map(|line| {
                                line.split_once(':')
                                    .filter(|(k, _)| k.eq_ignore_ascii_case("content-length"))
                                    .and_then(|(_, v)| v.trim().parse::<usize>().ok())
                            })
                            .unwrap_or(0);
                        break (end + 4, len);
                    }
                };
                while bytes.len() < header_end + len {
                    let n = stream.read(&mut buffer).await.unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&buffer[..n]);
                }
                let header = String::from_utf8_lossy(&bytes[..header_end]).into_owned();
                let body = if len == 0 {
                    Value::Null
                } else {
                    serde_json::from_slice(&bytes[header_end..header_end + len]).unwrap()
                };
                requests.push((header, body));
                let raw = response.to_string();
                stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{raw}",raw.len()).as_bytes()).await.unwrap();
            }
            requests
        });
        (format!("http://{address}"), task)
    }
    fn client(api: String, credentials: SdkCredentials) -> OpenMates {
        OpenMates::new(SdkOptions {
            api_url: api,
            credentials,
            device_id: "fixture-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap()
    }
    fn api_key() -> SdkCredentials {
        SdkCredentials::ApiKey(
            ApiKey::new(&format!("sk-api-{}.{}", "b".repeat(32), "s".repeat(32))).unwrap(),
        )
    }
    #[test]
    fn operation_tokens_are_owned_children() {
        let mut client = client("https://api.example.org".into(), api_key());
        let parent = CancellationToken::new();
        client.set_operation_cancel(parent.clone());
        let first = client.operation_cancel.clone();
        client.set_operation_cancel(parent.clone());
        assert!(first.is_cancelled());
        assert!(!parent.is_cancelled());
        parent.cancel();
        assert!(client.operation_cancel.is_cancelled());
        let parent = CancellationToken::new();
        client.set_operation_cancel(parent.clone());
        let child = client.operation_cancel.clone();
        drop(client);
        assert!(child.is_cancelled());
        assert!(!parent.is_cancelled());
    }
    #[tokio::test]
    async fn cancelled_api_key_writes_never_dispatch() {
        let mut client = client("http://127.0.0.1:1".into(), api_key());
        let parent = CancellationToken::new();
        client.set_operation_cancel(parent.clone());
        parent.cancel();
        assert_eq!(
            client
                .task_request(Method::POST, "/v1/user-tasks", Some(json!({})), false, None)
                .await,
            Err(Error::Cancelled)
        );
    }
    #[tokio::test]
    async fn anonymous_chat_uses_direct_route_without_bearer_or_model_defaults() {
        let (api, server) = server(vec![(
            200,
            json!({"assistant":"Synthetic anonymous response"}),
        )])
        .await;
        let client = client(
            api,
            SdkCredentials::Anonymous {
                anonymous_id: "guest-fixture".into(),
            },
        );
        let response = client
            .send_anonymous_chat(
                "Synthetic question",
                &[AnonymousMessage {
                    role: "user".into(),
                    content: "Previous synthetic question".into(),
                    created_at: 1,
                }],
            )
            .await
            .unwrap();
        assert_eq!(response["content"], "Synthetic anonymous response");
        let request = server.await.unwrap().remove(0);
        let headers = request.0.to_lowercase();
        assert!(headers.starts_with("post /v1/anonymous/chat/stream http/1.1"));
        assert!(!headers.contains("authorization:"));
        assert!(headers.contains("x-openmates-anonymous-id: guest-fixture"));
        assert!(headers.contains("x-openmates-sdk: rust"));
        assert_eq!(request.1["plaintext_message"], "Synthetic question");
        assert!(request.1.get("model").is_none());
        assert!(request.1.get("provider").is_none());
    }
    #[tokio::test]
    async fn exhausted_anonymous_allowance_has_actionable_error_and_never_changes_mode() {
        let (api, server) = server(vec![(
            429,
            json!({"detail":{"reason":"budget_exhausted","signup_required":true}}),
        )])
        .await;
        let client = client(
            api,
            SdkCredentials::Anonymous {
                anonymous_id: "guest-fixture".into(),
            },
        );
        assert!(matches!(
            client.anonymous_status().await,
            Err(Error::SignupRequired)
        ));
        assert_eq!(server.await.unwrap().len(), 1);
    }
    #[tokio::test]
    async fn failed_api_key_never_falls_back_to_anonymous() {
        let (api, server) = server(vec![(401, json!({"detail":"not authorized"}))]).await;
        let client = client(api, api_key());
        assert!(matches!(
            client
                .apps()
                .web()
                .search(json!({"requests":[{"query":"fixture"}]}))
                .await,
            Err(Error::Authentication)
        ));
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 1);
        assert!(
            requests[0]
                .0
                .starts_with("POST /v1/apps/web/skills/search ")
        );
        let headers = requests[0].0.to_lowercase();
        assert!(headers.contains(&format!("authorization: bearer sk-api-{}", "b".repeat(32))));
        assert!(!headers.contains(&"s".repeat(32)));
        assert!(!headers.contains("x-openmates-anonymous-id:"));
    }
    #[tokio::test]
    async fn async_skill_polls_once_per_task_without_resubmitting_input() {
        let (api, server) = super::parallel_task_tests::routed_original_task_server().await;
        let client = client(api, api_key());
        let result = client
            .apps()
            .web()
            .search(json!({"requests":[{"query":"fixture"}]}))
            .await
            .unwrap();
        assert_eq!(result["data"]["results"], json!([{"id":"a"},{"id":"b"}]));
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 3);
        assert_eq!(requests.iter().filter(|(header,_)|header.starts_with("POST /v1/apps/web/skills/search ")).count(),1);
        assert_eq!(requests.iter().filter(|(header,_)|header.starts_with("GET /v1/tasks/task-a ")).count(),1);
        assert_eq!(requests.iter().filter(|(header,_)|header.starts_with("GET /v1/tasks/task-b ")).count(),1);
    }
    #[tokio::test]
    async fn setup_suffix_unwraps_master_locally_and_never_enters_headers_or_body() {
        let salt = [3; 16];
        let iv = [4; 12];
        let mut wrapping = Zeroizing::new([0; 32]);
        pbkdf2::pbkdf2_hmac::<sha2::Sha256>(
            "s".repeat(32).as_bytes(),
            &salt,
            100_000,
            &mut *wrapping,
        );
        let encrypted = crypto::encrypt_aead(&[9; 32], &wrapping, &iv, &[]).unwrap();
        let(api,server)=server(vec![(200,json!({"key_wrapper":{"salt":STANDARD.encode(salt),"key_iv":STANDARD.encode(iv),"encrypted_key":STANDARD.encode(encrypted)}}))]).await;
        let mut client = client(api, api_key());
        assert_eq!(*client.master_key().await.unwrap(), [9; 32]);
        assert_eq!(*client.master_key().await.unwrap(), [9; 32]);
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 1);
        assert!(!requests[0].0.contains(&"s".repeat(32)));
        assert!(!requests[0].1.to_string().contains(&"s".repeat(32)));
        assert_eq!(
            requests[0].1,
            json!({"sdk_name":"rust","device_identity":"fixture-device"})
        );
    }
    #[test]
    fn malformed_credentials_and_header_injection_are_rejected() {
        for invalid in [
            "",
            "wrong",
            "sk-api-a.",
            "sk-api-a.secret.extra",
            "sk-api-a\r\nInjected: x",
        ] {
            assert!(ApiKey::new(invalid).is_err());
        }
        assert!(
            OpenMates::new(SdkOptions {
                api_url: "https://api.example.org".into(),
                credentials: api_key(),
                device_id: "bad\r\nheader".into(),
                client_options: ClientOptions::default()
            })
            .is_err()
        );
        assert!(
            crate::generated::app_skill_metadata()
                .as_array()
                .is_some_and(|rows| rows
                    .iter()
                    .any(|row| row["app_id"] == "web" && row["skill_id"] == "search"))
        );
    }
}

#[cfg(test)]
mod unavailable_tests {
    use super::*;
    #[test]
    fn retired_skills_are_absent_from_generated_metadata() {
        assert!(!crate::generated::app_skill_metadata().as_array().unwrap().iter().any(|item|item["app_id"]=="health"&&item["skill_id"]=="create_report"));
        assert!(!crate::generated::app_skill_metadata().as_array().unwrap().iter().any(|item|item["app_id"]=="workflows"&&item["skill_id"]=="create-or-modify"));
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="sdk_skill_release_tests.rs"]
mod skill_release_tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "sdk_parallel_task_tests.rs"]
mod parallel_task_tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "sdk_parallel_code_tests.rs"]
mod parallel_code_tests;
