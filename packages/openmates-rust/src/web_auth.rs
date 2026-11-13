//! Web app account authority owned by the shared core: password + 2FA login,
//! session-restore classification, logout plan and cross-tab invalidation.
//!
//! Sans-IO by design. The web adapter executes every [`HttpRequest`] exactly as
//! described (credentialed same-page Fetch, so cookies and Set-Cookie behave
//! identically) and returns an [`HttpReply`]. Request paths, header sets, body
//! field order and the fallback/branch rules reproduce the deployed TypeScript
//! web client byte for byte, so enabling the Rust path changes neither the
//! request sequence nor the cookies. Behaviour changes ship separately.
use crate::client::SessionVerification;
use crate::crypto::{self, Key};
use crate::error::{Error, Result};
use base64::{Engine as _, engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD}};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use zeroize::Zeroizing;

/// Header value the adapter replaces with the page origin (deployed TS sends it;
/// browsers treat `Origin` as a forbidden header and keep their own value).
pub const PAGE_ORIGIN: &str = "{page_origin}";
const JSON_HEADERS: &[(&str, &str)] = &[("Content-Type", "application/json")];
const LOGIN_HEADERS: &[(&str, &str)] = &[("Content-Type", "application/json"), ("Accept", "application/json"), ("Origin", PAGE_ORIGIN)];
const SESSION_HEADERS: &[(&str, &str)] = &[("Accept", "application/json"), ("Content-Type", "application/json"), ("Origin", PAGE_ORIGIN)];
const MAX_EMAIL_BYTES: usize = 512;
const MAX_PASSWORD_BYTES: usize = 16 * 1024;

/// JSON wire form of the values the web adapter receives.
pub trait WireJson { fn wire_json(&self) -> Result<String>; }
impl<T: Serialize> WireJson for T {
    fn wire_json(&self) -> Result<String> { serde_json::to_string(self).map_err(|_| Error::Protocol) }
}

/// One credentialed request for the platform adapter. No URL host: the adapter
/// resolves `path` against its configured API base, exactly as the TS client.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HttpRequest {
    pub method: &'static str,
    pub path: &'static str,
    pub headers: Vec<(&'static str, &'static str)>,
    pub body: Option<String>,
}
impl HttpRequest {
    fn post(path: &'static str, headers: &[(&'static str, &'static str)], body: Option<String>) -> Self {
        Self { method: "POST", path, headers: headers.to_vec(), body }
    }
}

/// Response as observed by the adapter. `body` is `None` when it was not JSON.
#[derive(Debug, Clone)]
pub struct HttpReply {
    pub status: u16,
    pub body: Option<Value>,
}
impl HttpReply {
    fn ok(&self) -> bool { (200..300).contains(&self.status) }
}

/// `JSON.stringify` of an object literal with these keys in this order.
fn ordered(fields: &[(&str, Value)]) -> String {
    let mut out = String::from("{");
    for (index, (key, value)) in fields.iter().enumerate() {
        if index > 0 { out.push(','); }
        out.push_str(&Value::String((*key).to_owned()).to_string());
        out.push(':');
        out.push_str(&value.to_string());
    }
    out.push('}');
    out
}
fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(value)) => *value,
        Some(Value::Number(number)) => number.as_f64().is_some_and(|n| n != 0.0 && !n.is_nan()),
        Some(Value::String(text)) => !text.is_empty(),
        Some(_) => true,
    }
}
fn text<'a>(value: &'a Value, key: &str) -> Option<&'a str> { value.get(key).and_then(Value::as_str) }

// ---------------------------------------------------------------- password ---

/// Second-factor kind of a password login (`code_type` on `/v1/auth/login`),
/// shared by the web sans-IO step and the native `Client` login.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TfaCodeType { Otp, Backup }
impl TfaCodeType {
    /// Parse the web form's `code_type` value.
    ///
    /// # Errors
    /// `Invalid("code_type")` for any other value.
    pub fn parse(value: &str) -> Result<Self> {
        match value { "otp" => Ok(Self::Otp), "backup" => Ok(Self::Backup), _ => Err(Error::Invalid("code_type")) }
    }
    /// Wire value of `code_type`.
    pub(crate) fn wire(self) -> &'static str { match self { Self::Otp => "otp", Self::Backup => "backup" } }
}

