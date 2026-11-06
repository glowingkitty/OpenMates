//! Explicit API-key connected-account import (npm/Python parity). The OMCA1
//! transfer payload is decrypted locally with the user's passcode, re-encrypted
//! with the API-key-wrapped account key and posted as an opaque row. The passcode,
//! refresh token and master key never leave memory and are never logged.
use crate::account::{assert_no_secret, decrypt_connected_account_transfer, import_row};
use crate::{Error, OpenMates, Result};
use reqwest::Method;
use serde_json::{Value, json};

pub struct ConnectedAccounts<'a> {
    client: &'a mut OpenMates,
}
impl<'a> ConnectedAccounts<'a> {
    pub(crate) fn new(client: &'a mut OpenMates) -> Self {
        Self { client }
    }
    /// Personal accounts only; `team_id` is refused like the maintained SDKs do.
    pub async fn import_account(
        &mut self,
        payload: &str,
        passcode: &str,
        team_id: Option<&str>,
    ) -> Result<Value> {
        if team_id.is_some_and(|t| !t.is_empty()) {
            return Err(Error::Invalid(
                "Team connected accounts are not supported yet.",
            ));
        }
        self.client.verify_private_operation()?;
        let transfer = decrypt_connected_account_transfer(payload, passcode)?;
        let account = self.client.account_info().await?;
        let user_id = account["id"]
            .as_str()
            .filter(|v| !v.is_empty())
            .ok_or(Error::Invalid(
                "Could not resolve current user id for connected account import.",
            ))?
            .to_owned();
        let master = self.client.master_key().await?;
        let row = import_row(&transfer, &user_id, &master)?;
        assert_no_secret(&row)?;
        self.client
            .task_request(
                Method::POST,
                "/v1/sdk/connected-accounts/import",
                Some(json!({ "row": row })),
                false,
                None,
            )
            .await
    }
}
