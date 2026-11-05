//! Small owner-scoped settings writes that mirror the legacy CLI's
//! `settingsPost` branches: issue reports, chat auto-deletion, debug-log
//! sharing, AI model defaults and mate consent. Every route is fixed.
use super::{Account, settings_ops::segment};
use crate::{Error, Result};
use reqwest::Method;
use serde_json::{Value, json};

impl Account<'_> {
    async fn settings_call(&mut self, method: Method, route: &str, body: Option<Value>) -> Result<Value> {
        self.client.require_session()?;
        self.client.request(method, route, body).await
    }

    /// POST /v1/settings/issues
    pub async fn report_issue(&mut self, title: &str, description: &str) -> Result<Value> {
        self.settings_call(
            Method::POST,
            "/v1/settings/issues",
            Some(json!({"title":title,"description":description})),
        )
        .await
    }

    /// GET /v1/settings/issues/{id}/status
    pub async fn report_issue_status(&mut self, id: &str) -> Result<Value> {
        let id = segment(id, "Invalid issue ID.")?;
        self.settings_call(Method::GET, &format!("/v1/settings/issues/{id}/status"), None)
            .await
    }

    /// POST /v1/settings/auto-delete-chats
    pub async fn set_chat_auto_delete(&mut self, period: &str) -> Result<Value> {
        if period.trim().is_empty() {
            return Err(Error::Invalid("Missing period."));
        }
        self.settings_call(
            Method::POST,
            "/v1/settings/auto-delete-chats",
            Some(json!({"period":period})),
        )
        .await
    }

    /// POST /v1/settings/debug-session
    pub async fn share_debug_logs(&mut self, duration: &str) -> Result<Value> {
        self.settings_call(
            Method::POST,
            "/v1/settings/debug-session",
            Some(json!({"duration":duration})),
        )
        .await
    }

    /// POST /v1/settings/ai-model-defaults with only the supplied keys; a
    /// `None` value means "auto" and is sent as JSON null.
    pub async fn set_ai_model_defaults(
        &mut self,
        simple: Option<Option<&str>>,
        complex: Option<Option<&str>>,
        most_demanding: Option<Option<&str>>,
    ) -> Result<Value> {
        let mut body = serde_json::Map::new();
        for (key, value) in [
            ("default_ai_model_simple", simple),
            ("default_ai_model_complex", complex),
            ("default_ai_model_most_demanding", most_demanding),
        ] {
            if let Some(value) = value {
                body.insert(key.into(), value.map_or(Value::Null, |v| json!(v)));
            }
        }
        if body.is_empty() {
            return Err(Error::Invalid(
                "Provide --simple, --complex, and/or --most-demanding <model-id|auto>.",
            ));
        }
        self.settings_call(Method::POST, "/v1/settings/ai-model-defaults", Some(Value::Object(body)))
            .await
    }

    /// POST /v1/settings/user/consent/mates
    pub async fn record_mates_consent(&mut self) -> Result<Value> {
        self.settings_call(
            Method::POST,
            "/v1/settings/user/consent/mates",
            Some(json!({"consent":true})),
        )
        .await
    }
}

#[cfg(test)]
#[path = "settings_extra_tests.rs"]
mod tests;
