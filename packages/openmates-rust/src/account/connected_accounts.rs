//! Connected-account CLI import (npm connectedAccountImport.ts): a
//! passcode-protected `OMCA1.` transfer is decrypted locally (PBKDF2-SHA256
//! 100k + AES-256-GCM), validated by the server, then stored as a row whose
//! every sensitive field is re-encrypted with this account's master key.
use super::Account;
use crate::{Error, Result, crypto};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use reqwest::Method;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

const PREFIX: &str = "OMCA1.";
const ITERATIONS: u32 = 100_000;

fn b64url(value: &str) -> Result<Vec<u8>> {
    URL_SAFE_NO_PAD
        .decode(value.trim_end_matches('='))
        .map_err(|_| Error::Invalid("Connected account import payload is malformed."))
}
fn sha256_hex(value: &str) -> String {
    Sha256::digest(value.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
/// Decrypt and validate an `OMCA1.` transfer payload.
pub fn decrypt_connected_account_transfer(payload: &str, passcode: &str) -> Result<Value> {
    let encoded = payload.strip_prefix(PREFIX).ok_or(Error::Invalid(
        "Connected account import payload must start with OMCA1.",
    ))?;
    if passcode.trim().is_empty() {
        return Err(Error::Invalid(
            "A passcode is required to import a connected account.",
        ));
    }
    let envelope: Value = serde_json::from_slice(&b64url(encoded)?)
        .map_err(|_| Error::Invalid("Connected account import payload is malformed."))?;
    if envelope["version"] != 1
        || envelope["kdf"]["name"] != "PBKDF2-SHA256"
        || envelope["kdf"]["iterations"] != ITERATIONS
        || envelope["cipher"]["name"] != "AES-256-GCM"
    {
        return Err(Error::Invalid(
            "Unsupported connected account import payload format.",
        ));
    }
    let field = |v: &Value| v.as_str().map(b64url).transpose().ok().flatten();
    let undecryptable = Error::Invalid(
        "Could not decrypt connected account import payload. Check the passcode and payload.",
    );
    let (Some(salt), Some(iv), Some(text)) = (
        field(&envelope["kdf"]["salt"]),
        field(&envelope["cipher"]["iv"]),
        field(&envelope["cipher"]["text"]),
    ) else {
        return Err(undecryptable);
    };
    let mut key = Zeroizing::new([0u8; 32]);
    pbkdf2::pbkdf2_hmac::<Sha256>(passcode.as_bytes(), &salt, ITERATIONS, key.as_mut());
    let plaintext =
        Zeroizing::new(crypto::decrypt_aead(&text, &key, &iv, &[]).map_err(|_| undecryptable)?);
    let value: Value = serde_json::from_slice(&plaintext).map_err(|_| undecryptable)?;
    validate(&value)?;
    Ok(value)
}
fn validate(payload: &Value) -> Result<()> {
    if !payload.is_object() {
        return Err(Error::Invalid(
            "Connected account import payload is malformed.",
        ));
    }
    if payload["version"] != 1 {
        return Err(Error::Invalid(
            "Unsupported connected account import payload format.",
        ));
    }
    let present = |key: &str| payload[key].as_str().is_some_and(|v| !v.is_empty());
    if !present("provider_id") {
        return Err(Error::Invalid("Import payload is missing provider_id."));
    }
    if !present("app_id") {
        return Err(Error::Invalid("Import payload is missing app_id."));
    }
    if !payload["label"].is_string() {
        return Err(Error::Invalid("Import payload is missing label."));
    }
    if !payload["capabilities"].is_array() {
        return Err(Error::Invalid("Import payload is missing capabilities."));
    }
    if !payload["runtime_modes"].is_object() {
        return Err(Error::Invalid("Import payload is missing runtime_modes."));
    }
    if payload["refresh_token_bundle"]["refresh_token"]
        .as_str()
        .is_none_or(str::is_empty)
    {
        return Err(Error::Invalid(
            "Import payload is missing refresh token material.",
        ));
    }
    Ok(())
}
/// npm assertNoConnectedAccountSecretLeak (forbidden plaintext keys).
pub(crate) fn assert_no_secret(value: &Value) -> Result<()> {
    let serialized = value.to_string();
    for key in [
        "refresh_token",
        "access_token",
        "provider_email",
        "account_email",
        "provider_account_id",
        "bridge_password",
        "imap_password",
        "smtp_password",
        "proton_password",
        "password",
    ] {
        if serialized.contains(&format!("\"{key}\"")) {
            return Err(Error::Invalid(
                "Connected account payload contains a forbidden field.",
            ));
        }
    }
    Ok(())
}
/// npm buildEncryptedConnectedAccountImportRow.
pub(crate) fn import_row(payload: &Value, user_id: &str, master: &[u8; 32]) -> Result<Value> {
    let enc = |value: &Value| {
        let text = match value {
            Value::String(s) => s.clone(),
            other => other.to_string(),
        };
        crate::work::legacy_encrypt(text.as_bytes(), master)
    };
    let id = uuid::Uuid::new_v4().to_string();
    let provider = payload["provider_id"].as_str().unwrap_or("");
    let app = match payload["app_id"]
        .as_str()
        .filter(|a| !a.is_empty())
        .unwrap_or(provider)
    {
        "google_calendar" => "calendar",
        other => other,
    };
    let mut capabilities: Vec<String> = vec![];
    for c in payload["capabilities"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
    {
        if !c.trim().is_empty() && !capabilities.iter().any(|x| x == c) {
            capabilities.push(c.into());
        }
    }
    if capabilities.is_empty() {
        capabilities.push("read".into());
    }
    let mut actions: Vec<&str> = vec![];
    for c in &capabilities {
        let add: &[&str] = match c.as_str() {
            "read" => &["read"],
            "write" => &["write", "update"],
            "delete" => &["delete"],
            _ => &[],
        };
        for a in add {
            if !actions.contains(a) {
                actions.push(a);
            }
        }
    }
    if actions.is_empty() {
        actions.push("read");
    }
    let scopes = payload["refresh_token_bundle"]["scopes"]
        .as_array()
        .map(|s| {
            s.iter()
                .filter(|v| v.is_string())
                .cloned()
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let label = payload["label"]
        .as_str()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| {
            if provider == "google_calendar" {
                "Google Calendar".into()
            } else {
                "Connected account".into()
            }
        });
    let account_ref = payload["account_ref"]
        .as_str()
        .map(str::trim)
        .filter(|r| !r.is_empty())
        .unwrap_or(&id)
        .to_owned();
    let runtime_modes = if payload["runtime_modes"]
        .as_object()
        .is_some_and(|m| !m.is_empty())
    {
        payload["runtime_modes"].clone()
    } else {
        Value::Object(
            actions
                .iter()
                .map(|a| {
                    (
                        (*a).to_owned(),
                        json!(if *a == "read" {
                            "allow_automatically"
                        } else {
                            "always_ask"
                        }),
                    )
                })
                .collect(),
        )
    };
    Ok(json!({
        "id":id,
        "hashed_user_id":sha256_hex(user_id),
        "encrypted_provider_type":enc(&json!(provider))?,
        "provider_type_hash":sha256_hex(provider),
        "encrypted_account_label":enc(&json!(label))?,
        "encrypted_refresh_token_bundle":enc(&payload["refresh_token_bundle"])?,
        "encrypted_capabilities":enc(&json!(capabilities))?,
        "encrypted_app_permissions":enc(&json!({"app_id":app,"allowed_actions":actions,"scopes":scopes}))?,
        "encrypted_account_directory_hint":enc(&json!({"account_ref":account_ref,"label":label,"capabilities":capabilities,"runtime_modes":runtime_modes}))?,
    }))
}

/// Revolut Business OAuth consent URL (npm buildRevolutBusinessConsentUrl);
/// pure, no network. Sandbox unless `production`.
pub fn revolut_business_consent_url(
    production: bool,
    client_id: &str,
    redirect_uri: Option<&str>,
    scope: Option<&str>,
) -> Result<String> {
    let client_id = client_id.trim();
    if client_id.is_empty() {
        return Err(Error::Invalid("Missing Revolut Business client ID."));
    }
    let redirect = redirect_uri.unwrap_or(if production {
        "https://openmates.org/oauth/revolut-business/callback"
    } else {
        "https://app.dev.openmates.org/oauth/revolut-business/callback"
    });
    let mut url = url::Url::parse(if production {
        "https://business.revolut.com/app-confirm"
    } else {
        "https://sandbox-business.revolut.com/app-confirm"
    })
    .map_err(|_| Error::Protocol)?;
    let scope = scope
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("READ");
    url.query_pairs_mut()
        .append_pair("client_id", client_id)
        .append_pair("redirect_uri", redirect.trim())
        .append_pair("response_type", "code")
        .append_pair("scope", scope);
    Ok(url.into())
}
/// Revolut Business authorization-code token endpoint.
pub fn revolut_business_token_url(production: bool) -> &'static str {
    if production {
        "https://b2b.revolut.com/api/1.0/auth/token"
    } else {
        "https://sandbox-b2b.revolut.com/api/1.0/auth/token"
    }
}

impl Account<'_> {
    /// Import an `OMCA1.` connected-account transfer into this account.
    /// Returns `{id, provider_id, app_id, label, validation}`.
    pub async fn import_connected_account(
        &mut self,
        payload: &str,
        passcode: &str,
    ) -> Result<Value> {
        self.client.require_session()?;
        let transfer = decrypt_connected_account_transfer(payload, passcode)?;
        let validation = self
            .client
            .request(
                Method::POST,
                "/v1/connected-accounts/validate-import",
                Some(json!({"provider_id":transfer["provider_id"],"app_id":transfer["app_id"],
                    "capabilities":transfer["capabilities"],"refresh_token_envelope":transfer["refresh_token_bundle"]})),
            )
            .await?;
        if validation["valid"] != true {
            return Err(Error::Invalid("Connected account validation failed."));
        }
        assert_no_secret(&validation)?;
        let user = self.profile().await?;
        let user_id = user["id"]
            .as_str()
            .or(user["user_id"].as_str())
            .filter(|v| !v.is_empty())
            .ok_or(Error::Invalid(
                "Could not resolve current user id for connected account import.",
            ))?
            .to_owned();
        let master = self.client.require_session()?.master_key.clone();
        let row = import_row(&transfer, &user_id, &master)?;
        assert_no_secret(&row)?;
        let stored = self
            .client
            .request(Method::POST, "/v1/connected-accounts", Some(row))
            .await?;
        let id = stored["id"]
            .as_str()
            .filter(|v| !v.is_empty())
            .ok_or(Error::Protocol)?;
        Ok(
            json!({"id":id,"provider_id":transfer["provider_id"],"app_id":transfer["app_id"],
            "label":transfer["label"],"validation":validation}),
        )
    }
}

/// npm decryptConnectedAccountField: AES-GCM "combined" text, JSON when it
/// parses, otherwise the plaintext; undecryptable or absent fields are null.
pub(crate) fn decrypt_field(value: &Value, master: &[u8; 32]) -> Value {
    let Some(text) = value.as_str().filter(|v| !v.is_empty()) else {
        return Value::Null;
    };
    match crypto::decrypt_combined(text, master) {
        Ok(plain) => serde_json::from_str(&plain).unwrap_or(Value::String(plain)),
        Err(_) => Value::Null,
    }
}
fn string_array(value: &Value) -> Vec<String> {
    let mut out: Vec<String> = vec![];
    for item in value.as_array().into_iter().flatten() {
        let text = match item {
            Value::String(s) => s.trim().to_owned(),
            other => other.to_string(),
        };
        if !text.is_empty() && !out.contains(&text) {
            out.push(text);
        }
    }
    out
}
/// One encrypted connected-account row decrypted for a skill run (npm
/// decryptConnectedAccountForSkill candidate). `None` when it belongs to a
/// different provider or App. Missing refresh-token material is an error.
pub fn skill_account_candidate(
    row: &Value,
    app_id: &str,
    provider_id: &str,
    master: &[u8; 32],
) -> Result<Option<Value>> {
    let id = match &row["id"] {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    };
    let provider = match decrypt_field(&row["encrypted_provider_type"], master) {
        Value::String(s) => s,
        Value::Null => "null".into(),
        other => other.to_string(),
    };
    if provider != provider_id {
        return Ok(None);
    }
    let permissions = decrypt_field(&row["encrypted_app_permissions"], master);
    let app = if permissions.is_object() {
        match &permissions["app_id"] {
            Value::Null => app_id.to_owned(),
            Value::String(s) => s.clone(),
            other => other.to_string(),
        }
    } else {
        app_id.to_owned()
    };
    if app != app_id {
        return Ok(None);
    }
    let label = match decrypt_field(&row["encrypted_account_label"], master) {
        Value::String(s) => s,
        Value::Null => provider.clone(),
        other => other.to_string(),
    };
    let mut capabilities = string_array(&decrypt_field(&row["encrypted_capabilities"], master));
    if capabilities.is_empty() {
        capabilities.push("read".into());
    }
    let hint = decrypt_field(&row["encrypted_account_directory_hint"], master);
    let account_ref = match &hint["account_ref"] {
        Value::Null => id.clone(),
        Value::String(s) => s.clone(),
        other => other.to_string(),
    };
    let runtime_modes = if hint["runtime_modes"].is_object() {
        hint["runtime_modes"].clone()
    } else {
        json!({"read":"allow_automatically"})
    };
    let bundle = decrypt_field(&row["encrypted_refresh_token_bundle"], master);
    if !bundle.is_object() {
        return Err(Error::Invalid(
            "Connected account is missing encrypted refresh-token material.",
        ));
    }
    Ok(Some(json!({"id":id,"provider_id":provider,"app_id":app,"label":label,
        "account_ref":account_ref,"capabilities":capabilities,"runtime_modes":runtime_modes,
        "refresh_token_bundle":bundle})))
}
fn path_segment(value: &str) -> Result<&str> {
    if value.is_empty()
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
    {
        return Err(Error::Invalid("Invalid App or skill identifier."));
    }
    Ok(value)
}

impl Account<'_> {
    /// npm importConnectedAccountPayload(payload, {skipValidation:true}):
    /// encrypt an already server-validated payload and store it.
    pub async fn store_validated_connected_account(&mut self, payload: &Value) -> Result<Value> {
        self.client.require_session()?;
        let user = self.profile().await?;
        let user_id = user["id"]
            .as_str()
            .or(user["user_id"].as_str())
            .filter(|v| !v.is_empty())
            .ok_or(Error::Invalid(
                "Could not resolve current user id for connected account import.",
            ))?
            .to_owned();
        let master = self.client.require_session()?.master_key.clone();
        let row = import_row(payload, &user_id, &master)?;
        assert_no_secret(&row)?;
        let stored = self
            .client
            .request(Method::POST, "/v1/connected-accounts", Some(row))
            .await?;
        let id = stored["id"]
            .as_str()
            .filter(|v| !v.is_empty())
            .ok_or(Error::Protocol)?;
        Ok(json!({"id":id,"provider_id":payload["provider_id"],"app_id":payload["app_id"],"label":payload["label"]}))
    }
    /// POST /v1/connected-accounts/setup/revolut-business/exchange-code.
    pub async fn exchange_revolut_business_setup_code(
        &mut self,
        client_id: &str,
        code: &str,
        private_key_pem: &str,
        production: bool,
        redirect_uri: &str,
    ) -> Result<Value> {
        self.client.require_session()?;
        let result = self
            .client
            .request(
                Method::POST,
                "/v1/connected-accounts/setup/revolut-business/exchange-code",
                Some(json!({"client_id":client_id,"code":code,"private_key_pem":private_key_pem,
                    "environment":if production {"production"} else {"sandbox"},"redirect_uri":redirect_uri})),
            )
            .await?;
        if result["provider_id"] != "revolut_business" {
            return Err(Error::Invalid("Revolut Business setup exchange failed."));
        }
        Ok(result)
    }
    /// Public egress IPs Revolut must whitelist; `None` when unavailable.
    pub async fn revolut_business_server_egress_ip(&mut self) -> Option<Value> {
        self.client
            .request(
                Method::GET,
                "/v1/connected-accounts/setup/revolut-business/server-egress-ip",
                None,
            )
            .await
            .ok()
    }
    /// Decrypted connected accounts for one App/provider (npm
    /// decryptConnectedAccountForSkill candidates, before selection).
    pub async fn connected_accounts_for_skill(
        &mut self,
        account_id: Option<&str>,
        app_id: &str,
        provider_id: &str,
    ) -> Result<Vec<Value>> {
        self.client.require_session()?;
        let listed = self
            .client
            .request(Method::GET, "/v1/connected-accounts", None)
            .await?;
        let rows = listed["rows"].as_array().ok_or(Error::Protocol)?.clone();
        let master = self.client.require_session()?.master_key.clone();
        let mut out = vec![];
        for row in &rows {
            if account_id.is_some_and(|wanted| row["id"].as_str() != Some(wanted)) {
                continue;
            }
            if let Some(candidate) = skill_account_candidate(row, app_id, provider_id, &master)? {
                out.push(candidate);
            }
        }
        Ok(out)
    }
    /// POST /v1/sdk/connected-account-skills/{app}/{skill}: the server-mediated
    /// skill run with short-lived connected-account token refs.
    pub async fn run_connected_account_skill(
        &mut self,
        app_id: &str,
        skill_id: &str,
        body: Value,
    ) -> Result<Value> {
        self.client.require_session()?;
        let route = format!(
            "/v1/sdk/connected-account-skills/{}/{}",
            path_segment(app_id)?,
            path_segment(skill_id)?
        );
        self.client.request(Method::POST, &route, Some(body)).await
    }
}

#[cfg(test)]
#[path = "connected_accounts_tests.rs"]
mod tests;
