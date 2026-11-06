//! Explicit API-key Notifications facade (npm/Python parity). Read-only.
use crate::sdk_ops::with_query;
use crate::{OpenMates, Result};
use reqwest::Method;
use serde_json::Value;

pub struct Notifications<'a> {
    client: &'a OpenMates,
}
impl<'a> Notifications<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    async fn get(&self, path: &str) -> Result<Value> {
        self.client.verify_private_operation()?;
        self.client
            .task_request(Method::GET, path, None, false, None)
            .await
    }
    pub async fn status(&self) -> Result<Value> {
        self.get("/v1/sdk/notifications/status").await
    }
    pub async fn list(&self, limit: Option<u32>) -> Result<Value> {
        let limit = limit.map(|l| l.to_string());
        let query: Vec<(&str, &str)> = limit.iter().map(|l| ("limit", l.as_str())).collect();
        self.get(&with_query("/v1/sdk/notifications", &query)).await
    }
}
