//! Native Project commits: named snapshots over hosted-file revision history.
//!
//! A commit stores pointers only (hashed Project item id plus embed version).
//! The message and the per-file paths are encrypted here with the Project key,
//! so the backend never sees them. Commits are append-only; restoring one is a
//! plan of new revisions plus a new commit recorded with `restored_from`.
use super::items::optional_text;
use super::*;
use std::collections::BTreeMap;

const MESSAGE_MAX_BYTES: usize = 16_000;
const MAX_FILES: usize = 500;
const HOSTED_SOURCE: &str = "hosted_project_file";

/// Who made the change a commit records.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectCommitAuthor {
    User,
    Assistant,
}

/// One hosted file at an exact revision (plain input for a new commit).
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProjectCommitFile {
    pub target_id: String,
    pub path: String,
    pub embed_version: u64,
}

/// New commit. An empty `files` list snapshots every hosted file at its current head.
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectCommitCreate {
    pub message: String,
    pub author: ProjectCommitAuthor,
    pub chat_id: Option<String>,
    #[serde(default)]
    pub files: Vec<ProjectCommitFile>,
    pub commit_id: Option<String>,
    pub created_at: Option<u64>,
}

/// One decoded snapshot entry; `path` is absent if the commit carried no path map.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize)]
pub struct ProjectCommitEntry {
    pub target_id_hash: String,
    pub path: Option<String>,
    pub embed_version: u64,
}

/// Decoded commit. No Debug on the message to avoid accidental logging.
#[derive(Clone, Serialize, Deserialize)]
pub struct ProjectCommit {
    pub commit_id: String,
    pub message: String,
    pub author: ProjectCommitAuthor,
    pub chat_id_hash: Option<String>,
    pub files: Vec<ProjectCommitEntry>,
    pub restored_from_commit_id: Option<String>,
    pub created_at: u64,
}

/// One page of commits, newest first.
#[derive(Clone, Serialize, Deserialize)]
pub struct ProjectCommitPage {
    pub commits: Vec<ProjectCommit>,
    pub next_cursor: Option<u64>,
}

/// What restoring a commit would change, per file.
#[derive(Clone, Serialize, Deserialize)]
pub struct ProjectCommitRestoreFile {
    /// Absent when the file was unlinked from the Project after the commit.
    pub target_id: Option<String>,
    pub target_id_hash: String,
    pub path: Option<String>,
    pub restore_version: u64,
    pub current_version: Option<u64>,
    /// True when the head already is the committed revision.
    pub unchanged: bool,
}

/// Restore plan: the client writes each changed file as a new revision, then records it.
#[derive(Clone, Serialize, Deserialize)]
pub struct ProjectCommitRestorePlan {
    pub commit_id: String,
    pub files: Vec<ProjectCommitRestoreFile>,
}

fn validate_input(input: &ProjectCommitCreate) -> Result<()> {
    if input.message.trim().is_empty() || input.message.len() > MESSAGE_MAX_BYTES {
        return Err(Error::Invalid(
            "A commit message of 1 to 16000 bytes is required.",
        ));
    }
    if input.files.len() > MAX_FILES {
        return Err(Error::Invalid("A commit can list at most 500 files."));
    }
    if let Some(id) = &input.commit_id {
        uuid(id)?;
    }
    for (index, file) in input.files.iter().enumerate() {
        if file.target_id.is_empty()
            || file.path.is_empty()
            || file.embed_version == 0
            || input.files[..index]
                .iter()
                .any(|earlier| earlier.target_id == file.target_id)
        {
            return Err(Error::Invalid(
                "Commit files need a unique target, a path and a positive version.",
            ));
        }
    }
    Ok(())
}

/// Encrypt a commit for transport; `files` must already be resolved.
fn commit_wire(
    input: &ProjectCommitCreate,
    key: &[u8; 32],
    commit_id: &str,
    now: u64,
) -> Result<Value> {
    validate_input(input)?;
    if input.files.is_empty() {
        return Err(Error::Invalid("A commit needs at least one file."));
    }
    let paths: BTreeMap<String, &str> = input
        .files
        .iter()
        .map(|file| (hash(&file.target_id), file.path.as_str()))
        .collect();
    let message = crypto::server_fields::encrypt_text(&input.message, key, &[])?;
    let encrypted_paths =
        crypto::server_fields::encrypt_text(&serde_json::to_string(&paths)?, key, &[])?;
    let entries: Vec<Value> = input
        .files
        .iter()
        .map(|file| json!({"target_id_hash":hash(&file.target_id),"embed_version":file.embed_version}))
        .collect();
    let mut body = json!({
        "commit_id": commit_id, "author_kind": input.author,
        "encrypted_message": message, "encrypted_paths": encrypted_paths,
        "entries": entries, "created_at": input.created_at.unwrap_or(now),
    });
    if let Some(chat) = &input.chat_id {
        body["chat_id"] = json!(chat);
    }
    Ok(body)
}

