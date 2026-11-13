//! Attach local folders as Project sources before hosting (npm
//! `resolveRemoteAccessRoots`, `remoteAccessHostingCandidates` and
//! `resolveRemoteAccessBindings` in `openmates-cli/src/{remoteAccess,cli}.ts`).
//!
//! Shared core: root canonicalization, repository discovery, the stored
//! association lookup, Project creation/selection, source registration with
//! encrypted name and metadata, and the local `remote-sources.json` upsert. The
//! CLI shell only prompts for the choices this module asks for.

use super::fs_safe::canonical_root;
use super::runner::SourceHostRunSource;
use super::store::{
    StoredRemoteSource, load_remote_sources, remote_cache_path, remote_source_type,
    upsert_remote_source,
};
use super::{HostError, HostResult, NameOrder, command_sandbox, host_capability_names};
use crate::client::Client;
use crate::error::Error;
use crate::work::{
    ProjectCreate, ProjectDefaultFocus, ProjectFilters, ProjectSettingsPatch,
    ProjectSourceCapabilitiesPatch, ProjectSourceCapability, ProjectSourceCreate, ProjectSourceStatus,
    ProjectSourceType, ProjectWriteMode, Projects,
};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

/// An attach failure: a local filesystem/store problem (with the npm code and
/// a local diagnostic) or a backend/client error.
#[derive(Debug)]
pub enum AttachError {
    /// Local root, discovery or `remote-sources.json` failure.
    Local(HostError),
    /// Backend or session failure.
    Client(Error),
}

impl From<HostError> for AttachError {
    fn from(error: HostError) -> Self {
        Self::Local(error)
    }
}

impl From<Error> for AttachError {
    fn from(error: Error) -> Self {
        Self::Client(error)
    }
}

impl std::fmt::Display for AttachError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Local(error) => error.fmt(f),
            Self::Client(error) => error.fmt(f),
        }
    }
}

impl std::error::Error for AttachError {}

/// Result alias for attach operations.
pub type AttachResult<T> = std::result::Result<T, AttachError>;

/// npm `MAX_APPROVED_ROOTS`.
pub const MAX_APPROVED_ROOTS: usize = 16;

/// npm `resolveRemoteAccessRoots`: each `--path` (or the working directory)
/// must be an existing directory; results are canonical and deduplicated.
///
/// # Errors
/// `operation_failed` for empty values, too many roots, missing directories or
/// roots overlapping the private state directory (`protected_path`).
pub fn resolve_roots(paths: &[String], cwd: &Path, state_dir: &Path) -> HostResult<Vec<PathBuf>> {
    let requested: Vec<PathBuf> = if paths.is_empty() {
        vec![cwd.to_path_buf()]
    } else {
        paths.iter().map(PathBuf::from).collect()
    };
    if paths.iter().any(String::is_empty) {
        return Err(HostError::failed("--path requires a non-empty folder value"));
    }
    if requested.len() > MAX_APPROVED_ROOTS {
        return Err(HostError::failed(format!(
            "remote-access accepts at most {MAX_APPROVED_ROOTS} approved roots"
        )));
    }
    let mut roots: Vec<PathBuf> = Vec::new();
    for value in requested {
        let candidate = cwd.join(value);
        if !std::fs::metadata(&candidate).is_ok_and(|m| m.is_dir()) {
            return Err(HostError::failed(format!(
                "Remote source path does not exist or is not a directory: {}",
                candidate.display()
            )));
        }
        let canonical = canonical_root(&candidate, state_dir)?;
        if !roots.contains(&canonical) {
            roots.push(canonical);
        }
    }
    Ok(roots)
}

/// Hosting candidates and the folders discovery could not read.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HostingCandidates {
    /// Roots to attach, in order.
    pub roots: Vec<PathBuf>,
    /// Approved-root-relative folders skipped for permission errors.
    pub permission_denied: Vec<String>,
}

