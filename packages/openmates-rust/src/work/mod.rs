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
mod checks;
pub use checks::*;
mod specifications;
/// Specification document hash under an unambiguous name (`projects` also exports a `content_hash`).
pub use specifications::content_hash as specification_content_hash;
pub use specifications::*;
mod task_crypto;
mod teams;
pub use teams::*;
mod tasks;
pub use tasks::*;
mod team_move;
pub use team_move::*;
pub mod recovery;
#[cfg(test)]
mod team_rotation_tests;
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
                // Native session or the web Worker's admitted browser credentials.
                client.require_work_authority()?;
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
    /// Unwraps a key wrapped under the master key (Project and Team key
    /// wrappers). The cookie client goes through its master binding, so the
    /// web Worker's non-extractable master works; API-key clients decrypt with
    /// their own wrapped master key as before.
    async fn unwrap_with_master(&mut self, ciphertext: &str) -> Result<Key> {
        match self {
            Self::Cookie(client) => client.work_unwrap_with_master(ciphertext).await,
            Self::ApiKey(client) => {
                let master = client.master_key().await?;
                key_bytes(&crypto::decrypt_bytes(ciphertext, &master)?)
            }
        }
    }
    /// Wraps a fresh object key under the master key (server wrapper format).
    /// The cookie client goes through its master binding, so the web Worker's
    /// non-extractable master works; API-key clients use their own master.
    async fn wrap_with_master(&mut self, plaintext: &[u8]) -> Result<String> {
        match self {
            Self::Cookie(client) => client.work_wrap_with_master(plaintext).await,
            Self::ApiKey(client) => {
                let master = client.master_key().await?;
                crypto::server_fields::encrypt_bytes(plaintext, &master, &[])
            }
        }
    }
    /// Master key bytes for the slug lookup index; `None` for the web Worker,
    /// whose master cannot be exported.
    async fn slug_lookup_master(&mut self) -> Result<Option<Key>> {
        match self {
            Self::Cookie(client) => client.work_slug_lookup_master(),
            Self::ApiKey(client) => client.master_key().await.map(Some),
        }
    }
    async fn wrapping(&mut self, team: Option<&str>) -> Result<Key> {
        let Some(team) = team else {
            return self.master().await;
        };
        let row = self.team_row(team).await?;
        self.unwrap_with_master(string(&row, "encrypted_team_key")?)
            .await
    }
    /// The Team row; a sealed rotated key is claimed (re-wrapped with the
    /// master key) by cookie clients and refused for API-key clients, so a
    /// sealed wrapper is never handed to a master-key unwrap.
    async fn team_row(&mut self, team: &str) -> Result<Value> {
        uuid::Uuid::parse_str(team).map_err(|_| Error::Invalid("Invalid Team ID."))?;
        let row = match self {
            Self::Cookie(client) if client.require_session().is_ok() => client.teams().get(team).await?,
            Self::Cookie(client) => {
                let mut row = client.team_key_row(team).await?;
                if let Some(claimed) = client.claim_sealed_team_key(team, &row).await? {
                    row["encrypted_team_key"] = json!(claimed);
                }
                row
            }
            Self::ApiKey(_) => {
                let value = self
                    .request(Method::GET, &format!("/v1/teams/{team}"), None, None)
                    .await?;
                value["team"].clone()
            }
        };
        if string(&row, "team_id")? != team {
            return Err(Error::Forbidden);
        }
        if row["encrypted_team_key"]
            .as_str()
            .is_some_and(|w| w.starts_with("OMTK1."))
        {
            return Err(Error::Invalid(
                "This Team key was rotated; open the Team once in a signed-in client to claim it.",
            ));
        }
        Ok(row)
    }
    /// Current key epoch of the Team (1 before any rotation); new Team key
    /// wrappers are stamped with it.
    async fn team_epoch(&mut self, team: &str) -> Result<u64> {
        let row = self.team_row(team).await?;
        Ok(row["team_key_epoch"]
            .as_u64()
            .filter(|e| *e >= 1)
            .unwrap_or(1))
    }
    /// Earlier Team keys (`epoch`, key) from the previous-key chain; empty
    /// before the first rotation.
    async fn team_previous_keys(&mut self, team: &str) -> Result<Vec<(u64, Key)>> {
        let row = self.team_row(team).await?;
        let Some(chain) = row["encrypted_previous_team_keys"]
            .as_str()
            .filter(|c| !c.is_empty())
        else {
            return Ok(vec![]);
        };
        let current = self
            .unwrap_with_master(string(&row, "encrypted_team_key")?)
            .await?;
        crate::client::previous_team_keys(chain, &current)
    }
}
/// Stamps every Team key wrapper of a create/move payload with the Team's
/// current epoch, so a wrapper written after a rotation never claims epoch 1.
pub(crate) fn stamp_team_epoch(payload: &mut Value, epoch: u64) {
    if let Some(wrappers) = payload["key_wrappers"].as_array_mut() {
        for wrapper in wrappers.iter_mut().filter(|w| w["key_type"] == "team") {
            wrapper["team_key_epoch"] = json!(epoch);
        }
    }
    if payload["team_project_key_wrapper"].is_object() {
        payload["team_project_key_wrapper"]["team_key_epoch"] = json!(epoch);
    }
}
/// Wrapper epochs are any rotation epoch from 1; the key is chosen by
/// [`open_team_wrapper`].
pub(crate) fn team_epoch_ok(row: &Value) -> bool {
    row["team_key_epoch"].as_u64().is_some_and(|e| e >= 1)
}
/// Open a Team-key wrapper: a chain key for its epoch first, then the current
/// key (wrappers written after a rotation carry the current key whatever epoch
/// label they were created with). Authenticated encryption makes a wrong key fail.
pub(crate) fn open_team_wrapper(
    encrypted: &str,
    epoch: u64,
    current: &[u8; 32],
    previous: &[(u64, Key)],
) -> Result<Vec<u8>> {
    if let Some((_, old)) = previous.iter().find(|(e, _)| *e == epoch)
        && let Ok(plain) = crypto::decrypt_bytes(encrypted, old)
    {
        return Ok(plain.to_vec());
    }
    Ok(crypto::decrypt_bytes(encrypted, current)?.to_vec())
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
    let task = task_crypto::decrypt(raw, wrapping, wrapping, team, &[])?;
    verify_task_job_fields(&task, key, expected, version)
}

/// Verify the exact fields against the canonical Task opened by the active authority.
fn verify_task_job_fields(
    task: &task_crypto::Resolved,
    key: &[u8; 32],
    expected: &Value,
    version: u64,
) -> Result<()> {
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