/// Password-step input as captured by the login form. `user_email_salt` and
/// `email_encryption_key` are the email-step lookup results (base64).
pub struct PasswordLoginInput {
    pub email: String,
    pub password: Zeroizing<String>,
    pub session_id: String,
    pub user_email_salt: String,
    pub email_encryption_key: Option<String>,
    pub stay_logged_in: bool,
    pub tfa: Option<(Zeroizing<String>, TfaCodeType)>,
}

/// Terminal result of the password step.
pub enum PasswordOutcome {
    /// Not an unlocked login (2FA prompt, wrong password, rate limit, signup
    /// redirect…). The form branches on these exact server fields as before.
    Response { status: u16, data: Value },
    /// Authenticated and the master key was unwrapped.
    Unlocked { status: u16, data: Value, master: Key, credential_version: u8 },
    /// Authenticated, but the local unlock failed (`code` names the TS message).
    UnlockFailed { status: u16, data: Value, code: &'static str },
}

enum Stage { Challenge, LoginV2, LoginV1, Done }

/// Deployed web login protocol: v2 challenge proof first, then the generic v1
/// lookup-hash attempt only when the v2 response is not an authenticated one.
pub struct PasswordLogin {
    input: PasswordLoginInput,
    salt: Zeroizing<Vec<u8>>,
    hashed_email: String,
    auth: Option<Key>,
    wrap: Option<Key>,
    stage: Stage,
    terminal: Option<HttpReply>,
}

pub enum PasswordStep { Http(HttpRequest), Finished }

impl PasswordLogin {
    /// Validates input and performs the Argon2id derivation (the deployed client
    /// derives before requesting the challenge). Returns the challenge request.
    pub fn start(input: PasswordLoginInput) -> Result<(Self, HttpRequest)> {
        if input.email.is_empty() || input.email.len() > MAX_EMAIL_BYTES || input.password.is_empty()
            || input.password.len() > MAX_PASSWORD_BYTES || uuid::Uuid::parse_str(&input.session_id).is_err()
            || input.tfa.as_ref().is_some_and(|(code, _)| code.is_empty() || code.len() > 128) {
            return Err(Error::Invalid("password_login_input"));
        }
        let salt = Zeroizing::new(STANDARD.decode(&input.user_email_salt).map_err(|_| Error::Invalid("user_email_salt"))?);
        let (auth, wrap) = crypto::derive_password_keys_v2(&input.password, &salt)?;
        let hashed_email = crypto::hash_email(&input.email);
        let request = HttpRequest::post("/v1/auth/password-v2/challenge", JSON_HEADERS, Some(ordered(&[
            ("hashed_email", json!(hashed_email)), ("session_id", json!(input.session_id)), ("purpose", json!("login")),
        ])));
        Ok((Self { input, salt, hashed_email, auth: Some(auth), wrap: Some(wrap), stage: Stage::Challenge, terminal: None }, request))
    }

    fn fields(&self) -> Vec<(&'static str, Value)> {
        let mut fields = vec![("stay_logged_in", json!(self.input.stay_logged_in))];
        if let Some((code, kind)) = &self.input.tfa {
            fields.push(("tfa_code", json!(code.as_str())));
            fields.push(("code_type", json!(kind.wire())));
        }
        if let Some(key) = self.input.email_encryption_key.as_ref().filter(|key| !key.is_empty()) {
            fields.push(("email_encryption_key", json!(key)));
        }
        fields.push(("hashed_email", json!(self.hashed_email)));
        fields.push(("session_id", json!(self.input.session_id)));
        fields.push(("login_method", json!("password")));
        fields
    }

