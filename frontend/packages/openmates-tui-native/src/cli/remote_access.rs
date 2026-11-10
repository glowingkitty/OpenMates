//! `openmates remote-access`: thin CLI shell over the core filesystem host
//! (`openmates_sdk::source_host`). Mirrors npm `handleRemoteAccess` in
//! `openmates-cli/src/cli.ts`: flag checks, Personal/Team confirmation, Project
//! and write-policy prompts, takeover confirmation and lifecycle output. Root
//! discovery, attachment, the local store and the host loop live in the core.
//! Not yet in the Rust host: `--enable-commands` and `--task-cache` (explicit errors).
use super::{CliError, CliOutput, Invocation};
use crate::client::Client;
use crate::error::Error;
use openmates_sdk::source_host::{
    AttachContext, AttachError, CredentialSync, ProjectChoice, SourceHostEvent, SourceHostRun, attach_root,
    hosting_candidates, npm_state_dir, prepare_source, resolve_roots, run_source_host,
    selectable_projects, stored_attachments,
};
use openmates_sdk::work::ProjectWriteMode;
use serde_json::json;
use std::io::IsTerminal;
use std::path::PathBuf;
use tokio_util::sync::CancellationToken;

const FLAGS: &[&str] = &[
    "path",
    "project",
    "write-policy",
    "task-cache",
    "enable-commands",
    "personal",
    "team",
    "team-id",
    "json",
    "profile",
    "api-url",
    "api-key",
    "help",
];
const INTERNAL_FLAGS: &[&str] = &[
    "source-id",
    "type",
    "local-only",
    "encrypted-display-name",
    "encrypted-metadata",
];

/// True for the `remote-access` command.
pub(super) fn supported(i: &Invocation) -> bool {
    i.command_path() == "remote-access"
}

fn contract(code: &'static str, message: impl Into<String>) -> CliError {
    CliError::Contract {
        code,
        message: message.into(),
    }
}

/// Checks that need no credentials (npm `assertRemoteAccessPublicFlags` plus
/// the Rust host's explicit gaps), run before the session is opened.
pub(super) fn preflight(i: &Invocation) -> Option<Result<CliOutput, CliError>> {
    if !supported(i) {
        return None;
    }
    check(i).err().map(Err)
}

fn check(i: &Invocation) -> Result<(), CliError> {
    if !i.positionals.is_empty() {
        return Err(CliError::Invalid(
            "openmates remote-access uses --path <folder>; positional paths are not supported.".into(),
        ));
    }
    let internal: Vec<String> = INTERNAL_FLAGS
        .iter()
        .filter(|f| i.has(f))
        .map(|f| format!("--{f}"))
        .collect();
    if !internal.is_empty() {
        return Err(CliError::Invalid(format!(
            "Unsupported remote-access option{}: {}",
            if internal.len() == 1 { "" } else { "s" },
            internal.join(", ")
        )));
    }
    if let Some(unknown) = i.flags.keys().find(|k| !FLAGS.contains(&k.as_str())) {
        return Err(CliError::Invalid(format!("Unknown option --{unknown} for remote-access.")));
    }
    if i.has("enable-commands") {
        if !i.boolean("enable-commands") {
            return Err(contract("invalid_enable_commands", "--enable-commands does not accept a value."));
        }
        return Err(contract(
            "remote_commands_unsupported",
            "--enable-commands is not yet supported in the Rust host. Remote access without commands works; the npm CLI remains available for command execution.",
        ));
    }
    if i.has("task-cache") {
        return Err(contract(
            "task_cache_unsupported",
            "--task-cache is not yet supported in the Rust host; Project Task sync stays with the npm CLI for now.",
        ));
    }
    if i.has("write-policy") {
        write_policy(i)?;
    }
    Ok(())
}

fn interactive(i: &Invocation) -> bool {
    !i.boolean("json") && std::io::stdin().is_terminal() && std::io::stdout().is_terminal()
}

fn write_policy(i: &Invocation) -> Result<Option<ProjectWriteMode>, CliError> {
    match i.flags.get("write-policy") {
        None => Ok(None),
        Some(value) => match value.as_str() {
            Some("apply_and_show") => Ok(Some(ProjectWriteMode::ApplyAndShow)),
            Some("always_ask") => Ok(Some(ProjectWriteMode::AlwaysAsk)),
            Some(_) => Err(contract("invalid_write_policy", "--write-policy must be apply_and_show or always_ask.")),
            None => Err(contract("invalid_write_policy", "--write-policy requires apply_and_show or always_ask.")),
        },
    }
}

/// npm promptLine (question on stdout, one stdin line).
async fn prompt(question: &str) -> Result<String, CliError> {
    use std::io::Write;
    let mut stdout = std::io::stdout();
    write!(stdout, "{question}")
        .and_then(|()| stdout.flush())
        .map_err(|_| CliError::Client(Error::Io))?;
    let line = tokio::task::spawn_blocking(|| {
        let mut line = String::new();
        std::io::stdin().read_line(&mut line).map(|_| line)
    })
    .await
    .map_err(|_| CliError::Client(Error::Io))?
    .map_err(|_| CliError::Client(Error::Io))?;
    Ok(line.trim().to_owned())
}

