//! Host side of "create a new Project folder on this machine" beyond the
//! folder operation itself (plan native-agentic-coding-readiness R10): finding
//! the placeholders addressed to this device, binding them with the
//! `create_source` capability, and finishing a placeholder once its folder
//! exists (local record, then backend `complete-creation`, then serving the new
//! folder with the normal capabilities).
//! Invariants: a refusal never touches the placeholder; a folder is never
//! deleted after it was created; when completion fails the local record keeps
//! the placeholder id, so the next discovery completes it without a second
//! request. Placeholders are only bound when a new-Projects folder is set.
//! spec: specifications/features/projects (remote sources).

use super::attach::host_capabilities;
use super::create_source::CreatedSource;
use super::dispatch::HostedSource;
use super::reads::HostRoot;
use super::runner::{SourceHostRun, SourceHostRunSource};
use super::store::{
    StoredRemoteSource, load_new_projects_dir, load_remote_sources, remote_cache_path,
    upsert_remote_source,
};
use super::{HostError, HostResult};
use crate::client::{Client, SourceHostAdapter, SourceHostOperation};
use crate::error::{Error, Result};
use crate::work::{
    PendingSourceCreation, ProjectFilters, ProjectSourceCapability, ProjectSourceCompletion,
    ProjectSourceType,
};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// Stable code of a created folder whose backend completion failed.
pub(crate) const COMPLETION_FAILED: &str = "creation_completion_failed";
/// The most sources one host session registers (`prepare_source_host`).
const MAX_SOURCES: usize = 16;

/// Adapter of a placeholder binding: only the creation operation.
pub(crate) struct CreationAdapter;

impl SourceHostAdapter for CreationAdapter {
    fn implemented_capabilities(&self) -> Vec<ProjectSourceCapability> {
        vec![ProjectSourceCapability::CreateSource]
    }
    fn supports_operation(&self, operation: SourceHostOperation) -> bool {
        operation == SourceHostOperation::CreateSource
    }
}

/// The sources of the running host session. Starts as the run's sources and
/// grows with placeholders; a created folder replaces its placeholder entry.
#[derive(Clone, Debug)]
pub(crate) struct HostState {
    /// Sources to register, placeholders included.
    pub(crate) sources: Vec<SourceHostRunSource>,
    /// Source ids that are still placeholders (bound with `create_source`).
    pub(crate) placeholders: BTreeSet<String>,
    /// Set while the session must be registered fresh from this state because
    /// its stored bindings are stale (a reconnect would reuse them).
    pub(crate) rebind_needed: bool,
}

impl HostState {
    /// Start from the sources of a run.
    pub(crate) fn new(run: &SourceHostRun) -> Self {
        Self {
            sources: run.sources.clone(),
            placeholders: BTreeSet::new(),
            rebind_needed: false,
        }
    }

    /// The adapter for one source: creation-only for placeholders.
    pub(crate) fn adapter(&self, source_id: &str) -> Arc<dyn SourceHostAdapter> {
        if self.placeholders.contains(source_id) {
            Arc::new(CreationAdapter)
        } else {
            Arc::new(super::dispatch::FilesystemSourceAdapter)
        }
    }

    /// Request-dispatch view of the sources.
    pub(crate) fn hosted(&self, state_dir: &Path) -> Vec<HostedSource> {
        self.sources
            .iter()
            .map(|s| HostedSource {
                project_id: s.project_id.clone(),
                source_id: s.source_id.clone(),
                team_id: s.team_id.clone(),
                root: HostRoot {
                    root: s.root.clone(),
                    state_dir: state_dir.to_path_buf(),
                    policy_source: None,
                },
                // The per-source target-branch setting is not stored yet; chat
                // worktrees default to the branch checked out in the source root.
                target_branch: None,
            })
            .collect()
    }

    /// Serve a created folder: the placeholder becomes a normal source rooted
    /// at the new folder.
    pub(crate) fn adopt(&mut self, created: &HostedSource) {
        self.placeholders.remove(&created.source_id);
        if let Some(entry) = self
            .sources
            .iter_mut()
            .find(|s| s.source_id == created.source_id)
        {
            entry.root = created.root.root.clone();
        }
    }
}

/// Whether a new-Projects folder is configured (an unreadable settings file
/// counts as not configured here; discovery reports it as an error).
pub(crate) fn creation_configured(state_dir: &Path) -> bool {
    load_new_projects_dir(state_dir).is_ok_and(|dir| dir.is_some())
}