    /// Feed the reply to the last request. `Err` codes map to the form's
    /// generic login error (the deployed client threw in the same places).
    pub fn on_reply(&mut self, reply: HttpReply) -> Result<PasswordStep> {
        match self.stage {
            Stage::Challenge => {
                let auth = self.auth.take().ok_or(Error::Protocol)?;
                if !reply.ok() { return Err(Error::Unavailable { code: "challenge_unavailable", reason: "password challenge" }); }
                let body = reply.body.as_ref().ok_or(Error::Protocol)?;
                let (Some(challenge_id), Some(nonce)) = (text(body, "challenge_id"), text(body, "nonce")) else {
                    return Err(Error::Invalid("invalid_challenge"));
                };
                if URL_SAFE_NO_PAD.decode(nonce).map(|bytes| bytes.len()) != Ok(32) { return Err(Error::Invalid("invalid_challenge")); }
                let proof = crypto::password_proof_v2(&auth, nonce, "login")?;
                drop(auth);
                let mut fields = self.fields();
                fields.push(("credential_version", json!(2)));
                fields.push(("challenge_id", json!(challenge_id)));
                fields.push(("password_proof", json!(proof)));
                self.stage = Stage::LoginV2;
                Ok(PasswordStep::Http(HttpRequest::post("/v1/auth/login", LOGIN_HEADERS, Some(ordered(&fields)))))
            }
            Stage::LoginV2 => {
                let body = reply.body.as_ref().ok_or(Error::Protocol)?;
                let authenticated = reply.ok() && truthy(body.get("success"))
                    && body.get("user").is_some_and(|user| truthy(user.get("id")));
                if reply.status == 429 || reply.status >= 500 || authenticated {
                    self.stage = Stage::Done; self.terminal = Some(reply);
                    return Ok(PasswordStep::Finished);
                }
                let mut fields = self.fields();
                fields.push(("credential_version", json!(1)));
                fields.push(("lookup_hash", json!(crypto::hash_key(&self.input.password, &self.salt)?)));
                self.stage = Stage::LoginV1;
                Ok(PasswordStep::Http(HttpRequest::post("/v1/auth/login", LOGIN_HEADERS, Some(ordered(&fields)))))
            }
            Stage::LoginV1 => {
                reply.body.as_ref().ok_or(Error::Protocol)?;
                self.stage = Stage::Done; self.terminal = Some(reply);
                Ok(PasswordStep::Finished)
            }
            Stage::Done => Err(Error::Protocol),
        }
    }

