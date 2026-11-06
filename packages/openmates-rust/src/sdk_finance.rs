//! Explicit API-key Finance facade: connected-account-only Finance skills run
//! through the server-mediated `/v1/sdk/connected-account-skills/*` route. Token
//! refs are short-lived server handles supplied by the caller; no provider
//! credentials are read or stored here.
use crate::{Error, OpenMates, Result};
use reqwest::Method;
use serde_json::{Value, json};

#[derive(Clone, Debug, Default)]
pub struct CheckAccountsOptions {
    pub connected_account_token_ref_inputs: Vec<Value>,
    pub chat_id: Option<String>,
    pub message_id: Option<String>,
    pub prompt_injection_protection: Option<bool>,
}
pub struct Finance<'a> {
    client: &'a OpenMates,
}
impl<'a> Finance<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    pub async fn check_accounts(
        &self,
        input: Value,
        options: CheckAccountsOptions,
    ) -> Result<Value> {
        self.client.verify_private_operation()?;
        let mut input = input;
        // Same projection as the maintained SDKs: only an explicit `false` is sent,
        // as security.prompt_injection_protection = "disabled".
        if options.prompt_injection_protection == Some(false) {
            let map = input
                .as_object_mut()
                .ok_or(Error::Invalid("Finance input must be an object."))?;
            let security = map.entry("security").or_insert_with(|| json!({}));
            if !security.is_object() {
                *security = json!({});
            }
            security["prompt_injection_protection"] = json!("disabled");
        }
        let body = json!({
            "input": input,
            "connected_account_token_ref_inputs": options.connected_account_token_ref_inputs,
            "chat_id": options.chat_id,
            "message_id": options.message_id,
        });
        self.client
            .task_request(
                Method::POST,
                "/v1/sdk/connected-account-skills/finance/check_accounts",
                Some(body),
                false,
                None,
            )
            .await
    }
}
