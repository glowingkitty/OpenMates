//! `projects commit` and `projects commits list|show|restore`: native Project
//! commits over the SDK. Encryption, snapshotting and restore planning live in
//! the Rust core; this file parses flags and formats output only.
use super::*;
use openmates_sdk::work::{ProjectCommit, ProjectCommitAuthor, ProjectCommitCreate};

fn contract(code: &'static str, message: impl Into<String>) -> CliError {
    CliError::Contract {
        code,
        message: message.into(),
    }
}
fn selector(i: &Invocation) -> Result<&str, CliError> {
    input::positional(i, 0, "Project")
}
fn commit_id(i: &Invocation) -> Result<&str, CliError> {
    input::positional(i, 1, "Commit ID")
}
fn author(i: &Invocation) -> Result<ProjectCommitAuthor, CliError> {
    match input::text(i, "author")? {
        None | Some("user") => Ok(ProjectCommitAuthor::User),
        Some("assistant") => Ok(ProjectCommitAuthor::Assistant),
        Some(_) => Err(contract(
            "invalid_author",
            "--author must be user or assistant.",
        )),
    }
}
fn number(i: &Invocation, flag: &str, default: u64, max: u64) -> Result<u64, CliError> {
    match input::text(i, flag)? {
        None => Ok(default),
        Some(raw) => raw
            .parse::<u64>()
            .ok()
            .filter(|value| *value <= max && (flag != "limit" || *value > 0))
            .ok_or_else(|| contract("invalid_limit", format!("--{flag} is out of range."))),
    }
}
fn present(commit: &ProjectCommit) -> Value {
    json!({
        "commit_id": commit.commit_id,
        "message": commit.message,
        "author": commit.author,
        "chat_id_hash": commit.chat_id_hash,
        "restored_from_commit_id": commit.restored_from_commit_id,
        "created_at": commit.created_at,
        "files": commit.files.iter().map(|f| json!({
            "target_id_hash": f.target_id_hash, "path": f.path, "embed_version": f.embed_version,
        })).collect::<Vec<_>>(),
    })
}
fn line(commit: &ProjectCommit) -> String {
    let author = match commit.author {
        ProjectCommitAuthor::User => "user",
        ProjectCommitAuthor::Assistant => "assistant",
    };
    let restored = commit
        .restored_from_commit_id
        .as_deref()
        .map(|id| format!("  (restore of {id})"))
        .unwrap_or_default();
    format!(
        "{}  {}  {}  {} file(s)  {}{restored}",
        commit.commit_id,
        commit.created_at,
        author,
        commit.files.len(),
        commit.message.lines().next().unwrap_or("")
    )
}

/// `projects commit <project> --message <text> [--author user|assistant] [--chat <id>]`
pub(super) async fn create(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    check(i, &["message", "author", "chat"])?;
    let message = input::text(i, "message")?
        .filter(|text| !text.trim().is_empty())
        .ok_or_else(|| contract("message_required", "Provide --message <text>."))?
        .to_owned();
    let commit = service
        .create_commit(
            selector(i)?,
            ProjectCommitCreate {
                message,
                author: author(i)?,
                chat_id: input::text(i, "chat")?.map(str::to_owned),
                files: vec![],
                commit_id: None,
                created_at: None,
            },
        )
        .await?;
    let text = format!("Committed: {}", line(&commit));
    output(i, json!({"commit": present(&commit)}), text)
}

pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    match i.command_path().as_str() {
        "projects commits list" => {
            check(i, &["limit", "cursor"])?;
            let page = service
                .list_commits(
                    selector(i)?,
                    number(i, "limit", 20, 100)? as u32,
                    number(i, "cursor", 0, u64::MAX)?,
                )
                .await?;
            let text = if page.commits.is_empty() {
                "No Project commits.".to_owned()
            } else {
                page.commits.iter().map(line).collect::<Vec<_>>().join("\n")
            };
            let value = json!({"commits": page.commits.iter().map(present).collect::<Vec<_>>(),
                "next_cursor": page.next_cursor});
            output(i, value, text)
        }
        "projects commits show" => {
            check(i, &[])?;
            let commit = service.show_commit(selector(i)?, commit_id(i)?).await?;
            let mut text = line(&commit);
            for file in &commit.files {
                text.push_str(&format!(
                    "\n  {}  v{}",
                    file.path.as_deref().unwrap_or(&file.target_id_hash),
                    file.embed_version
                ));
            }
            output(i, json!({"commit": present(&commit)}), text)
        }
        "projects commits restore" => restore(i, service).await,
        _ => Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "This Project commit command is not ported.".into(),
        }),
    }
}

/// Restore a whole commit: the core writes every changed file as a new
/// revision from `--chat` and records the restore commit. `--dry-run` only
/// prints the plan. An always-ask Project needs `--yes` as the user's grant.
async fn restore(i: &Invocation, service: &mut Projects<'_>) -> Result<CliOutput, CliError> {
    check(i, &["chat", "message", "yes", "dry-run"])?;
    if i.boolean("dry-run") {
        let plan = service
            .restore_commit_plan(selector(i)?, commit_id(i)?)
            .await?;
        let changed = plan.files.iter().filter(|file| !file.unchanged).count();
        let text = if changed == 0 {
            "Every file already matches this commit.".to_owned()
        } else {
            let mut lines = vec![format!(
                "Restoring would write {changed} new revision(s) (history is kept):"
            )];
            for file in plan.files.iter().filter(|file| !file.unchanged) {
                lines.push(format!(
                    "  {}  v{} -> new revision{}",
                    file.path.as_deref().unwrap_or(&file.target_id_hash),
                    file.restore_version,
                    if file.target_id.is_none() {
                        " (file no longer in the Project)"
                    } else {
                        ""
                    }
                ));
            }
            lines.join("\n")
        };
        return output(
            i,
            json!({"plan": plan, "applied": false, "changed_files": changed}),
            text,
        );
    }
    let chat = input::text(i, "chat")?.ok_or_else(|| {
        contract(
            "chat_required",
            "Provide --chat <chat-id> whose focus is this Project, or --dry-run.",
        )
    })?;
    let yes = i.boolean("yes");
    let mut approve = move |_: &openmates_sdk::work::HostedFileMutation| {
        Ok::<bool, openmates_sdk::work::HostedFileError>(yes)
    };
    let result = service
        .restore_commit(
            selector(i)?,
            commit_id(i)?,
            chat,
            input::text(i, "message")?,
            &mut approve,
        )
        .await
        .map_err(super::hosted::hosted_error)?;
    let text = format!(
        "Restored {} file(s); recorded {}",
        result.written.len(),
        line(&result.commit)
    );
    output(
        i,
        json!({"plan": result.plan, "applied": true, "written": result.written,
            "commit": present(&result.commit)}),
        text,
    )
}
