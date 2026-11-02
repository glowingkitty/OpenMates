//! Owner-scoped settings, billing and account-export operations that mirror the
//! legacy CLI's settingsGet/settingsPatch/settingsDelete and payments routes.
//! Every route is fixed; caller IDs are validated as one safe path segment.
//! Payments that need the email key derive it locally from the explicit
//! session; no credentials, profile files or environment are read.
use super::Account;
use crate::{Error, Result, crypto};
use reqwest::Method;
use serde_json::{Value, json};
use zeroize::Zeroizing;

/// A caller-supplied identifier is one URL path segment: ASCII letters,
/// digits, `-`, `_` and `.` only, never `.`/`..`, at most 256 bytes.
pub(crate) fn segment<'a>(value: &'a str, label: &'static str) -> Result<&'a str> {
    if value.is_empty()
        || value.len() > 256
        || value == "."
        || value == ".."
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
    {
        return Err(Error::Invalid(label));
    }
    Ok(value)
}

/// Scope of a stored-file deletion, exactly as the legacy settings route takes it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StoredFileDeletion<'a> {
    Single(&'a str),
    Category(&'a str),
    All,
}

impl Account<'_> {
    async fn settings(
        &mut self,
        method: Method,
        route: &str,
        body: Option<Value>,
    ) -> Result<Value> {
        self.client.require_session()?;
        self.client.request(method, route, body).await
    }

    /// PATCH /v1/settings/reminders/{id} with the caller's explicit JSON object.
    pub async fn update_reminder(&mut self, id: &str, body: Value) -> Result<Value> {
        let id = segment(id, "Invalid reminder ID.")?;
        if body.as_object().is_none_or(|fields| fields.is_empty()) {
            return Err(Error::Invalid(
                "Provide --data '<json>' or a supported flag.",
            ));
        }
        self.settings(
            Method::PATCH,
            &format!("/v1/settings/reminders/{id}"),
            Some(body),
        )
        .await
    }

    /// DELETE /v1/settings/reminders/{id}; the caller owns confirmation.
    pub async fn delete_reminder(&mut self, id: &str) -> Result<Value> {
        let id = segment(id, "Invalid reminder ID.")?;
        self.settings(
            Method::DELETE,
            &format!("/v1/settings/reminders/{id}"),
            None,
        )
        .await
    }

    /// Account email encryption key: the session copy, else derived locally
    /// from the freshly authenticated master-key-encrypted email.
    async fn email_encryption_key(&mut self) -> Result<Zeroizing<String>> {
        if let Some(key) = self.client.require_session()?.email_encryption_key.clone() {
            return Ok(Zeroizing::new(key));
        }
        let user = self.profile().await?;
        let encrypted = user["encrypted_email_with_master_key"]
            .as_str()
            .ok_or(Error::Unavailable {
                code: "email_encryption_key_missing",
                reason: "Email encryption key is missing. Run `openmates login` again to refresh your local encryption keys.",
            })?;
        let session = self.client.require_session()?;
        let email = Zeroizing::new(crypto::decrypt_combined(encrypted, &session.master_key)?);
        Ok(Zeroizing::new(crypto::derive_email_key(
            &email,
            &session.user_email_salt,
        )?))
    }

    /// POST /v1/payments/redeem-gift-card. The server response is returned as-is.
    pub async fn redeem_gift_card(&mut self, code: &str) -> Result<Value> {
        let code = code.trim();
        if code.is_empty() || code.len() > 128 || code.chars().any(char::is_control) {
            return Err(Error::Invalid("Missing gift card code."));
        }
        let key = self.email_encryption_key().await?;
        self.settings(
            Method::POST,
            "/v1/payments/redeem-gift-card",
            Some(json!({"code":code,"email_encryption_key":key.as_str()})),
        )
        .await
    }

    pub async fn redeemed_gift_cards(&mut self) -> Result<Value> {
        self.settings(Method::GET, "/v1/payments/redeemed-gift-cards", None)
            .await
    }

    /// GET /v1/payments/invoices normalized to `{"invoices":[...]}`.
    pub async fn invoices(&mut self) -> Result<Value> {
        let data = self
            .settings(Method::GET, "/v1/payments/invoices", None)
            .await?;
        let invoices = match data.get("invoices") {
            None | Some(Value::Null) => json!([]),
            Some(Value::Array(rows)) => Value::Array(rows.clone()),
            Some(_) => return Err(Error::Protocol),
        };
        Ok(json!({"invoices":invoices}))
    }

    pub async fn bank_transfer_orders(&mut self) -> Result<Value> {
        self.settings(Method::GET, "/v1/payments/bank-transfer-pending", None)
            .await
    }

    pub async fn account_export(&mut self, id: &str) -> Result<Value> {
        let id = segment(id, "Invalid export ID.")?;
        self.settings(Method::GET, &format!("/v1/account-exports/{id}"), None)
            .await
    }

    /// Without an export ID this is the legacy whole-account manifest read.
    pub async fn account_export_manifest(&mut self, id: Option<&str>) -> Result<Value> {
        let route = match id {
            Some(id) => format!(
                "/v1/account-exports/{}/manifest",
                segment(id, "Invalid export ID.")?
            ),
            None => "/v1/settings/export-account-manifest".into(),
        };
        self.settings(Method::GET, &route, None).await
    }

    pub async fn account_export_chunks(&mut self, id: &str) -> Result<Value> {
        let id = segment(id, "Invalid export ID.")?;
        self.settings(
            Method::GET,
            &format!("/v1/account-exports/{id}/chunks"),
            None,
        )
        .await
    }

    /// One chunk's `chunk` object; a response without it is a protocol error.
    pub async fn account_export_chunk(&mut self, id: &str, chunk: &str) -> Result<Value> {
        let id = segment(id, "Invalid export ID.")?;
        let chunk = segment(chunk, "Invalid export chunk ID.")?;
        let data = self
            .settings(
                Method::GET,
                &format!("/v1/account-exports/{id}/chunks/{chunk}"),
                None,
            )
            .await?;
        data.get("chunk")
            .filter(|chunk| chunk.is_object())
            .cloned()
            .ok_or(Error::Protocol)
    }

    /// Legacy whole-account export data read (settingsGet("export-account-data")).
    pub async fn account_export_data(&mut self) -> Result<Value> {
        self.settings(Method::GET, "/v1/settings/export-account-data", None)
            .await
    }

    pub async fn accept_partial_account_export(&mut self, id: &str) -> Result<Value> {
        let id = segment(id, "Invalid export ID.")?;
        self.settings(
            Method::POST,
            &format!("/v1/account-exports/{id}/accept-partial"),
            Some(json!({})),
        )
        .await
    }

    pub async fn cancel_account_export(&mut self, id: &str) -> Result<Value> {
        let id = segment(id, "Invalid export ID.")?;
        self.settings(
            Method::POST,
            &format!("/v1/account-exports/{id}/cancel"),
            Some(json!({})),
        )
        .await
    }

    pub async fn delete_account_preview(&mut self) -> Result<Value> {
        self.settings(Method::GET, "/v1/settings/delete-account-preview", None)
            .await
    }

    /// DELETE /v1/settings/storage/files. Irreversible; the caller confirms.
    pub async fn delete_stored_files(&mut self, scope: StoredFileDeletion<'_>) -> Result<Value> {
        let body = match scope {
            StoredFileDeletion::Single(id) => {
                json!({"scope":"single","file_id":segment(id, "Missing file ID.")?})
            }
            StoredFileDeletion::Category(category) => {
                json!({"scope":"category","category":segment(category, "Invalid storage category.")?})
            }
            StoredFileDeletion::All => json!({"scope":"all"}),
        };
        self.settings(Method::DELETE, "/v1/settings/storage/files", Some(body))
            .await
    }
}

