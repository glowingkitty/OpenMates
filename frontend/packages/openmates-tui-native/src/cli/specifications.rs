//! `openmates specifications list|show|revisions|revise|approve|create`.
//! Thin shell over the shared encrypted SDK namespace: file parsing, flag
//! validation and rendering only; crypto, hashing and transport live in the core.
use super::{CliError, CliOutput, Invocation, task_input as input};
use crate::{client::Client, runtime_store::RuntimeStore};
use openmates_sdk::{
    OpenMates,
    work::{SpecificationInput, Specifications},
};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

const FLAGS: &[&str] = &[
    "project", "revision", "file", "limit", "before", "after", "team", "personal",
];

pub(super) fn supported(invocation: &Invocation) -> bool {
    matches!(
        invocation.command_path().as_str(),
        "specifications list"
            | "specifications show"
            | "specifications revisions"
            | "specifications revise"
            | "specifications approve"
            | "specifications create"
    )
}

/// Parses a JSON or YAML authoring file: either a full input object with a
/// `document` member or the document itself.
fn parse_file(raw: &str) -> Result<SpecificationInput, CliError> {
    let value: Value = if raw.trim_start().starts_with('{') {
        serde_json::from_str(raw)
            .map_err(|_| CliError::Invalid("--file is not valid JSON.".into()))?
    } else {
        serde_yaml::from_str(raw)
            .map_err(|_| CliError::Invalid("--file is not valid YAML.".into()))?
    };
    let wrapped = value.get("document").is_some();
    let value = if wrapped {
        value
    } else {
        json!({"document": value})
    };
    serde_json::from_value(value).map_err(|error| {
        CliError::Invalid(format!("--file is not a Specification document: {error}"))
    })
}

fn read_file(invocation: &Invocation) -> Result<SpecificationInput, CliError> {
    let path = input::required(invocation, "file")?;
    let raw = std::fs::read_to_string(path)
        .map_err(|_| CliError::Invalid("--file could not be read.".into()))?;
    parse_file(&raw)
}

fn number(invocation: &Invocation, name: &str) -> Result<Option<u64>, CliError> {
    input::text(invocation, name)?
        .map(|v| {
            v.parse()
                .map_err(|_| CliError::Invalid(format!("--{name} must be a number.")))
        })
        .transpose()
}

fn team(invocation: &Invocation, active: Option<String>) -> Result<Option<String>, CliError> {
    if invocation.boolean("personal") && invocation.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    if invocation.boolean("personal") {
        return Ok(None);
    }
    Ok(input::text(invocation, "team")?
        .map(str::to_owned)
        .or(active))
}

fn output(invocation: &Invocation, value: Value, text: String) -> Result<CliOutput, CliError> {
    if invocation.boolean("json") {
        CliOutput::json(&value)
    } else {
        Ok(CliOutput::text(text))
    }
}

fn line(head: &Value) -> String {
    format!(
        "{}  {}  {}",
        head["specification_id"].as_str().unwrap_or(""),
        head["status"].as_str().unwrap_or(""),
        head["title"].as_str().unwrap_or("")
    )
}

pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    _store: Option<&RuntimeStore>,
) -> Result<CliOutput, CliError> {
    let active = client.session().and_then(|s| s.active_team_id.clone());
    let team = team(invocation, active)?;
    run(invocation, client.specifications().with_team(team), cancel).await
}

pub async fn execute_sdk_specifications(
    invocation: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    client.set_operation_cancel(cancel.clone());
    let team = team(invocation, None)?;
    run(invocation, client.specifications().with_team(team), cancel).await
}

async fn run(
    invocation: &Invocation,
    mut service: Specifications<'_>,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if cancel.is_cancelled() {
        return Err(openmates_sdk::Error::Cancelled.into());
    }
    input::check_flags(invocation, FLAGS)?;
    let project = input::required(invocation, "project")?;
    let id = || input::positional(invocation, 0, "Specification ID");
    let revision = || input::required(invocation, "revision");
    let path = invocation.command_path();
    match path.as_str() {
        "specifications list" => {
            let rows = service
                .list(
                    project,
                    number(invocation, "limit")?.unwrap_or(50).min(100) as u8,
                    input::text(invocation, "after")?,
                )
                .await?;
            let text = if rows.is_empty() {
                "No Specifications found.".into()
            } else {
                rows.iter().map(line).collect::<Vec<_>>().join("\n")
            };
            output(invocation, json!({"specifications": rows}), text)
        }
        "specifications show" => {
            let value = service
                .show(project, id()?, input::text(invocation, "revision")?)
                .await?;
            let text = format!(
                "{}\nRevision {} ({})\n{}",
                line(&value["specification"]),
                value["revision"]["revision_number"],
                value["revision"]["approval_state"]
                    .as_str()
                    .unwrap_or("draft"),
                value["revision"]["summary"].as_str().unwrap_or("")
            );
            output(invocation, value, text)
        }
        "specifications revisions" => {
            let rows = service
                .revisions(
                    project,
                    id()?,
                    number(invocation, "limit")?.unwrap_or(50).min(100) as u8,
                    number(invocation, "before")?,
                )
                .await?;
            let text = rows
                .iter()
                .map(|r| {
                    format!(
                        "#{}  {}  {}  {}",
                        r["revision_number"],
                        r["approval_state"].as_str().unwrap_or(""),
                        r["revision_id"].as_str().unwrap_or(""),
                        r["title"].as_str().unwrap_or("")
                    )
                })
                .collect::<Vec<_>>()
                .join("\n");
            output(invocation, json!({"revisions": rows}), text)
        }
        "specifications approve" => {
            let value = service.approve(project, id()?, revision()?).await?;
            let text = format!(
                "Approved revision {}.",
                value["revision"]["revision_id"].as_str().unwrap_or("")
            );
            output(invocation, value, text)
        }
        "specifications create" => {
            let value = service.create(project, read_file(invocation)?).await?;
            let text = format!(
                "Created Specification {}.",
                value["specification"]["specification_id"]
                    .as_str()
                    .unwrap_or("")
            );
            output(invocation, value, text)
        }
        "specifications revise" => {
            let value = service
                .revise(project, id()?, revision()?, read_file(invocation)?)
                .await?;
            let text = format!(
                "Saved revision {}.",
                value["revision"]["revision_id"].as_str().unwrap_or("")
            );
            output(invocation, value, text)
        }
        _ => Err(CliError::Unsupported {
            command: path,
            reason: "Unknown Specification command.".into(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn file_accepts_a_yaml_document_or_a_wrapped_input() {
        let yaml = "title: Recipes\nsummary: Plan meals\nflows:\n  - id: F1\n    title: Save\n    kind: user_flow\n    steps: [Open]\n";
        let input = parse_file(yaml).ok().unwrap();
        assert_eq!(input.document.title, "Recipes");
        assert_eq!(input.document.flows[0].steps, ["Open"]);
        let wrapped =
            parse_file(r#"{"specification_id":"s","document":{"title":"T","summary":"S"}}"#)
                .ok().unwrap();
        assert_eq!(wrapped.specification_id.as_deref(), Some("s"));
        assert!(parse_file("title: [unclosed").is_err());
    }
}
