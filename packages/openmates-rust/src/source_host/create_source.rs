//! `create_source`: create a new Project folder on the machine owner's
//! configured "new Projects" folder (shared core, native source host only;
//! plan native-agentic-coding-readiness R10). The folder name is derived from
//! the Project name, the target is exactly `<folder>/<name>` and is never
//! written into or over an existing path. The new folder becomes a Git
//! repository on `main` with a `README.md` heading and one first commit made
//! through the hardened runner of `worktrees_git.rs`. Failures after the
//! folder exists remove only what this call created.
//! spec: specifications/features/projects (remote sources).

use super::worktrees_git::{git, head_commit, run};
use super::{HostError, HostResult};
use hmac::{Hmac, Mac};
use serde_json::{Value, json};
use sha2::Sha256;
use std::ffi::OsStr;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};

/// Wire operation name.
pub(crate) const OPERATION: &str = "create_source";
/// Branch the new repository starts on.
pub(crate) const INITIAL_BRANCH: &str = "main";
const MAX_FOLDER_NAME: usize = 64;
const MAX_PROJECT_NAME_BYTES: usize = 200;
const DIGEST_DOMAIN: &str = "openmates-remote-create-source-proposal-v1";

/// A validated `arguments.create` proposal.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct CreateProposal {
    /// Approval-bound operation id.
    pub(crate) operation_id: String,
    /// The Project name exactly as the user confirmed it.
    pub(crate) project_name: String,
}

/// The author of the first commit, read from the machine's Git identity.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct CommitIdentity {
    pub(crate) name: String,
    pub(crate) email: String,
}

/// What a successful creation produced.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct CreatedSource {
    /// Absolute path of the new folder.
    pub(crate) path: PathBuf,
    /// The derived folder name.
    pub(crate) folder_name: String,
    /// The first commit.
    pub(crate) head: String,
    /// The branch HEAD is on.
    pub(crate) branch: &'static str,
}

impl CreatedSource {
    /// The wire result `{path, folder_name, head, branch}`.
    pub(crate) fn to_json(&self) -> Value {
        json!({
            "path": self.path.to_string_lossy(),
            "folder_name": self.folder_name,
            "head": self.head,
            "branch": self.branch,
        })
    }
}

fn invalid(message: &str) -> HostError {
    HostError::new("invalid_request", message)
}

/// Validate `arguments.create`: `{operation_id, project_name}`; unknown keys
/// are refused.
///
/// # Errors
/// `invalid_request` for any shape, size or charset violation.
pub(crate) fn validate(value: &Value) -> HostResult<CreateProposal> {
    let object = value
        .as_object()
        .ok_or_else(|| invalid("create must be an object"))?;
    if object
        .keys()
        .any(|key| !matches!(key.as_str(), "operation_id" | "project_name"))
    {
        return Err(invalid("create has an unsupported field"));
    }
    let operation_id = object
        .get("operation_id")
        .and_then(Value::as_str)
        .filter(|id| {
            (1..=128).contains(&id.len())
                && id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'-'))
        })
        .ok_or_else(|| invalid("create operation_id is invalid"))?
        .to_owned();
    let project_name = object
        .get("project_name")
        .and_then(Value::as_str)
        .filter(|name| {
            !name.trim().is_empty()
                && name.len() <= MAX_PROJECT_NAME_BYTES
                && !name.chars().any(char::is_control)
        })
        .ok_or_else(|| invalid("create project_name is invalid"))?
        .to_owned();
    Ok(CreateProposal {
        operation_id,
        project_name,
    })
}

