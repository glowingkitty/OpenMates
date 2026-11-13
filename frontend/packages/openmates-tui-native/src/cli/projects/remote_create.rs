//! `projects remote hosts|create`: thin argument parsing and formatting over
//! the shared core (`Projects::machine_hosts`, `propose_machine_source`,
//! `create_machine_source`). The machine decides where the folder goes (its
//! own new-Projects folder); the core owns the placeholder and approval flow.
//! Running `create` is the explicit user confirmation, so there is no prompt.
use super::remote_ops::{code_name, contract, operation_id, refusal, refusal_output, short};
use super::*;
use openmates_sdk::work::RemoteOpError;

const FLAGS: &[&str] = &["chat", "host", "name", "source"];

/// Validated, network-free view of one `create` invocation.
struct CreateRequest<'a> {
    project: &'a str,
    chat: &'a str,
    host: Option<&'a str>,
    name: &'a str,
    source: Option<&'a str>,
}

fn project_of(i: &Invocation) -> Result<&str, CliError> {
    if !i.boolean("personal") && !i.has("team") {
        return Err(contract(
            "context_confirmation_required",
            "Remote operations require --personal or --team <team>.",
        ));
    }
    i.positionals
        .first()
        .map(|v| v.trim())
        .filter(|v| !v.is_empty())
        .ok_or_else(|| contract("command_failed", "Missing project."))
}

fn create_request(i: &Invocation) -> Result<CreateRequest<'_>, CliError> {
    check(i, FLAGS)?;
    let project = project_of(i)?;
    let text = |name: &str| i.text(name).map(str::trim).filter(|v| !v.is_empty());
    let chat =
        text("chat").ok_or_else(|| contract("command_failed", "Missing --chat <chat-id>."))?;
    let name = text("name")
        .ok_or_else(|| contract("command_failed", "Missing --name \"<Project name>\"."))?;
    let (host, source) = (text("host"), text("source"));
    match (host, source) {
        (None, None) => Err(contract(
            "command_failed",
            "Missing --host <device hash> (see 'projects remote hosts') or --source <placeholder id> to retry.",
        )),
        (Some(_), Some(_)) => Err(contract(
            "command_failed",
            "--host proposes a new placeholder; --source retries an existing one. Use only one.",
        )),
        _ => Ok(CreateRequest {
            project,
            chat,
            host,
            name,
            source,
        }),
    }
}

/// One line per machine: device hash and the source names it hosts.
fn host_line(host_device_hash: &str, source_names: &[String]) -> String {
    format!("{host_device_hash}  {}", source_names.join(", "))
}

fn created_text(folder_name: &str, path: &str, branch: &str, head: &str) -> String {
    format!(
        "Created {folder_name} at {path} (branch {branch}, head {}).",
        short(head)
    )
}

/// Refusal after the placeholder exists: the stable code plus the placeholder
/// id so the user can retry (`--source`) or remove it.
fn creation_refusal(
    json: bool,
    source_id: &str,
    error: RemoteOpError,
) -> Result<CliOutput, CliError> {
    let (code, message) = match error {
        RemoteOpError::Core(error) => return Err(CliError::Client(error)),
        RemoteOpError::Host { code, message } => (code_name(&code), message),
    };
    let hint = format!(
        "Pending placeholder source: {source_id}. Retry with --source {source_id} or delete it with 'projects sources remove'."
    );
    if json {
        let mut out = CliOutput::json(
            &json!({"error":{"code":code,"message":message,"source_id":source_id}}),
        )?;
        out.exit_code = 125;
        return Ok(out);
    }
    refusal_output(false, code, &format!("{message}\n{hint}"))
}

pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    if i.command_path() == "projects remote hosts" {
        check(i, &[])?;
        let hosts = match service.machine_hosts(project_of(i)?).await {
            Ok(hosts) => hosts,
            Err(error) => return refusal(i, error),
        };
        let value = Value::Array(
            hosts
                .iter()
                .map(|h| json!({"host_device_hash": h.host_device_hash, "source_names": h.source_names}))
                .collect(),
        );
        let text = if hosts.is_empty() {
            "No connected machines.".to_owned()
        } else {
            hosts
                .iter()
                .map(|h| host_line(&h.host_device_hash, &h.source_names))
                .collect::<Vec<_>>()
                .join("\n")
        };
        return output(i, value, text);
    }
    let req = create_request(i)?;
    let (source_id, proposed) = match (req.source, req.host) {
        (Some(source), _) => (source.to_owned(), false),
        (None, Some(host)) => match service
            .propose_machine_source(req.project, host, req.name)
            .await
        {
            Ok(source) => (source.source_id, true),
            Err(error) => return refusal(i, error),
        },
        (None, None) => return Err(contract("command_failed", "Missing --host.")),
    };
    let created = service
        .create_machine_source(req.project, &source_id, req.chat, &operation_id(), req.name)
        .await;
    match created {
        Ok(created) => {
            let value = json!({"source_id": source_id, "proposed": proposed, "path": created.path,
                "folder_name": created.folder_name, "head": created.head, "branch": created.branch});
            let text = created_text(
                &created.folder_name,
                &created.path,
                &created.branch,
                &created.head,
            );
            output(i, value, text)
        }
        Err(error) => creation_refusal(i.boolean("json"), &source_id, error),
    }
}

#[cfg(test)]
#[path = "remote_create_tests.rs"]
mod tests;
