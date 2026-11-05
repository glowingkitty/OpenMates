//! Web app account authority exports (password + 2FA login, session restore
//! classification, logout plan, cross-tab frames). Policy lives in
//! `openmates_sdk::web_auth`; this file only converts between JS values and the
//! sans-IO core. The page executes each described request with its own Fetch.
use openmates_sdk::web_auth::{
    self, HttpReply, PasswordLogin, PasswordLoginInput, PasswordOutcome, PasswordStep,
    RecoveryKeyLogin, RecoveryKeyLoginInput, TfaCodeType,
};
use serde_json::Value;
use wasm_bindgen::{JsCast, prelude::*};
use zeroize::Zeroizing;

fn code(error: openmates_sdk::Error) -> JsValue {
    JsValue::from_str(match error {
        openmates_sdk::Error::Unavailable { code, .. } => code,
        openmates_sdk::Error::Invalid(code) => code,
        openmates_sdk::Error::Crypto => "crypto_failed",
        _ => "protocol",
    })
}
fn json(value: &impl web_auth::WireJson) -> Result<String, JsValue> {
    value.wire_json().map_err(|_| JsValue::from_str("protocol"))
}
fn reply(status: u16, body: Option<String>) -> HttpReply {
    let body = body
        .map(Zeroizing::new)
        .and_then(|text| serde_json::from_str::<Value>(&text).ok());
    HttpReply { status, body }
}
fn set(object: &js_sys::Object, key: &str, value: &JsValue) -> Result<(), JsValue> {
    js_sys::Reflect::set(object, &JsValue::from_str(key), value)
        .map(|_| ())
        .map_err(|_| JsValue::from_str("protocol"))
}

/// Import the unwrapped master exactly as the deployed form did: extractable
/// AES-GCM (recovery-key wrapping needs export), encrypt + decrypt usages.
async fn import_master(master: &[u8; 32]) -> Result<JsValue, JsValue> {
    use js_sys::{Array, Function, Object, Promise, Reflect, Uint8Array};
    let unavailable = || JsValue::from_str("crypto_failed");
    let crypto =
        Reflect::get(&js_sys::global(), &JsValue::from_str("crypto")).map_err(|_| unavailable())?;
    let subtle = Reflect::get(&crypto, &JsValue::from_str("subtle")).map_err(|_| unavailable())?;
    let import = Reflect::get(&subtle, &JsValue::from_str("importKey"))
        .map_err(|_| unavailable())?
        .dyn_into::<Function>()
        .map_err(|_| unavailable())?;
    let bytes = Uint8Array::from(&master[..]);
    let algorithm = Object::new();
    set(&algorithm, "name", &JsValue::from_str("AES-GCM"))?;
    let usages = Array::of2(&JsValue::from_str("encrypt"), &JsValue::from_str("decrypt"));
    let args = Array::of5(
        &JsValue::from_str("raw"),
        &bytes,
        &algorithm,
        &JsValue::TRUE,
        &usages,
    );
    let promise = import
        .apply(&subtle, &args)
        .map_err(|_| unavailable())?
        .dyn_into::<Promise>()
        .map_err(|_| unavailable())?;
    let key = wasm_bindgen_futures::JsFuture::from(promise).await;
    bytes.fill(0, 0, bytes.length());
    key.map_err(|_| unavailable())
}

/// One password-step attempt. JS loop: `request()` → fetch → `reply()` until it
/// returns true, then `finish()`.
#[wasm_bindgen]
pub struct WebAuthPasswordLogin {
    inner: Option<PasswordLogin>,
    pending: Option<String>,
}

