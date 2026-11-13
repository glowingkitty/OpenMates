//! `projects remote run|git status|git commit|git land`: thin argument parsing
//! and formatting over the shared core requester (`Projects::run_remote_command`,
//! `git_status`, `git_commit`, `git_land`). Approval digests, the sealed relay
//! envelope and host validation live in the core and on the source host.
use super::*;
use openmates_sdk::work::{
    GitCommitResult, GitLandOutcome, GitStatusResult, RemoteCommand, RemoteCommandResult,
    RemoteOpCode, RemoteOpError,
};

/// Exit code for a host or relay refusal (the command never ran).
const EXIT_REFUSED: u8 = 125;
/// Exit code when the command was stopped by the host's time limit.
const EXIT_TIMED_OUT: u8 = 124;
const DEFAULT_TIMEOUT_MS: u64 = 120_000;
const FLAGS: &[&str] = &["source", "chat", "cwd", "timeout-ms", "message"];

pub(super) fn contract(code: &'static str, message: impl Into<String>) -> CliError {
    CliError::Contract {
        code,
        message: message.into(),
    }
}
/// Stable wire spelling of a host refusal code.
pub(super) fn code_name(code: &RemoteOpCode) -> &'static str {
    match code {
        RemoteOpCode::InvalidRequest => "invalid_request",
        RemoteOpCode::NoWorktree => "no_worktree",
        RemoteOpCode::ConfinementUnavailable => "confinement_unavailable",
        RemoteOpCode::LaunchFailed => "launch_failed",
        RemoteOpCode::OperationFailed => "operation_failed",
        RemoteOpCode::NothingToCommit => "nothing_to_commit",
        RemoteOpCode::IdentityMissing => "identity_missing",
        RemoteOpCode::WorktreeDirty => "worktree_dirty",
        RemoteOpCode::TargetBranchUnavailable => "target_branch_unavailable",
        RemoteOpCode::TargetCheckedOutDirty => "target_checked_out_dirty",
        RemoteOpCode::LandFailed => "land_failed",
        RemoteOpCode::WriteAuthorizationDenied => "write_authorization_denied",
        RemoteOpCode::SourceCapabilityDenied => "source_capability_denied",
        RemoteOpCode::SourceOffline => "source_offline",
        RemoteOpCode::ProtocolTimeout => "protocol_timeout",
        RemoteOpCode::SourceSessionChanged => "source_session_changed",
        RemoteOpCode::SourceNotFound => "source_not_found",
        RemoteOpCode::SourceSelectionRequired => "source_selection_required",
        RemoteOpCode::CreationNotConfigured => "creation_not_configured",
        RemoteOpCode::InvalidProjectName => "invalid_project_name",
        RemoteOpCode::CreationFolderUnavailable => "creation_folder_unavailable",
        RemoteOpCode::TargetExists => "target_exists",
        RemoteOpCode::CreationCompletionFailed => "creation_completion_failed",
        RemoteOpCode::Other(_) => "remote_operation_error",
    }
}
pub(super) fn refusal_output(json: bool, code: &str, message: &str) -> Result<CliOutput, CliError> {
    let mut out = if json {
        CliOutput::json(&json!({"error":{"code":code,"message":message}}))?
    } else {
        CliOutput {
            stdout: String::new(),
            stderr: format!("{code}: {message}\n"),
            exit_code: 0,
        }
    };
    out.exit_code = EXIT_REFUSED;
    Ok(out)
}
/// A host refusal is a value for the caller (stable code, exit 125); a core
/// error keeps the normal CLI error path.
pub(super) fn refusal(i: &Invocation, error: RemoteOpError) -> Result<CliOutput, CliError> {
    match error {
        RemoteOpError::Core(error) => Err(CliError::Client(error)),
        RemoteOpError::Host { code, message } => {
            refusal_output(i.boolean("json"), code_name(&code), &message)
        }
    }
}
pub(super) fn operation_id() -> String {
    format!("cli-{}", uuid::Uuid::new_v4().simple())
}
fn number(i: &Invocation, name: &'static str, default: u64) -> Result<u64, CliError> {
    match i.text(name) {
        None => Ok(default),
        Some(raw) if !raw.is_empty() && raw.bytes().all(|b| b.is_ascii_digit()) => raw
            .parse()
            .map_err(|_| contract("invalid_limit", format!("--{name} must be an integer."))),
        Some(_) => Err(contract(
            "invalid_limit",
            format!("--{name} must be an integer."),
        )),
    }
}
pub(super) fn short(sha: &str) -> &str {
    sha.get(..12).unwrap_or(sha)
}

