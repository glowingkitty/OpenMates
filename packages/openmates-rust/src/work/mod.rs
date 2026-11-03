//! Shared encrypted workspace services for cookie and API-key authentication.
use crate::{
    Client, Error, OpenMates, Result,
    crypto::{self, Key},
};
use reqwest::Method;
use serde_json::{Value, json};
mod workflows;
pub use workflows::*;
mod projects;
pub use projects::*;
mod plans;
pub use plans::*;
mod task_crypto;
mod teams;
pub use teams::*;
mod tasks;
pub use tasks::*;
mod team_move;
pub use team_move::*;
#[derive(Default, Clone)]
pub(crate) struct TaskHeaders {
    pub assignee: bool,
    pub creator: bool,
    pub owner: Option<String>,
    pub idempotency: Option<String>,
}
impl TaskHeaders {
    pub(crate) fn headers(&self) -> Result<Vec<(&'static str, String)>> {
        let mut values = vec![];
        if self.assignee {
            values.push(("X-OpenMates-Task-Actor", "assignee".into()));
        }
        if self.creator {
            values.push(("X-OpenMates-Task-Creator", "codex".into()));
        }
        if let Some(owner) = &self.owner {
            if owner.len() != 64 || !owner.bytes().all(|b| b.is_ascii_hexdigit()) {
                return Err(Error::Forbidden);
            }
            values.push(("X-OpenMates-Task-Owner", owner.clone()));
        }
        if let Some(key) = &self.idempotency {
            if key.trim().is_empty() || key.len() > 255 || key.bytes().any(|b| b < 32 || b == 127) {
                return Err(Error::Invalid("Invalid idempotency key."));
            }
            values.push(("Idempotency-Key", key.clone()));
        }
        Ok(values)
    }
}
pub(crate) enum Backend<'a> {
    Cookie(&'a mut Client),
    ApiKey(&'a mut OpenMates),
}
impl Backend<'_> {
    fn verify_private_operation(&self) -> Result<()> {
        match self {
            Self::Cookie(client) => client.verify_private_operation(),
            Self::ApiKey(client) => client.verify_private_operation(),
        }
    }
    async fn request(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
        headers: Option<&TaskHeaders>,
    ) -> Result<Value> {
        match self {
            Self::Cookie(client) => {
                client.require_session()?;
                client
                    .request_task_headers(method, path, body, None, None, headers)
                    .await
            }
            Self::ApiKey(client) => {
                client
                    .task_request(method, path, body, false, headers)
                    .await
            }
        }
    }
    async fn public_workflow_projection(&mut self, template: &str) -> Result<Value> {
        match self {
            Self::Cookie(client) => client.public_workflow_projection(template).await,
            Self::ApiKey(client) => {
                client
                    .task_request(
                        Method::GET,
                        &format!(
                            "/v1/workflows/template-projections/{}",
                            url::form_urlencoded::byte_serialize(template.as_bytes())
                                .collect::<String>()
                        ),
                        None,
                        true,
                        None,
                    )
                    .await
            }
        }
    }
    async fn request_idempotent(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
        key: &str,
    ) -> Result<Value> {
        let headers = TaskHeaders {
            idempotency: Some(key.into()),
            ..Default::default()
        };
        self.request(method, path, body, Some(&headers)).await
    }
    async fn master(&mut self) -> Result<Key> {
        match self {
            Self::Cookie(client) => client.work_master_key(),
            Self::ApiKey(client) => client.master_key().await,
        }
    }
    fn app_origin(&self) -> String {
        match self {
            Self::Cookie(client) => client.app_url(),
            Self::ApiKey(client) => client.work_app_origin(),
        }
    }
    fn origin(&self) -> String {
        match self {
            Self::Cookie(client) => client.work_origin(),
            Self::ApiKey(client) => client.work_origin(),
        }
    }
    async fn wrapping(&mut self, team: Option<&str>) -> Result<Key> {
        let master = self.master().await?;
        let Some(team) = team else { return Ok(master) };
        uuid::Uuid::parse_str(team).map_err(|_| Error::Invalid("Invalid Team ID."))?;
        let value = self
            .request(Method::GET, &format!("/v1/teams/{team}"), None, None)
            .await?;
        let row = &value["team"];
        if string(row, "team_id")? != team {
            return Err(Error::Forbidden);
        }
        key_bytes(&crypto::decrypt_bytes(
            string(row, "encrypted_team_key")?,
            &master,
        )?)
    }
}
pub(crate) fn string<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or(Error::Protocol)
}
pub(crate) fn key_bytes(value: &[u8]) -> Result<Key> {
    let bytes: [u8; 32] = value.try_into().map_err(|_| Error::Crypto)?;
    Ok(zeroize::Zeroizing::new(bytes))
}
pub(crate) fn hash(value: &str) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
pub(crate) fn now() -> u64 {
    crate::client::now_ms() / 1000
}
pub(crate) fn path(path: &str, team: Option<&str>, params: &[(String, String)]) -> String {
    let mut query = url::form_urlencoded::Serializer::new(String::new());
    if let Some(team) = team {
        query.append_pair("team_id", team);
    }
    for (key, value) in params {
        query.append_pair(key, value);
    }
    let query = query.finish();
    format!(
        "{path}{}",
        if query.is_empty() {
            String::new()
        } else {
            format!("?{query}")
        }
    )
}
pub(crate) fn uuid(value: &str) -> Result<&str> {
    uuid::Uuid::parse_str(value)
        .map_err(|_| Error::Invalid("A full canonical object ID is required."))?;
    Ok(value)
}

