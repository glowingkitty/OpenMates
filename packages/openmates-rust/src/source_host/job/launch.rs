//! Turns a verified portable remote-command request into a confined, streaming
//! process on the Project root.
//!
//! The plan reuses the file-ops `run_command` confinement: the detected sandbox
//! tier, private-path and Git-config masks from `command_scope`, the fixed safe
//! base environment (nothing inherited) and the streaming runner of
//! `command_stream` with its stop handle, retained-output cap and deadline
//! bounds. Remote jobs add one mode: `read_only` source access mounts the root
//! read-only (and demotes writable Git admin paths to read-only).
//!
//! Everything this host cannot confine yet is refused with a typed server
//! error code and never run weaker: writable profiles, network profiles,
//! credential profiles, background with `read_write`, and a machine without a
//! sandbox tier.
//!
//! Mirrors the runtime request of `remoteCommandRuntime.ts`.
//! spec: specifications/features/app-skills/code-run code-run.remote.confinement
//! code-run.remote.private-path-deny code-run.remote.sandbox-tiers
//! code-run.remote.ignored-project-files

use super::portable::{Mode, PortableRequest, SourceAccess};
use super::wire::RemoteCommandErrorCode;
use crate::source_host::command_sandbox::{
    BWRAP_HOME, Sandbox, SandboxTier, Unavailable, detect, linux_system_paths, macos_system_paths,
};
use crate::source_host::command_scope::{PlanInputs, plan};
use crate::source_host::command_stream::{CommandStream, StreamError, spawn_streaming};
use crate::source_host::commands::launch_command;
use crate::source_host::fs_safe::resolve_approved;
use crate::source_host::reads::HostRoot;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// A refused launch: the server error code to report and a local diagnostic.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct LaunchError {
    /// Code sent in the terminal `failed` event.
    pub(crate) code: RemoteCommandErrorCode,
    /// Local, non-secret diagnostic text.
    pub(crate) message: String,
}

impl LaunchError {
    fn new(code: RemoteCommandErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl std::fmt::Display for LaunchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code.as_str(), self.message)
    }
}
impl std::error::Error for LaunchError {}

/// A running confined job. Dropping it stops the process group and removes
/// the per-run Seatbelt scratch directory.
pub(crate) struct JobProcess {
    /// Streaming handle: `events()` until `Exit`, `stop()` to terminate.
    pub(crate) stream: CommandStream,
    /// Tier that confines the process.
    pub(crate) tier: SandboxTier,
    _scratch: Scratch,
}

struct Scratch(Option<PathBuf>);

impl Drop for Scratch {
    fn drop(&mut self) {
        if let Some(path) = &self.0 {
            let _ = std::fs::remove_dir_all(path);
        }
    }
}

fn scratch_directory() -> Result<PathBuf, LaunchError> {
    use std::os::unix::fs::DirBuilderExt;
    let fail = |e: std::io::Error| {
        LaunchError::new(
            RemoteCommandErrorCode::LaunchFailed,
            format!("scratch directory: {e}"),
        )
    };
    let base = std::fs::canonicalize(std::env::temp_dir()).map_err(fail)?;
    let path = base.join(format!("openmates-job-{}", uuid::Uuid::new_v4()));
    let mut builder = std::fs::DirBuilder::new();
    builder.mode(0o700);
    builder.create(&path).map_err(fail)?;
    builder.create(path.join("home")).map_err(fail)?;
    builder.create(path.join("tmp")).map_err(fail)?;
    Ok(path)
}

/// Refuse what this host cannot confine, before touching the filesystem.
///
/// # Errors
/// `invalid_request` (background with `read_write`),
/// `resource_not_granted` (writable profiles),
/// `network_profile_unavailable`, `credential_unavailable`.
pub(crate) fn check_supported(request: &PortableRequest) -> Result<(), LaunchError> {
    let policy = &request.policy;
    if policy.mode == Mode::Background && policy.source_access == SourceAccess::ReadWrite {
        return Err(LaunchError::new(
            RemoteCommandErrorCode::InvalidRequest,
            "Background commands cannot have read-write source access",
        ));
    }
    if !policy.writable_profiles.is_empty() {
        return Err(LaunchError::new(
            RemoteCommandErrorCode::ResourceNotGranted,
            "Writable profiles are not supported by this host",
        ));
    }
    if policy.network_profile.is_some() {
        return Err(LaunchError::new(
            RemoteCommandErrorCode::NetworkProfileUnavailable,
            "Network profiles are not supported by this host",
        ));
    }
    if !policy.credential_profiles.is_empty() {
        return Err(LaunchError::new(
            RemoteCommandErrorCode::CredentialUnavailable,
            "Credential profiles are not supported by this host",
        ));
    }
    if policy.argv[0].starts_with('-') {
        return Err(LaunchError::new(
            RemoteCommandErrorCode::InvalidRequest,
            "Command program is invalid",
        ));
    }
    Ok(())
}

