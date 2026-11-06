//! Explicit API-key Settings facade over `/v1/sdk/settings/*` (npm/Python parity).
use crate::{Error, OpenMates, Result};
use reqwest::Method;
use serde_json::{Value, json};

/// `None` serializes as JSON null, exactly like the maintained SDKs.
#[derive(Clone, Debug, Default)]
pub struct ModelDefaults {
    pub default_ai_model_simple: Option<String>,
    pub default_ai_model_complex: Option<String>,
    pub default_ai_model_most_demanding: Option<String>,
}
pub struct Settings<'a> {
    client: &'a OpenMates,
}
impl<'a> Settings<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    async fn post(&self, path: &str, body: Value) -> Result<Value> {
        self.client.verify_private_operation()?;
        self.client
            .task_request(Method::POST, path, Some(body), false, None)
            .await
    }
    pub async fn set_language(&self, language: &str) -> Result<Value> {
        self.post("/v1/sdk/settings/language", json!({ "language": language }))
            .await
    }
    pub async fn set_dark_mode(&self, enabled: bool) -> Result<Value> {
        self.post("/v1/sdk/settings/dark-mode", json!({ "enabled": enabled }))
            .await
    }
    pub async fn set_font(&self, font: &str) -> Result<Value> {
        self.post("/v1/sdk/settings/font", json!({ "font": font }))
            .await
    }
    pub async fn set_model_defaults(&self, defaults: ModelDefaults) -> Result<Value> {
        let body = json!({
            "default_ai_model_simple": defaults.default_ai_model_simple,
            "default_ai_model_complex": defaults.default_ai_model_complex,
            "default_ai_model_most_demanding": defaults.default_ai_model_most_demanding,
        });
        self.post("/v1/sdk/settings/ai-model-defaults", body).await
    }
    pub async fn set_chat_auto_delete(&self, period: &str) -> Result<Value> {
        self.post(
            "/v1/sdk/settings/auto-delete/chats",
            json!({ "period": period }),
        )
        .await
    }
    /// Debug-log sharing is not offered through any API-key SDK (matches npm/Python).
    pub async fn share_debug_logs(&self, confirmed: bool, _duration: &str) -> Result<Value> {
        crate::sdk_ops::require_confirmed(confirmed)?;
        Err(Error::Unavailable {
            code: "unsupported",
            reason: "Debug-log sharing is not available through the API-key SDK yet.",
        })
    }
}