fn commit_decode(raw: &Value, key: &[u8; 32]) -> Result<ProjectCommit> {
    let message = crypto::decrypt_combined(string(raw, "encrypted_message")?, key)?;
    let paths: BTreeMap<String, String> = match raw.get("encrypted_paths") {
        None | Some(Value::Null) => BTreeMap::new(),
        Some(Value::String(text)) => serde_json::from_str(&crypto::decrypt_combined(text, key)?)
            .map_err(|_| Error::Crypto)?,
        _ => return Err(Error::Protocol),
    };
    let mut files = Vec::new();
    for entry in raw["entries"].as_array().ok_or(Error::Protocol)? {
        let target = string(entry, "target_id_hash")?;
        files.push(ProjectCommitEntry {
            target_id_hash: target.into(),
            path: paths.get(target).cloned(),
            embed_version: entry["embed_version"]
                .as_u64()
                .filter(|v| *v > 0)
                .ok_or(Error::Protocol)?,
        });
    }
    if files.is_empty() || files.len() > MAX_FILES {
        return Err(Error::Protocol);
    }
    Ok(ProjectCommit {
        commit_id: string(raw, "commit_id")?.into(),
        message,
        author: serde_json::from_value(raw["author_kind"].clone()).map_err(|_| Error::Protocol)?,
        chat_id_hash: raw["hashed_chat_id"].as_str().map(str::to_owned),
        files,
        restored_from_commit_id: raw["restored_from_commit_id"].as_str().map(str::to_owned),
        created_at: raw["created_at"].as_u64().ok_or(Error::Protocol)?,
    })
}

/// Hosted-file link rows decoded to (target id, path), in Project order.
fn hosted_files(items: &Value, key: &[u8; 32]) -> Result<Vec<(String, String)>> {
    let mut found = Vec::new();
    for row in items.as_array().ok_or(Error::Protocol)? {
        if !matches!(row["item_type"].as_str(), Some("embed" | "upload")) {
            continue;
        }
        let metadata = optional_text(row, "encrypted_metadata", key)?;
        let Ok(metadata) = serde_json::from_str::<Value>(&metadata) else {
            continue;
        };
        if metadata["source"] != HOSTED_SOURCE {
            continue;
        }
        let (Some(path), target) = (
            metadata["path"].as_str(),
            optional_text(row, "target_id_encrypted", key)?,
        ) else {
            continue;
        };
        if target.is_empty()
            || row["target_id_hash"]
                .as_str()
                .is_some_and(|h| h != hash(&target))
        {
            return Err(Error::Forbidden);
        }
        found.push((target, path.to_owned()));
    }
    Ok(found)
}