    /// Classify the final login response and, when it authenticated, unwrap
    /// the master key with the same checks as the deployed form.
    pub async fn finish(mut self) -> Result<PasswordOutcome> {
        let reply = self.terminal.take().ok_or(Error::Protocol)?;
        let status = reply.status;
        let data = reply.body.unwrap_or(Value::Null);
        if !(200..300).contains(&status) || !truthy(data.get("success")) || data.get("tfa_required") == Some(&Value::Bool(true)) {
            return Ok(PasswordOutcome::Response { status, data });
        }
        let Some(user) = data.get("user").filter(|user| !user.is_null()) else {
            return Ok(PasswordOutcome::UnlockFailed { status, data, code: "login_failed" });
        };
        let (Some(encrypted), Some(user_salt)) = (text(user, "encrypted_key").filter(|v| !v.is_empty()), text(user, "salt").filter(|v| !v.is_empty())) else {
            return Ok(PasswordOutcome::UnlockFailed { status, data, code: "login_failed" });
        };
        let version = match user.get("credential_version") {
            None | Some(Value::Null) => 1,
            Some(value) if value.as_u64() == Some(1) => 1,
            Some(value) if value.as_u64() == Some(2) => 2,
            Some(_) => return Ok(PasswordOutcome::UnlockFailed { status, data, code: "key_derivation_failed" }),
        };
        if version == 2 && STANDARD.encode(&*self.salt) != user_salt {
            return Ok(PasswordOutcome::UnlockFailed { status, data, code: "key_derivation_failed" });
        }
        let iv = text(user, "key_iv").unwrap_or("").to_owned();
        let (encrypted, user_salt) = (encrypted.to_owned(), user_salt.to_owned());
        let unwrapped = if version == 2 {
            let wrap = self.wrap.take().ok_or(Error::Protocol)?;
            crypto::unwrap_master_key_with_wrapping_key(&encrypted, &iv, &wrap)
        } else {
            self.wrap.take();
            legacy_unwrap(&self.input.password, &encrypted, &user_salt, &iv).await
        };
        Ok(match unwrapped {
            Ok(master) => PasswordOutcome::Unlocked { status, data, master, credential_version: version },
            Err(_) => PasswordOutcome::UnlockFailed { status, data, code: "unwrap_failed" },
        })
    }
}

// The deployed client's v1 wrapper is WebCrypto PBKDF2; keep it on the
// platform primitive in the browser (same work factor, much faster than WASM).
#[cfg(target_arch = "wasm32")]
async fn legacy_unwrap(password: &str, ciphertext: &str, salt: &str, iv: &str) -> Result<Key> {
    crypto::browser_legacy::unwrap(password, 1, ciphertext, salt, iv, || Ok(())).await
}
#[cfg(not(target_arch = "wasm32"))]
async fn legacy_unwrap(password: &str, ciphertext: &str, salt: &str, iv: &str) -> Result<Key> {
    crypto::unwrap_password_master_key(password, 1, ciphertext, salt, iv)
}

// ----------------------------------------------------------------- session ---

/// `POST /v1/auth/session` exactly as the deployed bootstrap check sends it.
/// `device_signals` keeps the caller's insertion order.
pub fn session_request(device_signals: &[(String, Option<String>)], session_id: &str) -> Result<HttpRequest> {
    if device_signals.len() > 64 || session_id.len() > 128 { return Err(Error::Invalid("session_request")); }
    let signals: Vec<(&str, Value)> = device_signals.iter()
        .map(|(key, value)| (key.as_str(), value.as_ref().map_or(Value::Null, |v| json!(v)))).collect();
    let body = format!("{{\"deviceSignals\":{},\"session_id\":{}}}", ordered(&signals), json!(session_id));
    Ok(HttpRequest::post("/v1/auth/session", SESSION_HEADERS, Some(body)))
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SessionDecision {
    /// Non-401 HTTP failure or unreadable body: offline-first, keep local state.
    Unreachable { status: u16 },
    /// Explicit 401: the definitive expired-session result.
    Expired { data: Value },
    DeviceVerification {
        verification: String,
        reason: String,
        password_fallback_available: bool,
        password_credential_version: Value,
        data: Value,
    },
    Authenticated { data: Value },
    Unauthenticated { data: Value },
}

pub fn classify_session(reply: HttpReply) -> SessionDecision {
    if reply.status == 401 {
        return SessionDecision::Expired { data: json!({"success": false, "message": "Session expired or revoked"}) };
    }
    let Some(data) = reply.body.filter(|_| reply.status >= 200 && reply.status < 300) else {
        return SessionDecision::Unreachable { status: reply.status };
    };
    let success = truthy(data.get("success"));
    // One device-verification rule for web and native (client/session_verification.rs).
    // A bare re-auth request stays `Unauthenticated` here, as deployed.
    let device = if success { None } else { SessionVerification::of_unsuccessful_session(&data) };
    if let Some(SessionVerification::Device { method, reason, password_fallback_available: fallback }) = device {
        return SessionDecision::DeviceVerification {
            verification: method.wire().to_owned(),
            reason,
            password_fallback_available: fallback,
            password_credential_version: if fallback { data.get("password_credential_version").cloned().unwrap_or(Value::Null) } else { Value::Null },
            data,
        };
    }
    if success && data.get("user").is_some_and(truthy_value) { SessionDecision::Authenticated { data } } else { SessionDecision::Unauthenticated { data } }
}
fn truthy_value(value: &Value) -> bool { truthy(Some(value)) }

/// Local facts at the moment an authenticated session has no master key.
#[derive(Debug, Clone, Copy, Default, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MissingKeyContext {
    pub already_forced: bool,
    pub shared_chat_session: bool,
    pub pair_login_pending: bool,
    pub og_image_mode: bool,
    pub had_local_session: bool,
    pub storage_evicted: bool,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MissingKeyPlan {
    pub set_forced: bool,
    pub clear_active_chat: bool,
    /// `None`, `"storage_evicted"` or `"session_ended"`.
    pub notify: Option<&'static str>,
    pub destructive_logout: bool,
    pub delete_cookies: bool,
}
/// Deployed forced-logout policy for "authenticated but no local master key".
pub fn missing_key_plan(context: MissingKeyContext) -> MissingKeyPlan {
    let preserve = context.shared_chat_session || context.pair_login_pending;
    MissingKeyPlan {
        set_forced: !context.already_forced,
        clear_active_chat: !preserve && !context.og_image_mode,
        notify: (!context.already_forced && !preserve && context.had_local_session)
            .then_some(if context.storage_evicted { "storage_evicted" } else { "session_ended" }),
        destructive_logout: !preserve,
        delete_cookies: !context.pair_login_pending,
    }
}

// ------------------------------------------------------------------ logout ---

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum LogoutServerStep {
    /// A newer login started meanwhile: protect its credentials.
    SkipNewerLogin,
    /// No server request (caller asked to skip and it is not a policy logout).
    None,
    /// Send this request; other tabs are then told to drop their local state.
    Request { request: HttpRequest, broadcast: bool },
}
/// Server half of the deployed logout: generation guard, then the plain or
/// policy-violation request (no body, JSON content type).
pub fn logout_server_step(captured_generation: u64, current_generation: u64, skip_server_logout: bool, policy_violation: bool) -> LogoutServerStep {
    if captured_generation != current_generation { return LogoutServerStep::SkipNewerLogin; }
    if !skip_server_logout {
        return LogoutServerStep::Request { request: HttpRequest::post("/v1/auth/logout", JSON_HEADERS, None), broadcast: true };
    }
    if policy_violation {
        return LogoutServerStep::Request { request: HttpRequest::post("/v1/auth/policy-violation-logout", JSON_HEADERS, None), broadcast: true };
    }
    LogoutServerStep::None
}
/// JS-visible cookies are deleted only while no newer login exists.
pub fn logout_may_delete_cookies(captured_generation: u64, current_generation: u64) -> bool {
    captured_generation == current_generation
}

/// Cross-tab channel carrying [`logout_frame`] frames.
pub const LOGOUT_CHANNEL: &str = "openmates-auth-v1";
pub fn logout_frame(tab_id: &str) -> Result<String> {
    uuid::Uuid::parse_str(tab_id).map_err(|_| Error::Invalid("tab_id"))?;
    Ok(ordered(&[("v", json!(1)), ("type", json!("logout")), ("tab", json!(tab_id))]))
}
/// A peer tab revoked the shared cookie session: drop local state without a
/// second server request. Frames from this tab or of unknown shape are ignored.
pub fn accept_logout_frame(frame: &Value, own_tab_id: &str) -> bool {
    let Some(object) = frame.as_object() else { return false };
    object.len() == 3 && object.get("v") == Some(&json!(1)) && object.get("type") == Some(&json!("logout"))
        && object.get("tab").and_then(Value::as_str)
            .is_some_and(|tab| tab != own_tab_id && uuid::Uuid::parse_str(tab).is_ok())
}

#[path = "web_auth_recovery.rs"]
mod recovery;
pub use recovery::{RecoveryKeyLogin, RecoveryKeyLoginInput};

#[path = "web_auth_signup.rs"]
mod signup;
#[path = "web_auth_pair.rs"]
mod pair;
#[path = "web_auth_actions.rs"]
mod actions;
#[path = "web_auth_recovery_print.rs"]
mod print;
#[path = "web_auth_flow.rs"]
mod flow;
pub use flow::flow_call;

#[cfg(test)]
#[path = "web_auth_tests.rs"]
mod tests;
#[cfg(test)]
#[path = "web_auth_flow_tests.rs"]
mod flow_tests;