/// npm `remoteAccessHostingCandidates`: an explicit `--path` is the source;
/// otherwise every Git repository below the working directory becomes one
/// (falling back to the directory itself when none exists).
///
/// # Errors
/// `operation_failed` for unexpected IO errors during discovery.
pub fn hosting_candidates(roots: &[PathBuf], explicit_path: bool) -> HostResult<HostingCandidates> {
    if explicit_path {
        return Ok(HostingCandidates {
            roots: roots.to_vec(),
            permission_denied: Vec::new(),
        });
    }
    let (mut repositories, mut denied) = (Vec::new(), Vec::new());
    for root in roots {
        let mut pending = vec![root.clone()];
        while let Some(directory) = pending.pop() {
            let entries = match std::fs::read_dir(&directory) {
                Ok(entries) => entries,
                Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {
                    let relative = directory.strip_prefix(root).unwrap_or(&directory);
                    let label = relative.to_string_lossy();
                    denied.push(if label.is_empty() { ".".to_owned() } else { label.into_owned() });
                    continue;
                }
                Err(error) => return Err(HostError::io("Repository discovery", &error)),
            };
            let mut children = Vec::new();
            let mut repository = false;
            for entry in entries {
                let entry = entry.map_err(|e| HostError::io("Repository discovery", &e))?;
                let kind = entry.file_type().map_err(|e| HostError::io("Repository discovery", &e))?;
                if entry.file_name() == ".git" {
                    repository |= kind.is_dir() || kind.is_file();
                    continue;
                }
                if kind.is_dir() {
                    children.push(entry.path());
                }
            }
            if repository {
                let real = std::fs::canonicalize(&directory).map_err(|e| HostError::io("Repository discovery", &e))?;
                if !repositories.contains(&real) {
                    repositories.push(real);
                }
            }
            pending.extend(children);
        }
    }
    // npm sorts with the default (code unit) comparator.
    repositories.sort_by(|a: &PathBuf, b| a.to_string_lossy().encode_utf16().cmp(b.to_string_lossy().encode_utf16()));
    denied.sort();
    Ok(HostingCandidates {
        roots: if repositories.is_empty() { roots.to_vec() } else { repositories },
        permission_denied: denied,
    })
}

/// How an unattached root picks its Project.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProjectChoice {
    /// Create a new encrypted Project named after the folder.
    New,
    /// An existing Project ID or slug in the hosting context.
    Existing(String),
}

/// Hosting context and local state shared by every attach call.
#[derive(Clone, Debug)]
pub struct AttachContext {
    /// Team ID, or `None` for Personal.
    pub team_id: Option<String>,
    /// npm-compatible state directory holding `remote-sources.json`.
    pub state_dir: PathBuf,
}

impl AttachContext {
    fn filters(&self) -> ProjectFilters {
        ProjectFilters {
            personal: self.team_id.is_none(),
            team_id: self.team_id.clone(),
            include_archived: None,
        }
    }
    fn projects<'a>(&self, client: &'a mut Client) -> Projects<'a> {
        client.projects().with_filters(self.filters())
    }
}

/// A stored association whose Project is still visible in this context.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoredAttachment {
    /// Canonical root.
    pub root: PathBuf,
    /// Bound Project.
    pub project_id: String,
    /// Stored source ID (reused so requesters keep their source).
    pub source_id: String,
}

/// Split candidate roots into already-attached ones and roots that need a
/// Project choice (npm: a stored record with a `projectId` that the user can
/// still see).
///
/// # Errors
/// Local store errors and Project listing errors.
pub async fn stored_attachments(
    client: &mut Client,
    context: &AttachContext,
    roots: &[PathBuf],
) -> AttachResult<(Vec<StoredAttachment>, Vec<PathBuf>)> {
    let stored = load_remote_sources(&context.state_dir)?;
    let visible: Vec<String> = context
        .projects(client)
        .list()
        .await?
        .iter()
        .filter_map(|p| p["project_id"].as_str().map(str::to_owned))
        .collect();
    let (mut attached, mut unresolved) = (Vec::new(), Vec::new());
    for root in roots {
        let root_text = root.to_string_lossy();
        let found = stored.iter().find(|s| s.root_path == root_text && s.project_id.is_some());
        match found.and_then(|s| s.project_id.as_ref().map(|p| (s, p))) {
            Some((source, project)) if visible.contains(project) => attached.push(StoredAttachment {
                root: root.clone(),
                project_id: project.clone(),
                source_id: source.source_id.clone(),
            }),
            _ => unresolved.push(root.clone()),
        }
    }
    Ok((attached, unresolved))
}

