//! `run_command` for the filesystem host: proposal validation, the keyed
//! proposal digest and one confined, bounded run in the request root (shared
//! core, native source host only; plan native-agentic-coding-readiness R3).
//!
//! The command is an argv (never a shell string) run in the chat worktree or
//! the live source root through a sandbox tier of `command_sandbox.rs`; no
//! tier means refusal, never an unconfined run. Bounds follow npm
//! `remoteCommandRuntime.ts`. spec: specifications/features/app-skills/code-run
//! `code-run.remote.confinement`, `code-run.remote.resource-profiles`.

use super::command_process::{ProcessOutcome, run_bounded};
use super::command_sandbox::{
    BWRAP_HOME, Sandbox, SandboxTier, bwrap_argv, linux_system_paths, macos_system_paths,
    seatbelt_profile,
};
use super::command_scope::{PlanInputs, plan};
use super::fs_safe::resolve_approved;
use super::reads::HostRoot;
use super::{HostError, HostResult};
use hmac::{Hmac, Mac};
use serde_json::{Value, json};
use sha2::Sha256;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

/// Wire operation name.
pub(crate) const OPERATION: &str = "run_command";
const MAX_ARGUMENTS: usize = 128;
const MAX_ARGUMENT_BYTES: usize = 16 * 1024;
/// Smallest wall-clock limit a request may ask for.
pub(crate) const MIN_TIMEOUT_MS: u64 = 100;
/// Largest wall-clock limit (foreground commands only; long-running
/// background jobs are a later slice).
pub(crate) const MAX_TIMEOUT_MS: u64 = 30 * 60 * 1000;
/// Per-stream output cap when the request names none.
pub(crate) const DEFAULT_OUTPUT_BYTES: usize = 64 * 1024;
/// Largest per-stream output cap (both streams together stay below the
/// 256 KiB the relay accepts for one sealed answer).
pub(crate) const MAX_OUTPUT_BYTES: usize = 96 * 1024;
const MIN_OUTPUT_BYTES: usize = 1024;

/// Fixed environment of every command: nothing from the host process is
/// inherited, so tokens, SSH agents and cloud credentials stay outside.
const BASE_ENVIRONMENT: [(&str, &str); 6] = [
    ("LANG", "C.UTF-8"),
    ("LC_ALL", "C.UTF-8"),
    ("NO_COLOR", "1"),
    ("GIT_TERMINAL_PROMPT", "0"),
    ("GIT_CONFIG_NOSYSTEM", "1"),
    ("CI", "1"),
];
const LINUX_PATH: &str = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
const MACOS_PATH: &str = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";

fn invalid(message: &str) -> HostError {
    HostError::new("invalid_request", message)
}

/// A validated `run_command` proposal (`arguments.command`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct CommandProposal {
    /// Approval-bound operation id.
    pub(crate) operation_id: String,
    /// Program and arguments; `argv[0]` is resolved through the sandbox `PATH`.
    pub(crate) argv: Vec<String>,
    /// Root-relative working directory (`.` for the root).
    pub(crate) cwd: String,
    /// Wall-clock limit.
    pub(crate) timeout_ms: u64,
    /// Per-stream output cap as sent (`None`: [`DEFAULT_OUTPUT_BYTES`]).
    pub(crate) max_output_bytes: Option<u64>,
}

impl CommandProposal {
    fn output_cap(&self) -> usize {
        self.max_output_bytes
            .map_or(DEFAULT_OUTPUT_BYTES, |bytes| bytes as usize)
    }
}

fn operation_id_valid(value: &str) -> bool {
    (1..=128).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'-'))
}

fn cwd_valid(value: &str) -> bool {
    value == "."
        || (!value.is_empty()
            && value.len() <= 4096
            && !value.starts_with('/')
            && !value.contains('\\')
            && !value.chars().any(char::is_control)
            && value
                .split('/')
                .all(|part| !part.is_empty() && part != "." && part != ".."))
}

