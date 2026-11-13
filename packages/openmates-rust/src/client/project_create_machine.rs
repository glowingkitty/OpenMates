//! Assistant request to create a Project on one of the user's machines.
//!
//! Such a request creates nothing by itself: the event only records a
//! confirmation card. When the shell's decision arrives (`confirm` or
//! `decline`) the core creates the encrypted Project, activates its default
//! focus, proposes the placeholder source on the chosen machine and asks that
//! machine to create the folder. A machine-side failure deletes the Project
//! again (the placeholder source goes with it), so no orphan remains.
//!
//! The `project_create_result` report is accepted by the server only from the
//! socket of the live turn (the executor must be ready for the chat), so the
//! decision is taken during the turn through
//! `SendOptions::machine_project`, never after it ended.
//! spec: specifications/features/projects (machine Project creation).
use super::*;
use crate::work::{
    CreatedMachineSource, CreatedProjectRecord, MachineHost, ProjectCreateRequest, ProjectFilters,
    RemoteOpError,
};
use serde::{Deserialize, Serialize};

/// The shell's answer to a machine Project confirmation card.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MachineProjectDecision {
    /// Create the Project on a machine. `None` picks the user's only machine.
    Confirm { host_device_hash: Option<String> },
    /// The user does not want the Project.
    Decline,
    /// The shell cannot ask (non-interactive); reported as a failure so the
    /// assistant tells the user nothing was created.
    Unavailable,
}

/// The two machine-side steps; a seam so tests can run them without a relay.
pub(super) trait MachineSteps {
    async fn hosts(&mut self) -> std::result::Result<Vec<MachineHost>, RemoteOpError>;
    async fn create_project(
        &mut self,
        request: &ProjectCreateRequest,
    ) -> Result<CreatedProjectRecord>;
    async fn undo_project(&mut self, record: &CreatedProjectRecord) -> Result<()>;
    async fn propose(
        &mut self,
        project_id: &str,
        host: &str,
        name: &str,
    ) -> std::result::Result<String, RemoteOpError>;
    async fn create(
        &mut self,
        project_id: &str,
        source_id: &str,
        chat: &str,
        operation: &str,
        name: &str,
    ) -> std::result::Result<CreatedMachineSource, RemoteOpError>;
}

struct RelaySteps<'a>(crate::work::Projects<'a>);

impl MachineSteps for RelaySteps<'_> {
    async fn create_project(
        &mut self,
        request: &ProjectCreateRequest,
    ) -> Result<CreatedProjectRecord> {
        self.0.create_for_request(request).await
    }
    async fn undo_project(&mut self, record: &CreatedProjectRecord) -> Result<()> {
        self.0.undo_created(&record.chat_id).await.map(|_| ())
    }
    async fn hosts(&mut self) -> std::result::Result<Vec<MachineHost>, RemoteOpError> {
        self.0.machine_hosts_any().await
    }
    async fn propose(
        &mut self,
        project_id: &str,
        host: &str,
        name: &str,
    ) -> std::result::Result<String, RemoteOpError> {
        let source = self
            .0
            .propose_machine_source(project_id, host, name)
            .await?;
        Ok(source.source_id)
    }
    async fn create(
        &mut self,
        project_id: &str,
        source_id: &str,
        chat: &str,
        operation: &str,
        name: &str,
    ) -> std::result::Result<CreatedMachineSource, RemoteOpError> {
        self.0
            .create_machine_source(project_id, source_id, chat, operation, name)
            .await
    }
}

fn machine_code(error: &RemoteOpError) -> String {
    match error {
        RemoteOpError::Host { code, .. } => {
            let wire = code.wire();
            if wire.len() <= 64 && wire.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_') {
                wire.to_owned()
            } else {
                "machine_failed".to_owned()
            }
        }
        RemoteOpError::Core(error) => failure_code(error.clone()).to_owned(),
    }
}

impl Client {
    /// Record the confirmation card of a machine request; nothing is created.
    /// An already supplied shell decision is applied at once.
    pub(super) async fn machine_request_received(
        &mut self,
        request: ProjectCreateRequest,
        chat: &str,
        state: &mut ProjectCreateState,
    ) -> Result<Option<Value>> {
        let id = request.request_id.clone();
        state.entries.insert(
            id.clone(),
            Entry {
                request: Some(request),
                ..Entry::new(Status::ConfirmationRequired)
            },
        );
        match state.machine_decision.clone() {
            Some(decision) => {
                self.decide_machine_project(chat, &id, decision, state)
                    .await
            }
            None => Ok(None),
        }
    }