/// Actions that the legacy settings route confirms with an emailed code.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VerifiedAction {
    DeleteAccount,
    DeleteTeam,
}
impl VerifiedAction {
    fn wire(self) -> &'static str {
        match self {
            Self::DeleteAccount => "delete_account",
            Self::DeleteTeam => "delete_team",
        }
    }
}
impl Account<'_> {
    /// `/v1/auth/methods` (`has_2fa` decides how deletion is confirmed).
    pub async fn auth_methods(&mut self) -> Result<Value> {
        self.settings(Method::GET, "/v1/auth/methods", None).await
    }
    /// Email a confirmation code for a destructive action.
    pub async fn request_action_email_code(&mut self, action: VerifiedAction) -> Result<Value> {
        let key = self.email_encryption_key().await?;
        self.settings(
            Method::POST,
            "/v1/settings/request-action-verification",
            Some(json!({"action":action.wire(),"email_encryption_key":key.as_str()})),
        )
        .await
    }
    pub async fn verify_action_email_code(&mut self, action: VerifiedAction, code: &str) -> Result<Value> {
        self.settings(
            Method::POST,
            "/v1/settings/verify-action-code",
            Some(json!({"action":action.wire(),"code":code})),
        )
        .await
    }
    /// Delete the account after the email code (and 2FA code, when enabled)
    /// were verified. On success the SDK forgets this session so the caller's
    /// persistence clears its stored credentials, like npm's purge.
    pub async fn delete_account(&mut self, totp_code: Option<&str>) -> Result<Value> {
        let key = self.email_encryption_key().await?;
        let mut body = json!({"confirm_data_deletion":true,
            "auth_method":if totp_code.is_some() {"2fa_otp"} else {"email_otp"},
            "email_encryption_key":key.as_str(),"require_email_verification":true});
        if let Some(code) = totp_code {
            body["auth_code"] = json!(code);
        }
        let result = self
            .settings(Method::POST, "/v1/settings/delete-account", Some(body))
            .await?;
        self.client.forget_session();
        Ok(result)
    }
}

/// Account Export V1 job options (npm startAccountExport).
#[derive(Clone, Debug, Default)]
pub struct AccountExportStart {
    pub domains: Option<Vec<String>>,
    pub filters: Value,
    pub directory_format: bool,
    pub include_advanced_metadata: bool,
}
impl Account<'_> {
    /// POST /v1/account-exports; returns the server's `{export: ...}` record.
    pub async fn start_account_export(&mut self, input: AccountExportStart) -> Result<Value> {
        let filters = if input.filters.is_null() { json!({}) } else { input.filters };
        if !filters.is_object() {
            return Err(Error::Invalid("Account export filters must be a JSON object."));
        }
        let mut body = json!({"filters":filters,"format":if input.directory_format {"directory"} else {"zip"},
            "include_advanced_metadata":input.include_advanced_metadata});
        if let Some(domains) = input.domains {
            body["domains"] = json!(domains);
        }
        self.settings(Method::POST, "/v1/account-exports", Some(body)).await
    }
    pub async fn complete_account_export(&mut self, id: &str) -> Result<Value> {
        let id = segment(id, "Invalid export ID.")?;
        self.settings(
            Method::POST,
            &format!("/v1/account-exports/{id}/complete"),
            Some(json!({})),
        )
        .await
    }
}

#[cfg(test)]
#[path = "settings_delete_tests.rs"]
mod delete_tests;

#[cfg(test)]
#[path = "settings_ops_tests.rs"]
mod tests;