/// The sandbox tier of this machine.
///
/// # Errors
/// `unsupported_platform` or `confinement_unavailable`.
pub(crate) fn detect_sandbox() -> Result<Sandbox, LaunchError> {
    detect().map_err(|unavailable| match unavailable {
        Unavailable::UnsupportedPlatform => LaunchError::new(
            RemoteCommandErrorCode::UnsupportedPlatform,
            "This platform cannot confine remote commands",
        ),
        Unavailable::ConfinementUnavailable => LaunchError::new(
            RemoteCommandErrorCode::ConfinementUnavailable,
            "No sandbox is available to confine remote commands",
        ),
    })
}

fn host_error(error: crate::source_host::HostError) -> LaunchError {
    let code = if error.code == "confinement_unavailable" {
        RemoteCommandErrorCode::ConfinementUnavailable
    } else {
        RemoteCommandErrorCode::InvalidRequest
    };
    LaunchError::new(code, error.message)
}

/// Canonical working directory inside `root`: no escape, no symlink hop, not
/// private, a directory.
fn resolve_cwd(host: &HostRoot, root: &Path, cwd: &str) -> Result<PathBuf, LaunchError> {
    if cwd == "." {
        return Ok(root.to_path_buf());
    }
    let resolved = resolve_approved(root, cwd).map_err(host_error)?;
    let policy = host.policy(root, &[cwd], false).map_err(host_error)?;
    if policy.is_private(cwd, true).map_err(host_error)? {
        return Err(LaunchError::new(
            RemoteCommandErrorCode::InvalidRequest,
            "Command cwd is private",
        ));
    }
    if !resolved.is_dir() {
        return Err(LaunchError::new(
            RemoteCommandErrorCode::InvalidRequest,
            "Command cwd is not a directory",
        ));
    }
    Ok(resolved)
}

/// Detect the sandbox tier and start the job. Blocking only for the path
/// scan and spawn; the returned process streams on its own threads.
///
/// # Errors
/// [`LaunchError`] with the server code for every refusal; see
/// [`check_supported`], [`detect_sandbox`] and [`launch_on`].
pub(crate) fn launch(
    host: &HostRoot,
    request: &PortableRequest,
    worktree: bool,
) -> Result<JobProcess, LaunchError> {
    check_supported(request)?;
    let sandbox = detect_sandbox()?;
    launch_on(host, request, &sandbox, worktree)
}

/// [`launch`] on a given tier (the driver reuses its detection; tests pass
/// one explicitly).
///
/// # Errors
/// `invalid_request` for unsupported policy, a cwd escape/private cwd or an
/// out-of-range deadline; `confinement_unavailable` when the private-path
/// plan cannot be built; `launch_failed` when the launcher cannot start.
pub(crate) fn launch_on(
    host: &HostRoot,
    request: &PortableRequest,
    sandbox: &Sandbox,
    worktree: bool,
) -> Result<JobProcess, LaunchError> {
    check_supported(request)?;
    let policy = &request.policy;
    let root = host.canonical().map_err(host_error)?;
    let cwd = resolve_cwd(host, &root, &policy.cwd)?;
    let seatbelt = sandbox.tier == SandboxTier::Seatbelt;
    let scratch = Scratch(if seatbelt {
        Some(scratch_directory()?)
    } else {
        None
    });
    let mut confinement = plan(
        host,
        PlanInputs {
            root: &root,
            cwd: &cwd,
            worktree,
            system: if seatbelt {
                macos_system_paths()
            } else {
                linux_system_paths()
            },
            scratch: scratch
                .0
                .clone()
                .unwrap_or_else(|| PathBuf::from(BWRAP_HOME)),
        },
    )
    .map_err(host_error)?;
    if policy.source_access == SourceAccess::ReadOnly {
        confinement.root_read_only = true;
        let writable = std::mem::take(&mut confinement.git.writable);
        confinement.git.read_only.extend(writable);
    }
    let command = launch_command(sandbox, &confinement, &policy.argv).map_err(host_error)?;
    let stream = spawn_streaming(command, Duration::from_millis(policy.deadline_ms), &[]).map_err(
        |error| match error {
            StreamError::InvalidDeadline => LaunchError::new(
                RemoteCommandErrorCode::InvalidRequest,
                "Deadline is out of range",
            ),
            StreamError::Launch(e) => LaunchError::new(
                RemoteCommandErrorCode::LaunchFailed,
                format!("sandbox launch: {e}"),
            ),
        },
    )?;
    Ok(JobProcess {
        stream,
        tier: sandbox.tier,
        _scratch: scratch,
    })
}