/// What one pending placeholder needs from this host.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Planned {
    /// Bind the placeholder with the `create_source` capability.
    Bind {
        project_id: String,
        source_id: String,
    },
    /// The folder already exists locally (an earlier completion failed): finish
    /// the placeholder without a new request.
    Recover {
        project_id: String,
        source_id: String,
        root: PathBuf,
    },
}

/// Match pending placeholders against the Projects this host can serve (by the
/// hash of the Project id) and its local records. Placeholders already known
/// are skipped; at most `room` are planned. Without a configured
/// new-Projects folder only recoveries are planned.
pub(crate) fn plan_pending(
    pending: &[PendingSourceCreation],
    visible_project_ids: &[String],
    known: &BTreeSet<String>,
    stored: &[StoredRemoteSource],
    configured: bool,
    room: usize,
) -> Vec<Planned> {
    let mut planned = Vec::new();
    for row in pending {
        if planned.len() >= room {
            break;
        }
        if known.contains(&row.source_id) {
            continue;
        }
        let Some(project_id) = visible_project_ids
            .iter()
            .find(|id| crate::work::hash(id) == row.hashed_project_id)
        else {
            continue;
        };
        let recoverable = stored.iter().find(|s| {
            s.source_id == row.source_id
                && s.project_id.as_deref() == Some(project_id.as_str())
                && Path::new(&s.root_path).is_dir()
        });
        if let Some(record) = recoverable {
            planned.push(Planned::Recover {
                project_id: project_id.clone(),
                source_id: row.source_id.clone(),
                root: PathBuf::from(&record.root_path),
            });
        } else if configured {
            planned.push(Planned::Bind {
                project_id: project_id.clone(),
                source_id: row.source_id.clone(),
            });
        }
    }
    planned
}

/// Result of one discovery pass.
#[derive(Debug, Default)]
pub(crate) struct Discovery {
    /// The session state gained sources and must be registered again.
    pub(crate) changed: bool,
    /// Lifecycle lines for the shell (for example a failed recovery).
    pub(crate) notes: Vec<String>,
}

fn personal() -> ProjectFilters {
    ProjectFilters {
        personal: true,
        ..Default::default()
    }
}

/// Look for placeholders addressed to this device and add them to `state`.
/// Personal Projects only: placeholders of Team Projects are not bound here.
///
/// # Errors
/// `Invalid` for an unreadable settings or record file; session and transport
/// errors from the backend.
pub(crate) async fn discover(
    client: &mut Client,
    run: &SourceHostRun,
    state: &mut HostState,
) -> Result<Discovery> {
    let mut found = Discovery::default();
    if state.sources.iter().any(|s| s.team_id.is_some()) || state.sources.len() >= MAX_SOURCES {
        return Ok(found);
    }
    let configured = load_new_projects_dir(&run.state_dir)
        .map_err(|_| Error::Invalid("host_settings_invalid"))?
        .is_some();
    let stored = load_remote_sources(&run.state_dir)
        .map_err(|_| Error::Invalid("remote_sources_invalid"))?;
    let (pending, visible) = {
        let mut projects = client.projects().with_filters(personal());
        let pending = projects.pending_source_creations().await?;
        if pending.is_empty() {
            return Ok(found);
        }
        let visible: Vec<String> = projects
            .list()
            .await?
            .iter()
            .filter_map(|p| p["project_id"].as_str().map(str::to_owned))
            .collect();
        (pending, visible)
    };
    let known: BTreeSet<String> = state.sources.iter().map(|s| s.source_id.clone()).collect();
    let plan = plan_pending(
        &pending,
        &visible,
        &known,
        &stored,
        configured,
        MAX_SOURCES - state.sources.len(),
    );
    for item in plan {
        match item {
            Planned::Bind {
                project_id,
                source_id,
            } => {
                state.placeholders.insert(source_id.clone());
                state.sources.push(SourceHostRunSource {
                    project_id,
                    source_id,
                    team_id: None,
                    // A placeholder has no folder; its binding only serves
                    // `create_source`, which never reads this root.
                    root: PathBuf::new(),
                });
                found.changed = true;
            }
            Planned::Recover {
                project_id,
                source_id,
                root,
            } => match complete_backend(client, &project_id, &source_id, &root).await {
                Ok(()) => {
                    state.sources.push(SourceHostRunSource {
                        project_id,
                        source_id,
                        team_id: None,
                        root,
                    });
                    found.changed = true;
                }
                Err(error) => found
                    .notes
                    .push(format!("create_source {} (will retry)", error.code)),
            },
        }
    }
    Ok(found)
}