fn run_exit_code(result: &RemoteCommandResult) -> u8 {
    match (result.exit_code, result.signal) {
        (Some(code), _) => u8::try_from(code.clamp(0, 255)).unwrap_or(1),
        (None, _) if result.timed_out => EXIT_TIMED_OUT,
        (None, Some(signal)) => u8::try_from((128 + signal).clamp(1, 255)).unwrap_or(1),
        (None, None) => 1,
    }
}
fn run_summary(result: &RemoteCommandResult) -> String {
    let status = match (result.exit_code, result.signal) {
        (Some(code), _) => format!("exit {code}"),
        (None, _) if result.timed_out => "timed out".to_owned(),
        (None, Some(signal)) => format!("signal {signal}"),
        (None, None) => "no exit status".to_owned(),
    };
    let truncated = match (result.stdout_truncated, result.stderr_truncated) {
        (false, false) => "output complete",
        (true, false) => "stdout truncated",
        (false, true) => "stderr truncated",
        (true, true) => "stdout and stderr truncated",
    };
    format!(
        "{status} in {} ms, sandbox {}, {truncated}",
        result.duration_ms, result.sandbox
    )
}
fn run_output(i: &Invocation, result: &RemoteCommandResult) -> Result<CliOutput, CliError> {
    let exit_code = run_exit_code(result);
    if i.boolean("json") {
        let mut out = CliOutput::json(&serde_json::to_value(result).map_err(|_| Error::Protocol)?)?;
        out.exit_code = exit_code;
        return Ok(out);
    }
    let mut stdout = super::super::terminal_text(&result.stdout);
    let mut stderr = super::super::terminal_text(&result.stderr);
    for stream in [&mut stdout, &mut stderr] {
        if !stream.is_empty() && !stream.ends_with('\n') {
            stream.push('\n');
        }
    }
    stderr.push_str(&run_summary(result));
    stderr.push('\n');
    Ok(CliOutput {
        stdout,
        stderr,
        exit_code,
    })
}
fn status_text(status: &GitStatusResult) -> String {
    if !status.exists {
        return "No chat worktree yet.".into();
    }
    let mut lines = vec![format!(
        "head {}  target {}  ahead {}  {}{}",
        status.head.as_deref().map_or("-", short),
        status.target_branch.as_deref().unwrap_or("-"),
        status.ahead,
        if status.dirty { "dirty" } else { "clean" },
        if status.landed { "  landed" } else { "" },
    )];
    lines.extend(
        status
            .changed_files
            .iter()
            .map(|file| format!("{}  {}", file.status, file.path)),
    );
    if status.truncated {
        lines.push("(file list truncated)".into());
    }
    lines.join("\n")
}
fn commit_text(commit: &GitCommitResult) -> String {
    format!(
        "Committed {} ({} ahead of {}).",
        short(&commit.commit),
        commit.ahead,
        commit.target_branch
    )
}
fn land_output(i: &Invocation, outcome: &GitLandOutcome) -> Result<CliOutput, CliError> {
    let value = serde_json::to_value(outcome).map_err(|_| Error::Protocol)?;
    let (text, exit_code) = match outcome {
        GitLandOutcome::Landed {
            commit,
            commits,
            target_branch,
            checked_out,
            ..
        } => (
            format!(
                "Landed {commits} commit(s) on {target_branch} at {}{}.",
                short(commit),
                if *checked_out {
                    " (checked-out branch updated)"
                } else {
                    ""
                }
            ),
            0,
        ),
        GitLandOutcome::Conflict {
            conflicting_paths, ..
        } => (
            format!(
                "Land conflict in {} path(s):\n{}",
                conflicting_paths.len(),
                conflicting_paths
                    .iter()
                    .map(|path| format!("  {path}"))
                    .collect::<Vec<_>>()
                    .join("\n")
            ),
            1,
        ),
    };
    let mut out = if i.boolean("json") {
        CliOutput::json(&value)?
    } else {
        CliOutput::text(text)
    };
    out.exit_code = exit_code;
    Ok(out)
}
/// Validated, network-free view of one invocation.
struct Request<'a> {
    action: &'a str,
    project: &'a str,
    chat: &'a str,
    source: Option<&'a str>,
}
fn request<'a>(i: &'a Invocation, action: &'a str) -> Result<Request<'a>, CliError> {
    check(i, FLAGS)?;
    if !i.boolean("personal") && !i.has("team") {
        return Err(contract(
            "context_confirmation_required",
            "Remote operations require --personal or --team <team>.",
        ));
    }
    let project = i
        .positionals
        .first()
        .map(|v| v.trim())
        .filter(|v| !v.is_empty())
        .ok_or_else(|| contract("command_failed", "Missing project."))?;
    let chat = i
        .text("chat")
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| contract("command_failed", "Missing --chat <chat-id>."))?;
    if action != "run" && (i.has("cwd") || i.has("timeout-ms")) {
        return Err(contract(
            "command_failed",
            "--cwd and --timeout-ms apply only to 'projects remote run'.",
        ));
    }
    if action != "git commit" && i.has("message") {
        return Err(contract(
            "command_failed",
            "--message applies only to 'projects remote git commit'.",
        ));
    }
    Ok(Request {
        action,
        project,
        chat,
        source: i.text("source"),
    })
}
fn command(i: &Invocation) -> Result<RemoteCommand, CliError> {
    let argv = i.positionals.get(1..).unwrap_or_default().to_vec();
    if argv.is_empty() {
        return Err(contract(
            "command_failed",
            "Missing command. Use: projects remote run <project> --chat <id> -- <program> [args...]",
        ));
    }
    Ok(RemoteCommand {
        argv,
        cwd: i.text("cwd").map(str::to_owned),
        timeout_ms: number(i, "timeout-ms", DEFAULT_TIMEOUT_MS)?,
        max_output_bytes: None,
    })
}

pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    if matches!(
        i.command_path().as_str(),
        "projects remote hosts" | "projects remote create"
    ) {
        return super::remote_create::execute(i, service).await;
    }
    let path = i.command_path();
    let action = path.trim_start_matches("projects remote ");
    let req = request(i, action)?;
    let (project, chat, source) = (req.project, req.chat, req.source);
    match req.action {
        "run" => {
            let command = command(i)?;
            match service
                .run_remote_command(project, source, chat, &operation_id(), &command)
                .await
            {
                Ok(result) => run_output(i, &result),
                Err(error) => refusal(i, error),
            }
        }
        "git status" => match service.git_status(project, source, chat).await {
            Ok(status) => output(
                i,
                serde_json::to_value(&status).map_err(|_| Error::Protocol)?,
                status_text(&status),
            ),
            Err(error) => refusal(i, error),
        },
        "git commit" => {
            let message = i
                .text("message")
                .filter(|m| !m.trim().is_empty())
                .ok_or_else(|| contract("command_failed", "Missing --message <text>."))?;
            match service
                .git_commit(project, source, chat, &operation_id(), message)
                .await
            {
                Ok(commit) => output(
                    i,
                    serde_json::to_value(&commit).map_err(|_| Error::Protocol)?,
                    commit_text(&commit),
                ),
                Err(error) => refusal(i, error),
            }
        }
        "git land" => match service
            .git_land(project, source, chat, &operation_id())
            .await
        {
            Ok(outcome) => land_output(i, &outcome),
            Err(error) => refusal(i, error),
        },
        _ => Err(contract(
            "unknown_projects_remote_command",
            "Use 'projects remote run' or 'projects remote git status|commit|land'.",
        )),
    }
}

#[cfg(test)]
#[path = "remote_ops_tests.rs"]
mod tests;