#[wasm_bindgen]
impl WebAuthPasswordLogin {
    /// `input_json`: `{email, sessionId, userEmailSalt, emailEncryptionKey, stayLoggedIn, codeType}`.
    /// Password and code are owned and wiped in WASM memory.
    pub fn start(
        input_json: &str,
        password: String,
        tfa: Option<String>,
    ) -> Result<WebAuthPasswordLogin, JsValue> {
        let password = Zeroizing::new(password);
        let tfa = tfa.map(Zeroizing::new);
        if input_json.len() > 4096 {
            return Err(JsValue::from_str("password_login_input"));
        }
        let input: Value = serde_json::from_str(input_json)
            .map_err(|_| JsValue::from_str("password_login_input"))?;
        let field = |name: &str| input.get(name).and_then(Value::as_str).map(str::to_owned);
        let tfa = match (tfa, field("codeType")) {
            (Some(code), Some(kind)) => {
                Some((code, TfaCodeType::parse(&kind).map_err(code_error)?))
            }
            (None, None) => None,
            _ => return Err(JsValue::from_str("password_login_input")),
        };
        let (inner, request) = PasswordLogin::start(PasswordLoginInput {
            email: field("email").unwrap_or_default(),
            password,
            session_id: field("sessionId").unwrap_or_default(),
            user_email_salt: field("userEmailSalt").unwrap_or_default(),
            email_encryption_key: field("emailEncryptionKey"),
            stay_logged_in: input
                .get("stayLoggedIn")
                .and_then(Value::as_bool)
                .ok_or_else(|| JsValue::from_str("password_login_input"))?,
            tfa,
        })
        .map_err(code)?;
        Ok(Self {
            inner: Some(inner),
            pending: Some(json(&request)?),
        })
    }
    /// The next request (JSON `{method,path,headers,body}`), or undefined.
    pub fn request(&mut self) -> Option<String> {
        self.pending.take()
    }
    /// Returns true once the login response is terminal.
    pub fn reply(&mut self, status: u16, body: Option<String>) -> Result<bool, JsValue> {
        let inner = self
            .inner
            .as_mut()
            .ok_or_else(|| JsValue::from_str("protocol"))?;
        match inner.on_reply(reply(status, body)) {
            Ok(PasswordStep::Http(request)) => {
                self.pending = Some(json(&request)?);
                Ok(false)
            }
            Ok(PasswordStep::Finished) => Ok(true),
            Err(error) => {
                self.inner = None;
                Err(code(error))
            }
        }
    }
    /// `{kind: "response"|"unlocked"|"unlock_failed", status, data, credentialVersion?, key?, code?}`.
    pub async fn finish(mut self) -> Result<JsValue, JsValue> {
        let inner = self
            .inner
            .take()
            .ok_or_else(|| JsValue::from_str("protocol"))?;
        outcome_js(inner.finish().await.map_err(code)?).await
    }
}

/// `{kind: "response"|"unlocked"|"unlock_failed", status, data, credentialVersion?, key?, code?}`.
async fn outcome_js(outcome: PasswordOutcome) -> Result<JsValue, JsValue> {
    let output = js_sys::Object::new();
    let (kind, status, data) = match outcome {
        PasswordOutcome::Response { status, data } => ("response", status, data),
        PasswordOutcome::UnlockFailed { status, data, code } => {
            set(&output, "code", &JsValue::from_str(code))?;
            ("unlock_failed", status, data)
        }
        PasswordOutcome::Unlocked {
            status,
            data,
            master,
            credential_version,
        } => {
            set(&output, "key", &import_master(&master).await?)?;
            drop(master);
            set(
                &output,
                "credentialVersion",
                &JsValue::from(credential_version),
            )?;
            ("unlocked", status, data)
        }
    };
    set(&output, "kind", &JsValue::from_str(kind))?;
    set(&output, "status", &JsValue::from(status))?;
    set(&output, "data", &JsValue::from_str(&data.to_string()))?;
    Ok(output.into())
}

/// Recovery-key login: `start()` returns the request JSON via `request()`; the
/// page sends it and passes the reply to `finish()`.
#[wasm_bindgen]
pub struct WebAuthRecoveryLogin {
    inner: Option<RecoveryKeyLogin>,
    pending: Option<String>,
}