impl Projects<'_> {
    fn commit_cookie_only(&self) -> Result<()> {
        if matches!(&self.backend, Backend::ApiKey(_)) {
            return Err(Error::Unavailable {
                code: "project_commits_unavailable",
                reason: "PROJECT_COMMITS_REQUIRE_COOKIE_SESSION",
            });
        }
        Ok(())
    }

    /// Hosted-file links of the Project as (target id, metadata path).
    pub(super) async fn project_hosted_files(
        &mut self,
        project_id: &str,
        key: &[u8; 32],
    ) -> Result<Vec<(String, String)>> {
        let route = self.path(&format!("/v1/projects/{project_id}"), &[]);
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        hosted_files(&response["items"], key)
    }

    /// Current head revision of one linked embed.
    pub(super) async fn head_version(&mut self, project_id: &str, target_id: &str) -> Result<u64> {
        uuid(target_id)?;
        let route = self.path(
            &format!("/v1/embeds/{target_id}/versions"),
            &[
                ("project_id".into(), project_id.into()),
                ("limit".into(), "1".into()),
                ("order".into(), "desc".into()),
            ],
        );
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        response["current_version"]
            .as_u64()
            .filter(|v| *v > 0)
            .ok_or(Error::Protocol)
    }

    /// Record a commit. With no files given, snapshots every hosted file's current head.
    pub async fn create_commit(
        &mut self,
        selector: &str,
        mut input: ProjectCommitCreate,
    ) -> Result<ProjectCommit> {
        self.commit_cookie_only()?;
        validate_input(&input)?;
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        if input.files.is_empty() {
            for (target_id, path) in self.project_hosted_files(&project_id, &project.key).await? {
                let embed_version = self.head_version(&project_id, &target_id).await?;
                input.files.push(ProjectCommitFile {
                    target_id,
                    path,
                    embed_version,
                });
            }
            if input.files.is_empty() {
                return Err(Error::Invalid("The Project has no hosted files to commit."));
            }
        }
        let commit_id = input
            .commit_id
            .clone()
            .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
        let wire = commit_wire(&input, &project.key, &commit_id, now())?;
        let route = self.path(&format!("/v1/projects/{project_id}/commits"), &[]);
        let response = self
            .backend
            .request(Method::POST, &route, Some(wire.clone()), None)
            .await?;
        acknowledged(&response, &wire, &project.key)
    }

    /// One page of commits, newest first.
    pub async fn list_commits(
        &mut self,
        selector: &str,
        limit: u32,
        cursor: u64,
    ) -> Result<ProjectCommitPage> {
        self.commit_cookie_only()?;
        if !(1..=100).contains(&limit) {
            return Err(Error::Invalid(
                "Commit page size must be between 1 and 100.",
            ));
        }
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let route = self.path(
            &format!("/v1/projects/{project_id}/commits"),
            &[
                ("limit".into(), limit.to_string()),
                ("cursor".into(), cursor.to_string()),
            ],
        );
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let commits = response["commits"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|raw| commit_decode(raw, &project.key))
            .collect::<Result<Vec<_>>>()?;
        let next_cursor = match &response["next_cursor"] {
            Value::Null => None,
            value => Some(value.as_u64().ok_or(Error::Protocol)?),
        };
        Ok(ProjectCommitPage {
            commits,
            next_cursor,
        })
    }

    /// One commit with its decrypted message and file paths.
    pub async fn show_commit(&mut self, selector: &str, commit_id: &str) -> Result<ProjectCommit> {
        self.commit_cookie_only()?;
        uuid(commit_id)?;
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let route = self.path(
            &format!("/v1/projects/{project_id}/commits/{commit_id}"),
            &[],
        );
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let commit = commit_decode(&response["commit"], &project.key)?;
        if commit.commit_id != commit_id {
            return Err(Error::Forbidden);
        }
        Ok(commit)
    }

    /// Compare a commit with the current heads. Creates nothing.
    pub async fn restore_commit_plan(
        &mut self,
        selector: &str,
        commit_id: &str,
    ) -> Result<ProjectCommitRestorePlan> {
        let commit = self.show_commit(selector, commit_id).await?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let linked: BTreeMap<String, String> = self
            .project_hosted_files(&project_id, &project.key)
            .await?
            .into_iter()
            .map(|(target, _)| (hash(&target), target))
            .collect();
        let mut files = Vec::with_capacity(commit.files.len());
        for entry in commit.files {
            let target_id = linked.get(&entry.target_id_hash).cloned();
            let current_version = match &target_id {
                Some(target) => Some(self.head_version(&project_id, target).await?),
                None => None,
            };
            files.push(ProjectCommitRestoreFile {
                unchanged: current_version == Some(entry.embed_version),
                target_id,
                target_id_hash: entry.target_id_hash,
                path: entry.path,
                restore_version: entry.embed_version,
                current_version,
            });
        }
        Ok(ProjectCommitRestorePlan {
            commit_id: commit.commit_id,
            files,
        })
    }

    /// Record a finished whole-commit restore as a new commit. The new revisions
    /// must already be written; the server refuses entries older than the source.
    pub async fn record_commit_restore(
        &mut self,
        selector: &str,
        source_commit_id: &str,
        input: ProjectCommitCreate,
    ) -> Result<ProjectCommit> {
        self.commit_cookie_only()?;
        uuid(source_commit_id)?;
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let commit_id = input
            .commit_id
            .clone()
            .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
        let wire = commit_wire(&input, &project.key, &commit_id, now())?;
        let route = self.path(
            &format!("/v1/projects/{project_id}/commits/{source_commit_id}/restore"),
            &[],
        );
        let response = self
            .backend
            .request(Method::POST, &route, Some(wire.clone()), None)
            .await?;
        let commit = acknowledged(&response, &wire, &project.key)?;
        if commit.restored_from_commit_id.as_deref() != Some(source_commit_id) {
            return Err(Error::Forbidden);
        }
        Ok(commit)
    }
}

/// The acknowledgement must echo the exact ciphertext and pointers we sent.
fn acknowledged(response: &Value, wire: &Value, key: &[u8; 32]) -> Result<ProjectCommit> {
    let raw = response
        .get("commit")
        .filter(|c| c.is_object())
        .ok_or(Error::Protocol)?;
    for field in [
        "commit_id",
        "author_kind",
        "encrypted_message",
        "encrypted_paths",
        "entries",
        "created_at",
    ] {
        if raw[field] != wire[field] {
            return Err(Error::Forbidden);
        }
    }
    commit_decode(raw, key)
}

#[cfg(test)]
mod tests;