/// Validate `arguments.command`. Unknown keys are refused so a requester
/// cannot assume a field (network, credentials, env) the host ignores.
///
/// # Errors
/// `invalid_request` for any shape, size or range violation.
pub(crate) fn validate(value: &Value) -> HostResult<CommandProposal> {
    let object = value
        .as_object()
        .ok_or_else(|| invalid("command must be an object"))?;
    const ALLOWED: [&str; 5] = [
        "operation_id",
        "argv",
        "cwd",
        "timeout_ms",
        "max_output_bytes",
    ];
    if object.keys().any(|key| !ALLOWED.contains(&key.as_str())) {
        return Err(invalid("command has an unsupported field"));
    }
    let operation_id = object
        .get("operation_id")
        .and_then(Value::as_str)
        .filter(|id| operation_id_valid(id))
        .ok_or_else(|| invalid("command operation_id is invalid"))?
        .to_owned();
    let argv: Vec<String> = object
        .get("argv")
        .and_then(Value::as_array)
        .filter(|items| (1..=MAX_ARGUMENTS).contains(&items.len()))
        .ok_or_else(|| invalid("command argv is empty or too long"))?
        .iter()
        .map(|item| {
            item.as_str()
                .filter(|a| !a.is_empty() && a.len() <= MAX_ARGUMENT_BYTES && !a.contains('\0'))
                .map(str::to_owned)
                .ok_or_else(|| invalid("command argv has an invalid argument"))
        })
        .collect::<HostResult<_>>()?;
    // A leading dash would be read as a launcher option (`sandbox-exec` has
    // no `--` terminator).
    if argv[0].starts_with('-') {
        return Err(invalid("command program is invalid"));
    }
    let cwd = match object.get("cwd") {
        None => ".".to_owned(),
        Some(value) => value
            .as_str()
            .filter(|cwd| cwd_valid(cwd))
            .ok_or_else(|| invalid("command cwd must stay inside the root"))?
            .to_owned(),
    };
    let timeout_ms = object
        .get("timeout_ms")
        .and_then(Value::as_u64)
        .filter(|ms| (MIN_TIMEOUT_MS..=MAX_TIMEOUT_MS).contains(ms))
        .ok_or_else(|| invalid("command timeout_ms is out of range"))?;
    let max_output_bytes = match object.get("max_output_bytes") {
        None => None,
        Some(value) => Some(
            value
                .as_u64()
                .filter(|b| (MIN_OUTPUT_BYTES as u64..=MAX_OUTPUT_BYTES as u64).contains(b))
                .ok_or_else(|| invalid("command max_output_bytes is out of range"))?,
        ),
    };
    Ok(CommandProposal {
        operation_id,
        argv,
        cwd,
        timeout_ms,
        max_output_bytes,
    })
}

/// HMAC-SHA256(projectKey, JSON tuple) over the exact proposal, the same
/// construction as the file proposal digest with its own domain tag:
/// `["openmates-remote-command-proposal-v1", project_id, chat_id,
/// "run_command", operation_id, argv, cwd, timeout_ms, max_output_bytes|null]`.
/// The backend holds this digest from the user's approval; the host refuses
/// a request whose recomputed digest differs.
///
/// # Errors
/// `invalid_request` for an empty project or chat id.
pub(crate) fn digest(
    key: &[u8; 32],
    project_id: &str,
    chat_id: &str,
    proposal: &CommandProposal,
) -> HostResult<String> {
    if project_id.is_empty() || chat_id.is_empty() {
        return Err(invalid("command identity is incomplete"));
    }
    let message = json!([
        "openmates-remote-command-proposal-v1",
        project_id,
        chat_id,
        OPERATION,
        proposal.operation_id,
        proposal.argv,
        proposal.cwd,
        proposal.timeout_ms,
        proposal.max_output_bytes,
    ])
    .to_string();
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key)
        .map_err(|_| invalid("command identity is incomplete"))?;
    mac.update(message.as_bytes());
    Ok(mac
        .finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}

/// Removes the per-run Seatbelt scratch directory.
struct Scratch(Option<PathBuf>);

impl Drop for Scratch {
    fn drop(&mut self) {
        if let Some(path) = &self.0 {
            // Best effort: a leftover private temp directory holds only
            // command scratch output and is recreated per run.
            let _ = std::fs::remove_dir_all(path);
        }
    }
}

fn scratch_directory() -> HostResult<PathBuf> {
    use std::os::unix::fs::DirBuilderExt;
    let base = std::fs::canonicalize(std::env::temp_dir())
        .map_err(|e| HostError::new("launch_failed", format!("temp directory: {e}")))?;
    let path = base.join(format!("openmates-command-{}", uuid::Uuid::new_v4()));
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&path)
        .and_then(|()| {
            std::fs::DirBuilder::new()
                .mode(0o700)
                .create(path.join("home"))
        })
        .and_then(|()| {
            std::fs::DirBuilder::new()
                .mode(0o700)
                .create(path.join("tmp"))
        })
        .map_err(|e| HostError::new("launch_failed", format!("scratch directory: {e}")))?;
    Ok(path)
}

