//! Explicit API-key Reminders facade over `/v1/sdk/reminders` (npm/Python parity).
use crate::sdk_ops::{require_confirmed, segment};
use crate::{OpenMates, Result};
use reqwest::Method;
use serde_json::Value;

pub struct Reminders<'a> {
    client: &'a OpenMates,
}
impl<'a> Reminders<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    async fn call(&self, method: Method, path: &str, body: Option<Value>) -> Result<Value> {
        self.client.verify_private_operation()?;
        self.client
            .task_request(method, path, body, false, None)
            .await
    }
    pub async fn list(&self) -> Result<Value> {
        self.call(Method::GET, "/v1/sdk/reminders", None).await
    }
    pub async fn update(&self, reminder_id: &str, input: Value) -> Result<Value> {
        let path = format!("/v1/sdk/reminders/{}", segment(reminder_id)?);
        self.call(Method::PATCH, &path, Some(input)).await
    }
    pub async fn delete(&self, reminder_id: &str, confirmed: bool) -> Result<Value> {
        require_confirmed(confirmed)?;
        let path = format!("/v1/sdk/reminders/{}", segment(reminder_id)?);
        self.call(Method::DELETE, &path, None).await
    }
}
