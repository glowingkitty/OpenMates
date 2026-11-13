//! Local connected-account connectors (for example Proton Mail Bridge). The
//! connector process stays on the user's machine; the account registers an
//! encrypted connected-account row plus public metadata, keeps a heartbeat and
//! answers server requests relayed over the session WebSocket. Provider
//! credentials never enter any request built here (npm registerLocalConnected-
//! AccountConnector / sendLocalConnectedAccountConnectorHeartbeat parity).
use super::Account;
use super::connected_accounts::assert_no_secret;
use crate::{Error, Result};
use reqwest::Method;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

/// Identifiers the server assigned to a registered connector.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LocalConnectorSession {
    pub connected_account_id: String,
    pub connector_session_id: String,
    pub heartbeat_interval_ms: Option<u64>,
}
fn segment(value: &str) -> Result<String> {
    if value.is_empty()
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_".contains(&b))
    {
        return Err(Error::Invalid("Invalid connector session identifier."));
    }
    Ok(value.to_owned())
}
fn sha256_hex(value: &str) -> String {
    Sha256::digest(value.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn text<'a>(registration: &'a Value, key: &str) -> Result<&'a str> {
    registration[key]
        .as_str()
        .filter(|v| !v.is_empty())
        .ok_or(Error::Invalid(
            "Local connector registration is incomplete.",
        ))
}
/// The registration body for `POST /v1/connected-accounts/local-connectors`.
pub(crate) fn registration_body(
    registration: &Value,
    user_id: &str,
    master: &[u8; 32],
) -> Result<Value> {
    assert_no_secret(registration)?;
    let provider = text(registration, "provider_id")?;
    let app = text(registration, "app_id")?;
    let label = text(registration, "label")?;
    let capabilities = registration["capabilities"].clone();
    let writes = capabilities
        .as_array()
        .is_some_and(|c| c.iter().any(|v| v == "write"));
    let enc = |value: &Value| {
        let plain = match value {
            Value::String(s) => s.clone(),
            other => other.to_string(),
        };
        crate::work::legacy_encrypt(plain.as_bytes(), master)
    };
    let modes: serde_json::Map<String, Value> = capabilities
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(|c| {
            (
                c.to_owned(),
                json!(if c == "read" {
                    "allow_automatically"
                } else {
                    "always_ask"
                }),
            )
        })
        .collect();
    let body = json!({
        "id": uuid::Uuid::new_v4().to_string(),
        "hashed_user_id": sha256_hex(user_id),
        "encrypted_provider_type": enc(&json!(provider))?,
        "provider_type_hash": sha256_hex(provider),
        "encrypted_account_label": enc(&json!(label))?,
        "encrypted_capabilities": enc(&capabilities)?,
        "encrypted_app_permissions": enc(&json!({
            "app_id": app,
            "allowed_actions": if writes { json!(["read", "write"]) } else { json!(["read"]) },
            "runtime_modes": modes,
        }))?,
        "encrypted_account_directory_hint": enc(&json!({"label": label, "app_id": app, "runtime": "local_connector"}))?,
        "execution_mode": "local_connector",
        "connector_provider_id": provider,
        "connector_instance_id": text(registration, "connector_instance_id")?,
        "connector_status": registration["status"],
        "connector_public_metadata": registration["metadata"],
    });
    assert_no_secret(&body)?;
    Ok(body)
}
impl Account<'_> {
    pub async fn register_local_connector(
        &mut self,
        registration: &Value,
    ) -> Result<LocalConnectorSession> {
        self.client.require_session()?;
        let user = self.profile().await?;
        let user_id = user["id"]
            .as_str()
            .or(user["user_id"].as_str())
            .filter(|v| !v.is_empty())
            .ok_or(Error::Invalid(
                "Could not resolve current user id for local connected-account connector.",
            ))?
            .to_owned();
        let master = self.client.require_session()?.master_key.clone();
        let body = registration_body(registration, &user_id, &master)?;
        let reply = self
            .client
            .request(
                Method::POST,
                "/v1/connected-accounts/local-connectors",
                Some(body),
            )
            .await?;
        assert_no_secret(&reply)?;
        let field = |key: &str| {
            reply[key]
                .as_str()
                .filter(|v| !v.is_empty())
                .map(str::to_owned)
        };
        Ok(LocalConnectorSession {
            connected_account_id: field("connected_account_id").ok_or(Error::Protocol)?,
            connector_session_id: field("connector_session_id").ok_or(Error::Protocol)?,
            heartbeat_interval_ms: reply["heartbeat_interval_ms"].as_u64(),
        })
    }
    pub async fn local_connector_heartbeat(
        &mut self,
        session: &LocalConnectorSession,
        online: bool,
        capabilities: &[&str],
        health_summary: Value,
    ) -> Result<Value> {
        self.client.require_session()?;
        let body = json!({
            "connected_account_id": session.connected_account_id,
            "status": if online { "online" } else { "offline" },
            "capabilities": capabilities,
            "health_summary": health_summary,
        });
        assert_no_secret(&body)?;
        let route = format!(
            "/v1/connected-accounts/local-connectors/{}/heartbeat",
            segment(&session.connector_session_id)?
        );
        self.client.request(Method::POST, &route, Some(body)).await
    }
    /// `status` is `ok`, `error` or `cancelled`.
    pub async fn complete_local_connector_request(
        &mut self,
        session: &LocalConnectorSession,
        request_id: &str,
        status: &str,
        result: Value,
        error: Option<(&str, &str)>,
    ) -> Result<Value> {
        self.client.require_session()?;
        if !matches!(status, "ok" | "error" | "cancelled") {
            return Err(Error::Invalid("Unknown local connector request status."));
        }
        let body = json!({
            "connected_account_id": session.connected_account_id,
            "request_id": request_id,
            "status": status,
            "result": result,
            "error_code": error.map(|e| e.0),
            "error_message": error.map(|e| e.1),
        });
        assert_no_secret(&body)?;
        let route = format!(
            "/v1/connected-accounts/local-connectors/{}/complete-request",
            segment(&session.connector_session_id)?
        );
        self.client.request(Method::POST, &route, Some(body)).await
    }
    pub async fn open_local_connector_socket(
        &mut self,
    ) -> Result<crate::account::LocalConnectorSocket> {
        self.client.open_local_connector_socket().await
    }
}
