//! API-key Account Import V1 (npm `client.accountImports`). The flow, batching
//! and client-side encryption are the shared `account::imports` implementation;
//! only the credential transport differs: requests are signed with the API key
//! and imported chats are wrapped with the API-key-wrapped account key.
use crate::account::imports::{AccountImportPlan, ImportBackend, ImportFlow};
use crate::account::imports_parse::ParsedAccountImport;
use crate::{OpenMates, Result, crypto};
use reqwest::Method;
use serde_json::Value;

struct KeyBackend<'a>(&'a mut OpenMates);
impl ImportBackend for KeyBackend<'_> {
    async fn request(
        &mut self,
        method: Method,
        route: &str,
        body: Option<Value>,
    ) -> Result<Value> {
        self.0.request_json(method, route, body).await
    }
    async fn master_key(&mut self) -> Result<crypto::Key> {
        self.0.master_key().await
    }
}

impl OpenMates {
    /// Previews a parsed export against the server duplicate check.
    pub async fn preview_account_import(
        &mut self,
        parsed: &ParsedAccountImport,
        select_all: bool,
    ) -> Result<AccountImportPlan> {
        ImportFlow {
            backend: KeyBackend(self),
        }
        .preview_account_import(parsed, select_all)
        .await
    }
    /// Runs a confirmed import; the caller owns the confirmation prompt.
    pub async fn run_account_import(
        &mut self,
        parsed: &ParsedAccountImport,
        plan: &AccountImportPlan,
    ) -> Result<Value> {
        ImportFlow {
            backend: KeyBackend(self),
        }
        .run_account_import(parsed, plan)
        .await
    }
}