fn attach_error(error: AttachError) -> CliError {
    match error {
        AttachError::Local(error) => CliError::Invalid(error.message),
        AttachError::Client(error) => CliError::Client(error),
    }
}

/// npm `resolveRemoteAccessHostingContext`: explicit `--personal`/`--team`,
/// else an interactive confirmation of the active context.
async fn hosting_team(i: &Invocation, client: &Client) -> Result<Option<String>, CliError> {
    let team = i.text("team").or(i.text("team-id")).map(str::to_owned);
    if i.boolean("personal") && team.is_some() {
        return Err(CliError::Invalid("Choose --personal or --team, not both.".into()));
    }
    if i.boolean("personal") {
        return Ok(None);
    }
    if team.is_some() {
        return Ok(team);
    }
    if !interactive(i) {
        return Err(contract(
            "context_confirmation_required",
            "Remote access hosting requires --personal or --team <team> in non-interactive mode.",
        ));
    }
    let active = client.session().and_then(|s| s.active_team_id.clone());
    let label = active.as_ref().map_or_else(|| "Personal".to_owned(), |t| format!("Team {t}"));
    let answer = prompt(&format!("Host Project sources in {label}? [Y/n/change] ")).await?.to_lowercase();
    match answer.as_str() {
        "" | "y" | "yes" => Ok(active),
        "n" | "no" | "cancel" => Err(contract(
            "context_confirmation_cancelled",
            "Remote access context confirmation cancelled.",
        )),
        _ => {
            let selected = prompt("Enter 'personal' or a Team ID: ").await?;
            Ok((!selected.eq_ignore_ascii_case("personal")).then_some(selected))
        }
    }
}

async fn choose_write_mode(i: &Invocation, root: &str) -> Result<ProjectWriteMode, CliError> {
    if let Some(mode) = write_policy(i)? {
        return Ok(mode);
    }
    if !interactive(i) {
        return Err(contract(
            "write_policy_required",
            "This operation requires --write-policy apply_and_show|always_ask in non-interactive mode.",
        ));
    }
    println!("Choose how OpenMates may change files in {}:", json!(root));
    println!("  1. Apply and show changes (recommended)");
    println!("  2. Always ask before writes");
    match prompt("Write policy (1 or 2): ").await?.to_lowercase().as_str() {
        "1" | "apply_and_show" => Ok(ProjectWriteMode::ApplyAndShow),
        "2" | "always_ask" => Ok(ProjectWriteMode::AlwaysAsk),
        _ => Err(contract(
            "write_policy_selection_cancelled",
            "A write policy must be selected; no Project setting was changed.",
        )),
    }
}

async fn choose_project(
    i: &Invocation,
    client: &mut Client,
    context: &AttachContext,
    root: &str,
) -> Result<ProjectChoice, CliError> {
    let mut answer = i.text("project").map(|p| p.trim().to_owned()).unwrap_or_default();
    let available = selectable_projects(client, context).await.map_err(attach_error)?;
    if answer.is_empty() {
        println!("Choose the OpenMates Project for {root}:");
        for (index, (id, name)) in available.iter().enumerate() {
            println!("  {}. {} ({id})", index + 1, json!(name));
        }
        println!("  new. Create a new Project");
        answer = prompt("Project number, 'new', or Enter to cancel: ").await?;
    }
    if answer.eq_ignore_ascii_case("new") {
        return Ok(ProjectChoice::New);
    }
    if answer.is_empty() {
        return Err(CliError::Invalid(
            "Remote access Project selection cancelled or invalid; no Project was created.".into(),
        ));
    }
    let numbered = answer
        .parse::<usize>()
        .ok()
        .filter(|n| !answer.starts_with('0') && *n >= 1)
        .and_then(|n| available.get(n - 1));
    Ok(ProjectChoice::Existing(numbered.map_or(answer.clone(), |(id, _)| id.clone())))
}

fn state_dir(i: &Invocation) -> Result<PathBuf, CliError> {
    let profile = i
        .text("profile")
        .map(str::to_owned)
        .or_else(|| std::env::var("OPENMATES_PROFILE").ok());
    let home = std::env::var_os("HOME").filter(|h| !h.is_empty()).map(PathBuf::from);
    npm_state_dir(
        std::env::var("OPENMATES_STATE_DIR").ok().as_deref(),
        profile.as_deref(),
        home.as_deref(),
    )
    .map_err(|e| CliError::Invalid(e.message))
}