    /// Apply the user's decision to a pending machine request and return the
    /// `project_create_result` report (`confirmed`, `declined` or `failed`).
    /// `None` when the request is unknown or already decided.
    ///
    /// # Errors
    /// Only cancellation; every other failure becomes a `failed` report.
    pub(super) async fn decide_machine_project(
        &mut self,
        chat: &str,
        request_id: &str,
        decision: MachineProjectDecision,
        state: &mut ProjectCreateState,
    ) -> Result<Option<Value>> {
        let filters = state
            .entries
            .get(request_id)
            .and_then(|entry| entry.request.as_ref())
            .map(|request| ProjectFilters {
                personal: request.team_id.is_none(),
                team_id: request.team_id.clone(),
                include_archived: None,
            });
        let Some(filters) = filters else {
            return Ok(None);
        };
        let mut steps = RelaySteps(self.projects().with_filters(filters));
        decide(&mut steps, chat, request_id, decision, state).await
    }
}

fn failed(chat: &str, id: &str, entry: &mut Entry, code: &str) -> Value {
    entry.status = Status::Failed;
    entry.record = None;
    entry.error_code = Some(code.to_owned());
    entry.failure_reported = true;
    let mut payload = json!({"chat_id": chat, "request_id": id, "status": "failed"});
    payload["error_code"] = json!(code);
    payload
}

/// The state machine behind confirm/decline, generic over the machine steps.
pub(super) async fn decide<M: MachineSteps>(
    steps: &mut M,
    chat: &str,
    id: &str,
    decision: MachineProjectDecision,
    state: &mut ProjectCreateState,
) -> Result<Option<Value>> {
    let Some(entry) = state.entries.get_mut(id) else {
        return Ok(None);
    };
    let Some(request) = entry
        .request
        .clone()
        .filter(|_| entry.status == Status::ConfirmationRequired)
    else {
        return Ok(None);
    };
    let host = match decision {
        MachineProjectDecision::Decline => {
            entry.status = Status::Declined;
            return Ok(Some(
                json!({"chat_id": chat, "request_id": id, "status": "declined"}),
            ));
        }
        MachineProjectDecision::Unavailable => {
            return Ok(Some(failed(chat, id, entry, "confirmation_unavailable")));
        }
        MachineProjectDecision::Confirm {
            host_device_hash: Some(hash),
        } => hash,
        MachineProjectDecision::Confirm {
            host_device_hash: None,
        } => match steps.hosts().await {
            Ok(hosts) => match hosts.as_slice() {
                [only] => only.host_device_hash.clone(),
                [] => return Ok(Some(failed(chat, id, entry, "no_machine_host"))),
                _ => return Ok(Some(failed(chat, id, entry, "machine_selection_required"))),
            },
            Err(error) => return Ok(Some(failed(chat, id, entry, &machine_code(&error)))),
        },
    };
    let record = match steps.create_project(&request).await {
        Ok(record) => record,
        Err(Error::Cancelled) => return Err(Error::Cancelled),
        Err(error) => return Ok(Some(failed(chat, id, entry, failure_code(error)))),
    };
    let operation = format!("create-{}", uuid::Uuid::new_v4());
    let folder = machine_folder(steps, &record, &host, chat, &operation).await;
    match folder {
        Ok((source_id, folder)) => {
            let machine = json!({"sourceId": source_id, "path": folder.path, "folderName": folder.folder_name});
            let payload = json!({
                "chat_id": chat, "request_id": id, "status": "confirmed",
                "project_id": record.project_id, "focus_id": record.focus_id,
                "source_id": source_id, "path": folder.path, "folder_name": folder.folder_name,
            });
            entry.status = Status::Created;
            entry.record = Some(record);
            entry.machine = Some(machine);
            Ok(Some(payload))
        }
        Err(error) => {
            // The Project (and with it the placeholder source) must not stay behind;
            // the machine error stays the reported reason even if cleanup fails.
            let _ = steps.undo_project(&record).await;
            let code = machine_code(&error);
            Ok(Some(failed(chat, id, entry, &code)))
        }
    }
}

async fn machine_folder<M: MachineSteps>(
    steps: &mut M,
    record: &CreatedProjectRecord,
    host: &str,
    chat: &str,
    operation: &str,
) -> std::result::Result<(String, CreatedMachineSource), RemoteOpError> {
    let source = steps
        .propose(&record.project_id, host, &record.name)
        .await?;
    let folder = steps
        .create(&record.project_id, &source, chat, operation, &record.name)
        .await?;
    Ok((source, folder))
}

#[cfg(test)]
#[path = "project_create_machine_tests.rs"]
mod tests;