/// HMAC-SHA256(projectKey, JSON tuple), built like `git_ops::digest`:
/// `["openmates-remote-create-source-proposal-v1", project_id, chat_id,
/// "create_source", operation_id, project_name]`. The backend holds it from
/// the user's confirmation; the host refuses a request whose recomputed
/// digest differs.
///
/// # Errors
/// `invalid_request` for an empty project or chat id.
pub(crate) fn digest(
    key: &[u8; 32],
    project_id: &str,
    chat_id: &str,
    proposal: &CreateProposal,
) -> HostResult<String> {
    if project_id.is_empty() || chat_id.is_empty() {
        return Err(invalid("create identity is incomplete"));
    }
    let message = json!([
        DIGEST_DOMAIN,
        project_id,
        chat_id,
        OPERATION,
        proposal.operation_id,
        proposal.project_name,
    ])
    .to_string();
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key)
        .map_err(|_| invalid("create identity is incomplete"))?;
    mac.update(message.as_bytes());
    Ok(mac
        .finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}

/// Derive the folder name: lowercase ASCII letters and digits, every other
/// character run becomes one `-`, no leading or trailing `-`, at most 64
/// characters. Names that yield nothing are refused, so the result can never
/// be `.`/`..` or start with a dot or dash.
///
/// # Errors
/// `invalid_project_name` when nothing usable remains.
pub(crate) fn folder_name(project_name: &str) -> HostResult<String> {
    let mut name = String::new();
    for c in project_name.chars() {
        if c.is_ascii_alphanumeric() {
            name.push(c.to_ascii_lowercase());
        } else if !name.is_empty() && !name.ends_with('-') {
            name.push('-');
        }
    }
    name.truncate(MAX_FOLDER_NAME);
    let name = name.trim_end_matches('-').to_owned();
    if name.is_empty() {
        return Err(HostError::new(
            "invalid_project_name",
            "The Project name has no letters or digits",
        ));
    }
    Ok(name)
}

/// The configured folder, or the stable `creation_not_configured` refusal.
///
/// # Errors
/// `creation_not_configured` when the machine owner set no folder;
/// `operation_failed` for an unreadable settings file.
pub(crate) fn configured_folder(state_dir: &Path) -> HostResult<PathBuf> {
    super::store::load_new_projects_dir(state_dir)?.ok_or_else(|| {
        HostError::new(
            "creation_not_configured",
            "No new-Projects folder is configured on this machine",
        )
    })
}

/// The machine's global Git identity: `~/.gitconfig`, then the XDG file under
/// `home`, read with `--file` so the repository the host runs in never
/// matters. `probe_dir` only gives Git a working directory.
///
/// # Errors
/// `identity_missing` without a non-empty `user.name` and `user.email`.
pub(crate) fn machine_identity(home: &Path, probe_dir: &Path) -> HostResult<CommitIdentity> {
    let files = [home.join(".gitconfig"), home.join(".config/git/config")];
    let read = |key: &str| -> HostResult<Option<String>> {
        for file in files.iter().filter(|f| f.is_file()) {
            let args: [&OsStr; 6] = [
                "config".as_ref(),
                "--includes".as_ref(),
                "--file".as_ref(),
                file.as_os_str(),
                "--get".as_ref(),
                key.as_ref(),
            ];
            let (code, value) = run(probe_dir, &args)?;
            let value = value.trim();
            if code == Some(0) && !value.is_empty() {
                return Ok(Some(value.to_owned()));
            }
        }
        Ok(None)
    };
    match (read("user.name")?, read("user.email")?) {
        (Some(name), Some(email)) => Ok(CommitIdentity { name, email }),
        _ => Err(HostError::new(
            "identity_missing",
            "No global Git user.name/user.email is configured",
        )),
    }
}

/// Everything checked before anything is written.
#[derive(Debug)]
pub(crate) struct CreationPlan {
    parent: PathBuf,
    folder_name: String,
    identity: CommitIdentity,
}