fn now_seconds() -> u64 {
    crate::client::now_ms() / 1000
}

fn folder_label(root: &Path) -> HostResult<String> {
    root.file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .filter(|name| !name.is_empty())
        .ok_or_else(|| HostError::new(COMPLETION_FAILED, "The new folder has no name"))
}

/// Backend `complete-creation` for a created folder: the encrypted folder name
/// and `{root, binding_root}` metadata like a normal attach, with the host's
/// normal capabilities.
async fn complete_backend(
    client: &mut Client,
    project_id: &str,
    source_id: &str,
    root: &Path,
) -> HostResult<()> {
    let root_text = root.to_string_lossy().into_owned();
    let mut metadata = serde_json::Map::new();
    metadata.insert("root".into(), json!(root_text));
    metadata.insert("binding_root".into(), json!(root_text));
    let completion = ProjectSourceCompletion {
        source_type: ProjectSourceType::LocalGitRepository,
        display_name: folder_label(root)?,
        metadata,
        capabilities: host_capabilities(),
        updated_at: now_seconds(),
    };
    client
        .projects()
        .with_filters(personal())
        .complete_machine_source(project_id, source_id, completion)
        .await
        .map(|_| ())
        .map_err(|error| {
            HostError::new(
                COMPLETION_FAILED,
                format!("Completion was refused: {error}"),
            )
        })
}

/// Backend completion seam (a fake in tests).
pub(crate) trait CompleteCreation {
    /// Finish the placeholder `source_id` of `project_id` for the folder `root`.
    async fn complete(&mut self, project_id: &str, source_id: &str, root: &Path) -> HostResult<()>;
}

/// The real backend completion.
pub(crate) struct BackendCompletion<'a>(pub(crate) &'a mut Client);

impl CompleteCreation for BackendCompletion<'_> {
    async fn complete(&mut self, project_id: &str, source_id: &str, root: &Path) -> HostResult<()> {
        complete_backend(self.0, project_id, source_id, root).await
    }
}

fn record_local(
    state_dir: &Path,
    project_id: &str,
    source_id: &str,
    root: &Path,
) -> HostResult<()> {
    let now = now_seconds();
    let cache = remote_cache_path(state_dir, source_id)?;
    upsert_remote_source(
        state_dir,
        StoredRemoteSource {
            source_id: source_id.to_owned(),
            project_id: Some(project_id.to_owned()),
            source_type: "local_git_repository".to_owned(),
            root_path: root.to_string_lossy().into_owned(),
            display_name: folder_label(root)?,
            cache_path: cache.to_string_lossy().into_owned(),
            status: "offline".to_owned(),
            created_at: now,
            updated_at: now,
            extra: serde_json::Map::new(),
        },
    )
    .map(|_| ())
}

/// Turn the outcome of the folder operation into the request answer.
///
/// A refused creation (`created` is an error) is returned unchanged and the
/// completer is never called, so the placeholder stays untouched. After a
/// created folder the local record is written and the backend completed once;
/// a failure of either answers `creation_completion_failed` and leaves the
/// folder in place. On success the answer is the folder result and the new
/// source to serve.
///
/// # Errors
/// The refusal code of the folder operation, or `creation_completion_failed`.
pub(crate) async fn finish_creation<C: CompleteCreation>(
    completer: &mut C,
    source: &HostedSource,
    created: HostResult<CreatedSource>,
    state_dir: &Path,
) -> HostResult<(Value, HostedSource)> {
    let created = created?;
    let failed = |error: HostError| HostError::new(COMPLETION_FAILED, error.message);
    record_local(
        state_dir,
        &source.project_id,
        &source.source_id,
        &created.path,
    )
    .map_err(failed)?;
    completer
        .complete(&source.project_id, &source.source_id, &created.path)
        .await
        .map_err(failed)?;
    let served = HostedSource {
        project_id: source.project_id.clone(),
        source_id: source.source_id.clone(),
        team_id: source.team_id.clone(),
        root: HostRoot {
            root: created.path.clone(),
            state_dir: state_dir.to_path_buf(),
            policy_source: None,
        },
        target_branch: None,
    };
    Ok((created.to_json(), served))
}