/// Unarchived Projects offered for an interactive choice: `(project_id, name)`.
///
/// # Errors
/// Project listing errors.
pub async fn selectable_projects(client: &mut Client, context: &AttachContext) -> AttachResult<Vec<(String, String)>> {
    Ok(context
        .projects(client)
        .list()
        .await?
        .iter()
        .filter(|p| p["archived"] != true)
        .filter_map(|p| {
            Some((
                p["project_id"].as_str()?.to_owned(),
                p["name"].as_str().unwrap_or_default().to_owned(),
            ))
        })
        .collect())
}

/// npm `readRootProjectInstructions`: `AGENTS.md`, else `CLAUDE.md`
/// (case-insensitive; the exact upper-case name wins).
fn root_instructions(root: &Path) -> HostResult<Option<(String, String)>> {
    let mut names = Vec::new();
    for entry in std::fs::read_dir(root).map_err(|e| HostError::io("Project instructions", &e))? {
        let entry = entry.map_err(|e| HostError::io("Project instructions", &e))?;
        let is_file = entry.file_type().map_err(|e| HostError::io("Project instructions", &e))?.is_file();
        if let (true, Ok(name)) = (is_file, entry.file_name().into_string()) {
            names.push(name);
        }
    }
    let order = NameOrder::new()?;
    for (canonical, exact) in [("agents.md", "AGENTS.md"), ("claude.md", "CLAUDE.md")] {
        let mut matching: Vec<&String> = names.iter().filter(|n| n.to_lowercase() == canonical).collect();
        matching.sort_by(|a, b| match (a.as_str() == exact, b.as_str() == exact) {
            (true, _) => std::cmp::Ordering::Less,
            (_, true) => std::cmp::Ordering::Greater,
            _ => order.compare(a, b),
        });
        if let Some(name) = matching.first() {
            let text = std::fs::read_to_string(root.join(name.as_str()))
                .map_err(|e| HostError::io("Project instructions", &e))?;
            return Ok(Some((text, (*name).clone())));
        }
    }
    Ok(None)
}

fn folder_name(root: &Path) -> String {
    root.file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| root.to_string_lossy().into_owned())
}

/// Bind an unattached root to a Project: create one (`ProjectChoice::New`,
/// imported `AGENTS.md`/`CLAUDE.md` as default focus) or set the chosen
/// Project's write mode. Returns a fresh attachment with a new source ID.
///
/// # Errors
/// Project creation, resolution or settings errors from the backend.
pub async fn attach_root(
    client: &mut Client,
    context: &AttachContext,
    root: &Path,
    choice: &ProjectChoice,
    write_mode: ProjectWriteMode,
) -> AttachResult<StoredAttachment> {
    let mut projects = context.projects(client);
    let project_id = match choice {
        ProjectChoice::New => {
            let name = folder_name(root);
            let imported = root_instructions(root)?;
            let label = if name.trim().is_empty() { "Untitled project".to_owned() } else { name.trim().to_owned() };
            let focus = ProjectDefaultFocus {
                focus_id: uuid::Uuid::new_v4().to_string(),
                name: format!("Work on {label}"),
                instructions: imported
                    .as_ref()
                    .map(|(text, _)| text.trim().to_owned())
                    .filter(|text| !text.is_empty())
                    .unwrap_or_else(|| {
                        format!(
                            "Help with work in {label}. Follow the user's instructions and the Project's connected source guidance."
                        )
                    }),
                source: imported.map_or_else(|| "generated".to_owned(), |(_, source)| source),
            };
            let created = projects
                .create(ProjectCreate {
                    name,
                    icon: Some("folder".into()),
                    color: Some("default".into()),
                    write_mode: Some(write_mode),
                    default_focus: Some(focus),
                    ..Default::default()
                })
                .await?;
            created["project_id"].as_str().ok_or(Error::Protocol)?.to_owned()
        }
        ProjectChoice::Existing(selector) => {
            let project = projects.show(selector).await?;
            let id = project["project_id"].as_str().ok_or(Error::Protocol)?.to_owned();
            projects
                .update_settings(
                    &id,
                    ProjectSettingsPatch {
                        write_mode: Some(write_mode),
                        ..Default::default()
                    },
                )
                .await?;
            id
        }
    };
    Ok(StoredAttachment {
        root: root.to_path_buf(),
        project_id,
        source_id: uuid::Uuid::new_v4().to_string(),
    })
}

