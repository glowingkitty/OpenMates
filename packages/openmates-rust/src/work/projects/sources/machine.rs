//! Creating a new Project folder on one of the user's machines (shared core;
//! plan native-agentic-coding-readiness R10). Requester side: propose a
//! placeholder source bound to a connected machine, ask that machine to create
//! the folder through the sealed relay, list the machines that can be chosen.
//! Host side: discover the placeholders addressed to this device and finish a
//! placeholder after its folder exists (`complete-creation`).
//! spec: specifications/features/projects (remote sources).
use super::super::remote_ops::{WireCall, WriteProposal};
use super::*;
use std::collections::BTreeMap;
use std::time::Duration;

const CREATE_TIMEOUT: Duration = Duration::from_secs(45);
const MAX_NAME_BYTES: usize = 200;

/// A placeholder source addressed to this device, as listed by the backend
/// (`GET /v1/projects/source-creations/pending`). The Project identity is a
/// hash; the host maps it to the Projects it can serve.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct PendingSourceCreation {
    /// Backend-generated source id of the placeholder.
    pub source_id: String,
    /// SHA-256 hex of the Project id.
    pub hashed_project_id: String,
    /// Stable hash of the machine the placeholder is bound to.
    pub host_device_hash: String,
}

/// What a machine reports after creating the folder (`create_source` result).
#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct CreatedMachineSource {
    /// Absolute path of the new folder on the machine.
    pub path: String,
    /// The folder name derived from the Project name.
    pub folder_name: String,
    /// The first commit of the new repository.
    pub head: String,
    /// The branch HEAD is on.
    pub branch: String,
}

/// One machine a Project already has a connected source on, offered as the
/// target of a new folder.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MachineHost {
    /// Stable device hash to pass to `propose_machine_source`.
    pub host_device_hash: String,
    /// Names of the connected sources the machine hosts (the only label the
    /// client has for a machine), sorted.
    pub source_names: Vec<String>,
}

/// The values that turn a placeholder into a normal source once its folder
/// exists. Encrypted under the Project key before sending.
#[derive(Clone, Debug)]
pub struct ProjectSourceCompletion {
    /// Type of the new source (a Git repository for a created folder).
    pub source_type: ProjectSourceType,
    /// Folder name shown for the source.
    pub display_name: String,
    /// Metadata, including `root` and `binding_root`.
    pub metadata: serde_json::Map<String, Value>,
    /// The machine's normal capabilities (never `create_source`).
    pub capabilities: Vec<ProjectSourceCapability>,
    /// Unix seconds.
    pub updated_at: u64,
}

fn canonical_device_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}

fn valid_operation_id(id: &str) -> bool {
    (1..=128).contains(&id.len())
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'-'))
}

fn valid_name(name: &str) -> bool {
    !name.trim().is_empty() && name.len() <= MAX_NAME_BYTES && !name.chars().any(char::is_control)
}

/// Group the connected personal sources of one Project by their machine.
pub(super) fn group_machine_hosts(rows: &[Value], key: &[u8; 32]) -> Result<Vec<MachineHost>> {
    let mut hosts: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for row in rows {
        let Some(device) = row["host_device_hash"]
            .as_str()
            .filter(|hash| canonical_device_hash(hash))
        else {
            continue;
        };
        if row["status"] != "connected" {
            continue;
        }
        let name = crypto::decrypt_combined(string(row, "encrypted_display_name")?, key)?;
        hosts.entry(device.to_owned()).or_default().push(name);
    }
    Ok(hosts
        .into_iter()
        .map(|(host_device_hash, mut source_names)| {
            source_names.sort();
            MachineHost {
                host_device_hash,
                source_names,
            }
        })
        .collect())
}