fn lifecycle(json_output: bool, event: &SourceHostEvent) {
    let value = match event {
        SourceHostEvent::Connecting { attempt } => json!({"state": "connecting", "attempt": attempt}),
        SourceHostEvent::Connected => json!({"state": "connected"}),
        SourceHostEvent::Reconnecting { attempt, delay_ms } => {
            json!({"state": "reconnecting", "attempt": attempt, "delayMs": delay_ms})
        }
        SourceHostEvent::Disconnected => json!({"state": "disconnected"}),
        SourceHostEvent::Request { summary } => {
            if json_output {
                println!("{}", json!({"type": "remote_access_request", "summary": summary}));
            }
            return;
        }
    };
    if json_output {
        let mut line = json!({"type": "remote_access_lifecycle"});
        if let (Some(target), Some(source)) = (line.as_object_mut(), value.as_object()) {
            target.extend(source.clone());
        }
        println!("{line}");
        return;
    }
    match event {
        SourceHostEvent::Connected => println!("Remote access connected."),
        SourceHostEvent::Reconnecting { delay_ms, .. } => println!("Remote access reconnecting in {delay_ms}ms."),
        SourceHostEvent::Disconnected => println!("Remote access disconnected."),
        _ => {}
    }
}

/// Attach the approved folders and host them until cancelled.
pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    store: Option<&crate::runtime_store::RuntimeStore>,
) -> Result<CliOutput, CliError> {
    check(i)?;
    let json_output = i.boolean("json");
    let state_dir = state_dir(i)?;
    let team_id = hosting_team(i, client).await?;
    let paths: Vec<String> = i
        .values("path")
        .iter()
        .flat_map(|value| value.split('\n'))
        .map(str::to_owned)
        .collect();
    let cwd = std::env::current_dir().map_err(|_| CliError::Client(Error::Io))?;
    let roots = resolve_roots(&paths, &cwd, &state_dir).map_err(|e| CliError::Invalid(e.message))?;
    let discovery = hosting_candidates(&roots, !paths.is_empty()).map_err(|e| CliError::Invalid(e.message))?;
    let context = AttachContext { team_id, state_dir: state_dir.clone() };
    let (mut attachments, unresolved) =
        stored_attachments(client, &context, &discovery.roots).await.map_err(attach_error)?;
    if !unresolved.is_empty() && !interactive(i) {
        if !i.has("write-policy") {
            return Err(contract(
                "write_policy_required",
                "Adding a Project folder requires --write-policy apply_and_show|always_ask in non-interactive mode.",
            ));
        }
        if i.text("project").is_none() {
            return Err(contract(
                "project_selection_required",
                "Adding a Project folder requires --project <slug|id|new> in non-interactive mode.",
            ));
        }
    }
    for root in unresolved {
        let label = root.to_string_lossy().into_owned();
        let choice = choose_project(i, client, &context, &label).await?;
        let mode = choose_write_mode(i, &label).await?;
        attachments.push(attach_root(client, &context, &root, &choice, mode).await.map_err(attach_error)?);
    }
    if attachments.is_empty() {
        return Err(CliError::Invalid("No Project folders were approved for remote access.".into()));
    }
    let mut sources = Vec::with_capacity(attachments.len());
    for attachment in &attachments {
        sources.push(prepare_source(client, &context, attachment).await.map_err(attach_error)?);
    }
    if !json_output {
        let count = sources.len();
        println!("Remote access connecting {count} Project source{}.", if count == 1 { "" } else { "s" });
        println!("Keep this terminal open. For long-running work, start it inside zellij, tmux, or screen.");
        let denied = discovery.permission_denied.len();
        if denied > 0 {
            eprintln!("Skipped {denied} unreadable folder{}.", if denied == 1 { "" } else { "s" });
        }
    }
    // The host runs for hours: other `openmates` commands on this state
    // directory must keep working, so only individual store operations lock it.
    if let Some(store) = store {
        store.scope_runtime_lock_to_operations().map_err(CliError::Client)?;
    }
    // Another command may rotate and store the session while the host runs:
    // adopt it before reconnecting, and never overwrite it on exit.
    let credential_sync = store.cloned().map(|store| {
        CredentialSync(std::sync::Arc::new(move || {
            let store = store.clone();
            Box::pin(async move { store.load_superseded(None).await })
        }))
    });
    let source_session_id = uuid::Uuid::new_v4().to_string();
    let mut confirmed_takeover = false;
    loop {
        let run = SourceHostRun {
            sources: sources.clone(),
            source_session_id: source_session_id.clone(),
            confirmed_takeover,
            state_dir: state_dir.clone(),
            credential_sync: credential_sync.clone(),
        };
        let mut on_event = |event: SourceHostEvent| lifecycle(json_output, &event);
        match run_source_host(client, run, cancel.clone(), &mut on_event).await {
            Ok(()) => return Ok(CliOutput::text(String::new())),
            Err(Error::Conflict) if !confirmed_takeover => {
                if !interactive(i) {
                    return Err(CliError::Invalid(
                        "Another remote-access process owns one of these sources; rerun interactively to confirm takeover.".into(),
                    ));
                }
                let answer = prompt("Another process owns one of these sources. Take over? [y/N] ").await?.to_lowercase();
                if answer != "y" && answer != "yes" {
                    return Err(CliError::Invalid("Remote access takeover cancelled.".into()));
                }
                confirmed_takeover = true;
            }
            Err(error) => return Err(CliError::Client(error)),
        }
    }
}

#[cfg(test)]
#[path = "remote_access_tests.rs"]
mod remote_access_tests;