/// The capabilities a normal (folder-backed) source is registered with.
/// `create_source` belongs to placeholders only (see `creation_host.rs`), so
/// it is never part of this set.
pub(crate) fn host_capabilities() -> Vec<ProjectSourceCapability> {
    host_capability_names(command_sandbox::detect().is_ok(), false)
        .iter()
        .map(|c| match *c {
            "read" => ProjectSourceCapability::Read,
            "search" => ProjectSourceCapability::Search,
            "import" => ProjectSourceCapability::Import,
            "run_command" => ProjectSourceCapability::RunCommand,
            "create_source" => ProjectSourceCapability::CreateSource,
            _ => ProjectSourceCapability::WriteRequest,
        })
        .collect()
}

fn now_seconds() -> u64 {
    crate::client::now_ms() / 1000
}

/// npm per-binding preparation: ensure the default focus, record the local
/// association, register the source (encrypted display name and
/// `{root, binding_root}` metadata) or align its capabilities, and return
/// the run input.
///
/// # Errors
/// Local store failures; backend errors otherwise.
pub async fn prepare_source(
    client: &mut Client,
    context: &AttachContext,
    attachment: &StoredAttachment,
) -> AttachResult<SourceHostRunSource> {
    let mut projects = context.projects(client);
    projects.ensure_default_focus(&attachment.project_id).await?;
    let root_text = attachment.root.to_string_lossy().into_owned();
    let display_name = folder_name(&attachment.root);
    let source_type = remote_source_type(&attachment.root);
    let now = now_seconds();
    let cache = remote_cache_path(&context.state_dir, &attachment.source_id)?;
    upsert_remote_source(
        &context.state_dir,
        StoredRemoteSource {
            source_id: attachment.source_id.clone(),
            project_id: Some(attachment.project_id.clone()),
            source_type: source_type.to_owned(),
            root_path: root_text.clone(),
            display_name: display_name.clone(),
            cache_path: cache.to_string_lossy().into_owned(),
            status: "offline".into(),
            created_at: now,
            updated_at: now,
            extra: serde_json::Map::new(),
        },
    )
    ?;
    let desired = host_capabilities();
    let remote = projects.list_sources_raw(&attachment.project_id).await?;
    match remote.iter().find(|s| s["source_id"] == attachment.source_id.as_str()) {
        None => {
            let mut metadata = serde_json::Map::new();
            metadata.insert("root".into(), json!(root_text));
            metadata.insert("binding_root".into(), json!(root_text));
            projects
                .create_source(
                    &attachment.project_id,
                    ProjectSourceCreate {
                        source_id: attachment.source_id.clone(),
                        source_type: if source_type == "local_git_repository" {
                            ProjectSourceType::LocalGitRepository
                        } else {
                            ProjectSourceType::LocalFolder
                        },
                        display_name,
                        metadata,
                        capabilities: desired,
                        status: ProjectSourceStatus::Offline,
                        created_at: now,
                        updated_at: now,
                        last_indexed_at: None,
                    },
                )
                .await?;
        }
        Some(existing) => {
            let mut current: Vec<String> = existing["capabilities"]
                .as_array()
                .map(|values| values.iter().filter_map(Value::as_str).map(str::to_owned).collect())
                .unwrap_or_default();
            let mut wanted: Vec<String> = host_capability_names(command_sandbox::detect().is_ok(), false)
                .iter()
                .map(|c| (*c).to_owned())
                .collect();
            current.sort();
            wanted.sort();
            if current != wanted {
                projects
                    .update_source_capabilities(
                        &attachment.project_id,
                        &attachment.source_id,
                        ProjectSourceCapabilitiesPatch {
                            capabilities: desired,
                            updated_at: now,
                        },
                    )
                    .await?;
            }
        }
    }
    Ok(SourceHostRunSource {
        project_id: attachment.project_id.clone(),
        source_id: attachment.source_id.clone(),
        team_id: context.team_id.clone(),
        root: attachment.root.clone(),
    })
}
