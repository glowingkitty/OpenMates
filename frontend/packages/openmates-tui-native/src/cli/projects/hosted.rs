//! `projects hosted list|read|create|update`: OpenMates-stored Project files
//! through the core hosted writer (`work::projects::hosted`). Parse, call the
//! core, render; the policy, encryption and revision commit live in the core.
//! Writes come from `--chat` (its active focus must be this Project); an
//! always-ask Project needs `--yes` as the user's grant for this exact write.
use super::*;
use openmates_sdk::work::{HostedFileError, HostedFileMutation};

const MAX_INPUT_BYTES: u64 = 200 * 1024;

/// Executor refusals keep the core's stable code; a server rejection keeps
/// its filtered code in the message under the stable `commit_rejected`.
pub(super) fn hosted_error(error: HostedFileError) -> CliError {
    match error {
        HostedFileError::Core(error) => CliError::Client(error),
        HostedFileError::Refused(code) => CliError::Contract {
            code,
            message: match code {
                "project_focus_required" => "Activate this Project's focus in --chat first.".into(),
                "write_policy_required" => "Choose the Project's write policy first.".into(),
                "write_approval_required" => {
                    "This Project asks before every write; rerun with --yes to approve it.".into()
                }
                "stale_base" => "The file changed since the patch's base; read it again.".into(),
                _ => format!("Hosted Project file operation refused: {code}."),
            },
        },
        HostedFileError::Rejected(code) => CliError::Contract {
            code: "commit_rejected",
            message: format!("The server rejected the revision: {code}."),
        },
    }
}

fn selector(i: &Invocation) -> Result<&str, CliError> {
    input::positional(i, 0, "Project")
}

fn path(i: &Invocation) -> Result<&str, CliError> {
    input::positional(i, 1, "Project file path")
}

fn chat(i: &Invocation) -> Result<&str, CliError> {
    input::text(i, "chat")?.ok_or_else(|| CliError::Contract {
        code: "chat_required",
        message: "Provide --chat <chat-id> whose focus is this Project.".into(),
    })
}

/// Exactly one of `--text <value>` or `--file <local-path>` (at most 200 KB).
fn body(i: &Invocation, what: &str) -> Result<String, CliError> {
    match (input::text(i, "text")?, input::text(i, "file")?) {
        (Some(text), None) => Ok(text.to_owned()),
        (None, Some(file)) => {
            let size = std::fs::metadata(file)
                .map_err(|_| CliError::Invalid(format!("Cannot read {what} file {file}.")))?
                .len();
            if size > MAX_INPUT_BYTES {
                return Err(CliError::Contract {
                    code: "file_mutation_too_large",
                    message: format!("The {what} is larger than 200 KB."),
                });
            }
            std::fs::read_to_string(file).map_err(|_| {
                CliError::Invalid(format!("The {what} file {file} is not UTF-8 text."))
            })
        }
        _ => Err(CliError::Invalid(format!(
            "Provide the {what} with exactly one of --text or --file."
        ))),
    }
}

fn approval(
    i: &Invocation,
) -> impl FnMut(&HostedFileMutation) -> Result<bool, HostedFileError> + '_ {
    move |_| Ok(i.boolean("yes"))
}

pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    match i.command_path().as_str() {
        "projects hosted list" => {
            check(i, &["path"])?;
            let value = service
                .hosted_files_list(selector(i)?, input::text(i, "path")?)
                .await
                .map_err(hosted_error)?;
            let text = value["entries"]
                .as_array()
                .map(|rows| {
                    rows.iter()
                        .filter_map(|row| row["path"].as_str())
                        .collect::<Vec<_>>()
                        .join("\n")
                })
                .filter(|text| !text.is_empty())
                .unwrap_or_else(|| "No hosted Project files.".into());
            output(i, value, text)
        }
        "projects hosted read" => {
            check(i, &["include-ignored"])?;
            let value = service
                .hosted_file_read(selector(i)?, path(i)?, i.boolean("include-ignored"))
                .await
                .map_err(hosted_error)?;
            let text = value["content"].as_str().unwrap_or_default().to_owned();
            output(i, value, text)
        }
        "projects hosted create" => {
            check(i, &["chat", "text", "file", "yes"])?;
            let content = body(i, "content")?;
            let mut approve = approval(i);
            let value = service
                .hosted_file_create(selector(i)?, chat(i)?, path(i)?, &content, &mut approve)
                .await
                .map_err(hosted_error)?;
            let text = format!(
                "Created {} (revision {}).",
                value["path"].as_str().unwrap_or_default(),
                value["revision"]
            );
            output(i, value, text)
        }
        "projects hosted update" => {
            check(i, &["chat", "text", "file", "yes"])?;
            let base = input::positional(
                i,
                2,
                "expected base (SHA-256 of the text the patch was made from)",
            )?;
            let patch = body(i, "patch")?;
            let mut approve = approval(i);
            let value = service
                .hosted_file_update(selector(i)?, chat(i)?, path(i)?, base, &patch, &mut approve)
                .await
                .map_err(hosted_error)?;
            let text = format!(
                "Updated {} (revision {}).",
                value["path"].as_str().unwrap_or_default(),
                value["revision"]
            );
            output(i, value, text)
        }
        _ => Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "This hosted Project file command is not ported.".into(),
        }),
    }
}