impl Projects<'_> {
    /// Host: placeholders addressed to the calling device. Rows carry hashed
    /// Project ids only.
    ///
    /// # Errors
    /// Session, transport and protocol errors.
    pub async fn pending_source_creations(&mut self) -> Result<Vec<PendingSourceCreation>> {
        self.source_cookie_only()?;
        self.scope()?;
        let route = self.path("/v1/projects/source-creations/pending", &[]);
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        response["sources"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|row| serde_json::from_value(row.clone()).map_err(|_| Error::Protocol))
            .collect()
    }

    /// Host: turn a placeholder into a normal offline source after its folder
    /// exists (`POST .../complete-creation`, accepted only from the bound
    /// device). Name and metadata are encrypted like a normal attach.
    ///
    /// # Errors
    /// Backend refusals (`SOURCE_NOT_CREATION_PENDING`, device mismatch) and
    /// transport errors; `Forbidden` when the answer is not the completed source.
    pub async fn complete_machine_source(
        &mut self,
        selector: &str,
        source: &str,
        input: ProjectSourceCompletion,
    ) -> Result<ProjectSource> {
        self.source_cookie_only()?;
        let segment = source_patch_segment(source)?;
        let owner = self.source_cookie_owner().await?;
        self.scope()?;
        source_capabilities(&input.capabilities, true)?;
        if input
            .capabilities
            .contains(&ProjectSourceCapability::CreateSource)
        {
            return Err(Error::Invalid(
                "A completed source never keeps the create_source capability.",
            ));
        }
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let name = crypto::server_fields::encrypt_text(&input.display_name, &project.key, &[])?;
        let metadata = crypto::server_fields::encrypt_text(
            &serde_json::to_string(&input.metadata)?,
            &project.key,
            &[],
        )?;
        if name.len() > 128_000 || metadata.len() > 128_000 {
            return Err(Error::Invalid(
                "Project source ciphertext exceeds the server bound.",
            ));
        }
        let route = self.path(
            &format!("/v1/projects/{project_id}/sources/{segment}/complete-creation"),
            &[],
        );
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let body = json!({"source_type":input.source_type,"encrypted_display_name":name,
            "encrypted_metadata":metadata,"capabilities":input.capabilities,
            "updated_at":input.updated_at});
        let response = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        let raw = source_ack(&response)?;
        if raw["source_id"] != source || raw["status"] == "creation_pending" {
            return Err(Error::Forbidden);
        }
        source_decode(
            raw,
            &project_id,
            &owner,
            self.filters.team_id.as_deref(),
            &project.key,
        )
    }

    /// Distinct connected machines of a Project, each with the names of the
    /// sources it hosts, so a client can offer a target machine.
    ///
    /// # Errors
    /// Project resolution, transport and decryption errors.
    pub async fn machine_hosts(
        &mut self,
        selector: &str,
    ) -> std::result::Result<Vec<MachineHost>, RemoteOpError> {
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let rows = self.list_sources_raw(&project_id).await?;
        Ok(group_machine_hosts(&rows, &project.key)?)
    }

    /// Create the placeholder source for a new folder on the machine
    /// `host_device_hash` (it must be connected). The machine binds the
    /// placeholder; then [`Projects::create_machine_source`] asks it to create
    /// the folder.
    ///
    /// # Errors
    /// `Invalid` for a malformed hash or name; the backend refuses an
    /// unconnected machine (403 `HOST_DEVICE_NOT_CONNECTED`) and a Project
    /// without a write mode (409 `PROJECT_WRITE_MODE_REQUIRED`).
    pub async fn propose_machine_source(
        &mut self,
        selector: &str,
        host_device_hash: &str,
        display_name: &str,
    ) -> std::result::Result<ProjectSource, RemoteOpError> {
        if !canonical_device_hash(host_device_hash) {
            return Err(Error::Invalid("machine_host_hash_invalid").into());
        }
        if !valid_name(display_name) {
            return Err(Error::Invalid("machine_source_name_invalid").into());
        }
        let owner = self.source_cookie_owner().await?;
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let name = crypto::server_fields::encrypt_text(display_name, &project.key, &[])?;
        let metadata = crypto::server_fields::encrypt_text("{}", &project.key, &[])?;
        let now = crate::client::now_ms() / 1000;
        let route = self.path(&format!("/v1/projects/{project_id}/sources"), &[]);
        let payload = json!({"create_on_host_device":host_device_hash,"source_type":"local_folder",
            "encrypted_display_name":name,"encrypted_metadata":metadata,
            "created_at":now,"updated_at":now});
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled.into());
        }
        let response = self
            .backend
            .request(Method::POST, &route, Some(payload), None)
            .await?;
        let raw = source_ack(&response)?;
        if raw["status"] != "creation_pending" || raw["host_device_hash"] != host_device_hash {
            return Err(Error::Forbidden.into());
        }
        Ok(source_decode(
            raw,
            &project_id,
            &owner,
            self.filters.team_id.as_deref(),
            &project.key,
        )?)
    }

    /// Ask the machine bound to the placeholder `source_id` to create the new
    /// Project folder for `project_name` (write-class: the approval is stored
    /// first under the keyed digest, like `git_commit`).
    ///
    /// # Errors
    /// [`RemoteOpError::Host`] with `creation_not_configured`,
    /// `invalid_project_name`, `creation_folder_unavailable`, `identity_missing`,
    /// `target_exists` (the machine changed nothing), `creation_completion_failed`
    /// (the folder exists; the machine retries completion) or an approval code;
    /// `source_offline` while the machine has not bound the placeholder.
    pub async fn create_machine_source(
        &mut self,
        selector: &str,
        source_id: &str,
        chat_id: &str,
        operation_id: &str,
        project_name: &str,
    ) -> std::result::Result<CreatedMachineSource, RemoteOpError> {
        if !valid_operation_id(operation_id) {
            return Err(Error::Invalid("remote_operation_id_invalid").into());
        }
        if !valid_name(project_name) {
            return Err(Error::Invalid("machine_source_name_invalid").into());
        }
        let proposal = WriteProposal::CreateSource {
            operation_id: operation_id.to_owned(),
            project_name: project_name.to_owned(),
        };
        let call = WireCall {
            name: "create_source",
            arguments: proposal.arguments(chat_id),
            capability: Some("create_source"),
            chat: Some(chat_id.to_owned()),
            write: Some((chat_id.to_owned(), proposal)),
        };
        let (_, _, result) = self
            .source_call(selector, Some(source_id), call, CREATE_TIMEOUT)
            .await?;
        serde_json::from_value(result).map_err(|_| RemoteOpError::Core(Error::Protocol))
    }
}