/// Validate name, configured folder, identity and target without writing.
/// Run it before consuming an approval so a refusal never costs one.
///
/// # Errors
/// `invalid_project_name`, `creation_folder_unavailable` (missing, not a
/// directory, a symlink or not absolute), `identity_missing`, `target_exists`.
pub(crate) fn preflight(
    new_projects_dir: &Path,
    project_name: &str,
    home: &Path,
) -> HostResult<CreationPlan> {
    let folder_name = folder_name(project_name)?;
    let unavailable = |why: &str| {
        HostError::new(
            "creation_folder_unavailable",
            format!("New-Projects folder {why}"),
        )
    };
    if !new_projects_dir.is_absolute() {
        return Err(unavailable("is not an absolute path"));
    }
    let meta =
        std::fs::symlink_metadata(new_projects_dir).map_err(|_| unavailable("does not exist"))?;
    if meta.file_type().is_symlink() {
        return Err(unavailable("is a symlink"));
    }
    if !meta.is_dir() {
        return Err(unavailable("is not a directory"));
    }
    let parent =
        std::fs::canonicalize(new_projects_dir).map_err(|_| unavailable("cannot be resolved"))?;
    let identity = machine_identity(home, &parent)?;
    let target = parent.join(&folder_name);
    if target.parent() != Some(parent.as_path()) {
        return Err(unavailable("would be left by the target"));
    }
    match std::fs::symlink_metadata(&target) {
        Ok(_) => Err(HostError::new(
            "target_exists",
            "The target path already exists",
        )),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(CreationPlan {
            parent,
            folder_name,
            identity,
        }),
        Err(e) => Err(HostError::io("New Project target", &e)),
    }
}

/// Create the folder, repository, `README.md` and first commit. Removes the
/// new folder again when any step fails.
///
/// # Errors
/// `target_exists` when the path appeared since [`preflight`]; the folder is
/// then left alone. `operation_failed` for IO or Git failures (cleaned up).
pub(crate) fn create(plan: &CreationPlan, project_name: &str) -> HostResult<CreatedSource> {
    let target = plan.parent.join(&plan.folder_name);
    // Non-recursive and exclusive: an existing path is never entered.
    std::fs::DirBuilder::new()
        .mode(0o755)
        .create(&target)
        .map_err(|e| {
            if e.kind() == std::io::ErrorKind::AlreadyExists {
                HostError::new("target_exists", "The target path already exists")
            } else {
                HostError::io("New Project folder", &e)
            }
        })?;
    match populate(&target, plan, project_name) {
        Ok(head) => Ok(CreatedSource {
            path: target,
            folder_name: plan.folder_name.clone(),
            head,
            branch: INITIAL_BRANCH,
        }),
        Err(error) => {
            // This call created `target` a moment ago and nothing else owns it.
            let _ = std::fs::remove_dir_all(&target);
            Err(error)
        }
    }
}

/// [`preflight`] then [`create`].
///
/// # Errors
/// See both.
pub(crate) fn create_source(
    new_projects_dir: &Path,
    project_name: &str,
    home: &Path,
) -> HostResult<CreatedSource> {
    create(
        &preflight(new_projects_dir, project_name, home)?,
        project_name,
    )
}

fn populate(target: &Path, plan: &CreationPlan, project_name: &str) -> HostResult<String> {
    git(
        target,
        "init",
        &[
            "init".as_ref(),
            "--quiet".as_ref(),
            "--initial-branch".as_ref(),
            INITIAL_BRANCH.as_ref(),
        ],
    )?;
    let heading = project_name
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    std::fs::write(target.join("README.md"), format!("# {heading}\n"))
        .map_err(|e| HostError::io("README.md", &e))?;
    git(
        target,
        "add",
        &["add".as_ref(), "--".as_ref(), "README.md".as_ref()],
    )?;
    let name = format!("user.name={}", plan.identity.name);
    let email = format!("user.email={}", plan.identity.email);
    git(
        target,
        "commit",
        &[
            "-c".as_ref(),
            name.as_ref(),
            "-c".as_ref(),
            email.as_ref(),
            "commit".as_ref(),
            "--quiet".as_ref(),
            "--no-verify".as_ref(),
            "--no-gpg-sign".as_ref(),
            "-m".as_ref(),
            "Initial commit".as_ref(),
        ],
    )?;
    Ok(head_commit(target)?)
}