#[wasm_bindgen]
impl WebAuthRecoveryLogin {
    /// `input_json`: `{email, sessionId, userEmailSalt, emailEncryptionKey, stayLoggedIn}`.
    pub fn start(input_json: &str, recovery_key: String) -> Result<WebAuthRecoveryLogin, JsValue> {
        let recovery_key = Zeroizing::new(recovery_key);
        if input_json.len() > 4096 {
            return Err(JsValue::from_str("recovery_login_input"));
        }
        let input: Value = serde_json::from_str(input_json)
            .map_err(|_| JsValue::from_str("recovery_login_input"))?;
        let field = |name: &str| input.get(name).and_then(Value::as_str).map(str::to_owned);
        let (inner, request) = RecoveryKeyLogin::start(RecoveryKeyLoginInput {
            email: field("email").unwrap_or_default(),
            recovery_key,
            session_id: field("sessionId").unwrap_or_default(),
            user_email_salt: field("userEmailSalt").unwrap_or_default(),
            email_encryption_key: field("emailEncryptionKey"),
            stay_logged_in: input
                .get("stayLoggedIn")
                .and_then(Value::as_bool)
                .ok_or_else(|| JsValue::from_str("recovery_login_input"))?,
        })
        .map_err(code)?;
        Ok(Self {
            inner: Some(inner),
            pending: Some(json(&request)?),
        })
    }
    pub fn request(&mut self) -> Option<String> {
        self.pending.take()
    }
    pub async fn finish(mut self, status: u16, body: Option<String>) -> Result<JsValue, JsValue> {
        let inner = self
            .inner
            .take()
            .ok_or_else(|| JsValue::from_str("protocol"))?;
        outcome_js(inner.finish(reply(status, body)).await.map_err(code)?).await
    }
}
fn code_error(error: openmates_sdk::Error) -> JsValue {
    code(error)
}

/// `signals_json`: `[[name, value|null], ...]` in the page's insertion order.
#[wasm_bindgen]
pub fn web_auth_session_request(signals_json: &str, session_id: &str) -> Result<String, JsValue> {
    if signals_json.len() > 16 * 1024 {
        return Err(JsValue::from_str("session_request"));
    }
    let signals: Vec<(String, Option<String>)> =
        serde_json::from_str(signals_json).map_err(|_| JsValue::from_str("session_request"))?;
    json(&web_auth::session_request(&signals, session_id).map_err(code)?)
}
#[wasm_bindgen]
pub fn web_auth_classify_session(status: u16, body: Option<String>) -> Result<String, JsValue> {
    json(&web_auth::classify_session(reply(status, body)))
}
#[wasm_bindgen]
pub fn web_auth_missing_key_plan(context_json: &str) -> Result<String, JsValue> {
    let context =
        serde_json::from_str(context_json).map_err(|_| JsValue::from_str("missing_key_context"))?;
    json(&web_auth::missing_key_plan(context))
}
fn generation(value: f64) -> Result<u64, JsValue> {
    if value.is_finite() && value.fract() == 0.0 && (0.0..=9_007_199_254_740_991.0).contains(&value)
    {
        Ok(value as u64)
    } else {
        Err(JsValue::from_str("generation"))
    }
}
#[wasm_bindgen]
pub fn web_auth_logout_server_step(
    captured: f64,
    current: f64,
    skip_server_logout: bool,
    policy_violation: bool,
) -> Result<String, JsValue> {
    json(&web_auth::logout_server_step(
        generation(captured)?,
        generation(current)?,
        skip_server_logout,
        policy_violation,
    ))
}
#[wasm_bindgen]
pub fn web_auth_logout_may_delete_cookies(captured: f64, current: f64) -> Result<bool, JsValue> {
    Ok(web_auth::logout_may_delete_cookies(
        generation(captured)?,
        generation(current)?,
    ))
}
#[wasm_bindgen]
pub fn web_auth_logout_frame(tab_id: &str) -> Result<String, JsValue> {
    web_auth::logout_frame(tab_id).map_err(code)
}
#[wasm_bindgen]
pub fn web_auth_accept_logout_frame(frame_json: &str, own_tab_id: &str) -> bool {
    frame_json.len() <= 512
        && serde_json::from_str::<Value>(frame_json)
            .is_ok_and(|frame| web_auth::accept_logout_frame(&frame, own_tab_id))
}