// The caller authenticates the object wrapper and scope before supplying its key.
pub(crate) fn decode_task_with_key(raw: Value, key: Key) -> Result<Value> {
    let task = task_crypto::decode_with_key(raw, key)?;
    let mut public = task.public.clone();
    if let Some(activity) = task
        .raw
        .get("latest_activity")
        .filter(|value| value.is_object())
    {
        public["latest_activity"] = task_crypto::activity(&task, activity)?;
    }
    if let Some(dependencies) = task.raw.get("dependencies") {
        public["dependencies"] = dependencies.clone();
    }
    Ok(public)
}
/// A server receipt alone cannot prove randomized private ciphertext persisted.
#[allow(clippy::too_many_arguments)]
pub(crate) fn verify_task_job_persistence(
    raw: Value,
    wrapping: &[u8; 32],
    team: Option<&str>,
    key: &[u8; 32],
    expected: &Value,
    version: u64,
    owner: &str,
) -> Result<()> {
    if match team {
        Some(team) => raw["hashed_team_id"] != hash(team),
        None => raw["hashed_user_id"] != hash(owner),
    } {
        return Err(Error::Forbidden);
    }
    let task = task_crypto::decrypt(raw, wrapping, wrapping, team)?;
    if task.key.as_ref() != key || task.raw["version"].as_u64() != Some(version) {
        return Err(Error::Conflict);
    }
    for (field, value) in expected.as_object().ok_or(Error::Protocol)? {
        if field == "version" {
            continue;
        }
        if field == "key_wrappers" {
            let expected = value.as_array().ok_or(Error::Protocol)?;
            let actual = task.raw[field].as_array().ok_or(Error::Protocol)?;
            if actual.len() != expected.len() {
                return Err(Error::Conflict);
            }
            for wrapper in expected {
                let candidates = actual
                    .iter()
                    .filter(|row| {
                        [
                            "key_type",
                            "hashed_chat_id",
                            "hashed_project_id",
                            "hashed_plan_id",
                            "hashed_team_id",
                            "team_key_epoch",
                        ]
                        .iter()
                        .all(|key| row[*key] == wrapper[*key])
                    })
                    .collect::<Vec<_>>();
                if candidates.len() != 1
                    || wrapper
                        .as_object()
                        .ok_or(Error::Protocol)?
                        .iter()
                        .any(|(field, value)| candidates[0][field] != *value)
                {
                    return Err(Error::Conflict);
                }
            }
        } else if field == "linked_project_ids" {
            if task.public[field] != *value {
                return Err(Error::Conflict);
            }
            let expected = value
                .as_array()
                .ok_or(Error::Protocol)?
                .iter()
                .map(|id| id.as_str().map(hash).ok_or(Error::Protocol))
                .collect::<Result<std::collections::BTreeSet<_>>>()?;
            let actual = task.raw["linked_project_hashes"]
                .as_array()
                .ok_or(Error::Protocol)?
                .iter()
                .map(|id| id.as_str().map(str::to_owned).ok_or(Error::Protocol))
                .collect::<Result<std::collections::BTreeSet<_>>>()?;
            if actual != expected {
                return Err(Error::Conflict);
            }
        } else if task.raw[field] != *value {
            return Err(Error::Conflict);
        }
    }
    Ok(())
}
