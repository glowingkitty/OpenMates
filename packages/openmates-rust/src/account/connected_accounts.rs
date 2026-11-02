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
fn assert_no_secret(value: &Value) -> Result<()> {
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

#[cfg(test)]
#[path = "connected_accounts_tests.rs"]
mod tests;
