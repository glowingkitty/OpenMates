//! `projects files list|search|read` over the SDK requester side of the
//! encrypted Project source protocol (npm handleProjectFiles). The relay sees
//! only ciphertext; the selected source must be online.
use super::*;
use openmates_sdk::work::{ProjectFileOperation, ProjectRequesterError, safe_relative_path};

fn contract(code: &'static str, message: impl Into<String>) -> CliError {
    CliError::Contract {
        code,
        message: message.into(),
    }
}
/// Keep npm's contract codes; unknown host codes share one stable code.
fn requester_error(error: ProjectRequesterError) -> CliError {
    match error {
        ProjectRequesterError::Core(error) => CliError::Client(error),
        ProjectRequesterError::Remote { code, message } => {
            const KNOWN: &[&str] = &[
                "source_offline",
                "source_not_found",
                "source_selection_required",
                "source_capability_denied",
                "source_session_changed",
                "protocol_timeout",
                "invalid_encrypted_result",
                "invalid_remote_payload",
                "result_too_large",
                "routing_identity_unavailable",
                "routing_identity_invalid",
                "invalid_path",
                "query_too_large",
                "protected_path",
                "unsupported_file",
                "search_query_required",
                "operation_failed",
                "ignored_path_requires_approval",
            ];
            let code = KNOWN
                .iter()
                .copied()
                .find(|known| *known == code)
                .unwrap_or("project_source_error");
            contract(code, message)
        }
    }
}
fn depth(i: &Invocation) -> Result<u32, CliError> {
    match i.text("depth") {
        None => Ok(1),
        Some(raw) if raw.bytes().all(|b| b.is_ascii_digit()) && !raw.is_empty() => {
            let value: u32 = raw
                .parse()
                .map_err(|_| contract("invalid_limit", "--depth must be an integer."))?;
            if (1..=8).contains(&value) {
                Ok(value)
            } else {
                Err(contract(
                    "invalid_limit",
                    "--depth must be between 1 and 8.",
                ))
            }
        }
        Some(_) => Err(contract("invalid_limit", "--depth must be an integer.")),
    }
}

pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    let action = i.path.last().map(String::as_str).unwrap_or("");
    check(
        i,
        &[
            "source",
            "path",
            "depth",
            "include-ignored",
            "include-content",
        ],
    )?;
    if i.boolean("include-ignored") && action != "read" {
        return Err(contract(
            "include_ignored_read_only",
            "--include-ignored is allowed only for one exact file read.",
        ));
    }
    if i.boolean("include-content") && action != "search" {
        return Err(contract(
            "include_content_search_only",
            "--include-content is allowed only for filename search.",
        ));
    }
    if !i.boolean("personal") && !i.has("team") {
        return Err(contract(
            "context_confirmation_required",
            "Live file requests require --personal or --team <team>.",
        ));
    }
    if i.boolean("include-ignored") {
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "Approved reads of ignored files are not ported.".into(),
        });
    }
    let positional = |index: usize, label: &str| {
        i.positionals
            .get(index)
            .map(|v| v.trim())
            .filter(|v| !v.is_empty())
            .ok_or_else(|| contract("command_failed", format!("Missing {label}.")))
    };
    let project = positional(0, "project")?;
    let operation = match action {
        "list" => ProjectFileOperation::List {
            path: safe_relative_path(i.text("path").unwrap_or(".")).map_err(requester_error)?,
            depth: depth(i)?,
        },
        "search" => {
            let query = positional(1, "search query")?;
            if query.len() > 256 {
                return Err(contract(
                    "query_too_large",
                    "Search query exceeds 256 bytes.",
                ));
            }
            ProjectFileOperation::Search {
                query: query.into(),
                include_content: i.boolean("include-content"),
            }
        }
        "read" => ProjectFileOperation::ReadText {
            path: safe_relative_path(positional(1, "relative path")?).map_err(requester_error)?,
        },
        _ => {
            return Err(contract(
                "unknown_projects_files_command",
                "Use 'projects files list', 'search', or 'read'.",
            ));
        }
    };
    let value = service
        .source_file_operation(project, i.text("source"), operation)
        .await
        .map_err(requester_error)?;
    if i.boolean("json") {
        return CliOutput::json(
            &json!({"project_id":value["project_id"],"source_id":value["source_id"],
            "operation":action,"result":value["result"]}),
        );
    }
    let result = &value["result"];
    if action == "read"
        && let Some(content) = result["content"].as_str()
    {
        let mut stdout = content.to_owned();
        if !stdout.ends_with('\n') {
            stdout.push('\n');
        }
        return Ok(CliOutput {
            stdout,
            stderr: String::new(),
            exit_code: 0,
        });
    }
    CliOutput::json(result)
}

#[cfg(test)]
#[path = "files_tests.rs"]
mod tests;