/// The launch command for one tier (pure apart from reading nothing: the
/// plan already holds every path).
///
/// # Errors
/// `confinement_unavailable` when a Seatbelt profile cannot quote a path.
pub(crate) fn launch_command(
    sandbox: &Sandbox,
    plan: &super::command_sandbox::ConfinementPlan,
    argv: &[String],
) -> HostResult<Command> {
    let mut command = Command::new(&sandbox.executable);
    command
        .env_clear()
        .envs(BASE_ENVIRONMENT)
        .current_dir(&plan.root);
    match sandbox.tier {
        SandboxTier::Bubblewrap | SandboxTier::BubblewrapAppArmor => {
            command
                .env("PATH", LINUX_PATH)
                .env("HOME", BWRAP_HOME)
                .env("TMPDIR", "/tmp")
                .args(bwrap_argv(plan, argv));
        }
        SandboxTier::Seatbelt => {
            let profile = seatbelt_profile(plan).map_err(|e| {
                HostError::new(
                    "confinement_unavailable",
                    format!("unquotable path {}", e.0.display()),
                )
            })?;
            command
                .env("PATH", MACOS_PATH)
                .env("HOME", plan.scratch.join("home"))
                .env("TMPDIR", plan.scratch.join("tmp"))
                .current_dir(&plan.cwd)
                .arg("-p")
                .arg(profile)
                .args(argv);
        }
    }
    Ok(command)
}

/// Run one validated proposal in `host`'s root, confined by `sandbox`.
/// Blocking: call it off the async worker.
///
/// # Errors
/// `invalid_path`/`protected_path` for a bad or private cwd,
/// `confinement_unavailable` when the plan cannot be built, `launch_failed`
/// when the launcher cannot start.
pub(crate) fn run(
    host: &HostRoot,
    proposal: &CommandProposal,
    sandbox: &Sandbox,
    worktree: bool,
) -> HostResult<Value> {
    let root = host.canonical()?;
    let cwd = if proposal.cwd == "." {
        root.clone()
    } else {
        let resolved = resolve_approved(&root, &proposal.cwd)?;
        let policy = host.policy(&root, &[proposal.cwd.as_str()], false)?;
        if policy.is_private(&proposal.cwd, true)? {
            return Err(HostError::protected("Command cwd is private"));
        }
        resolved
    };
    if !cwd.is_dir() {
        return Err(HostError::invalid_path("Command cwd is not a directory"));
    }
    let seatbelt = sandbox.tier == SandboxTier::Seatbelt;
    let scratch = Scratch(if seatbelt {
        Some(scratch_directory()?)
    } else {
        None
    });
    let plan = plan(
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
    )?;
    let command = launch_command(sandbox, &plan, &proposal.argv)?;
    let outcome = run_bounded(
        command,
        Duration::from_millis(proposal.timeout_ms),
        proposal.output_cap(),
    )
    .map_err(|e| HostError::new("launch_failed", format!("sandbox launch: {e}")))?;
    drop(scratch);
    Ok(result_json(&outcome, sandbox.tier, worktree, &root, &cwd))
}

/// The `run_command` success result. `exit_code` is `null` when a signal
/// ended the command (always after a timeout).
pub(crate) fn result_json(
    outcome: &ProcessOutcome,
    tier: SandboxTier,
    worktree: bool,
    root: &Path,
    cwd: &Path,
) -> Value {
    let relative_cwd = cwd
        .strip_prefix(root)
        .ok()
        .and_then(Path::to_str)
        .filter(|p| !p.is_empty())
        .unwrap_or(".");
    json!({
        "exit_code": outcome.exit_code,
        "signal": outcome.signal,
        "timed_out": outcome.timed_out,
        "duration_ms": u64::try_from(outcome.duration.as_millis()).unwrap_or(u64::MAX),
        "stdout": outcome.stdout.text(),
        "stderr": outcome.stderr.text(),
        "stdout_truncated": outcome.stdout.truncated(),
        "stderr_truncated": outcome.stderr.truncated(),
        "sandbox": tier.as_str(),
        "root": if worktree { "worktree" } else { "source" },
        "cwd": relative_cwd,
    })
}
