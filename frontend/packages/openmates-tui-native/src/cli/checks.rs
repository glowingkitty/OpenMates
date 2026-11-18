//! `openmates checks list|show|create|run|result|confirm|ai-evaluate|link-plan`.
//! Thin shell over the shared encrypted SDK namespace: flag parsing and rendering
//! only; crypto, hashing, validation and transport live in the core.
use super::{CliError, CliOutput, Invocation, task_input as input};
use crate::{client::Client, runtime_store::RuntimeStore};
use openmates_sdk::{
    OpenMates,
    work::{CheckInput, Checks, SourceResultInput, parse_source_spec},
};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

pub(super) fn supported(invocation: &Invocation) -> bool {
    matches!(
        invocation.command_path().as_str(),
        "checks list"
            | "checks show"
            | "checks create"
            | "checks run"
            | "checks result"
            | "checks confirm"
            | "checks ai-evaluate"
            | "checks link-plan"
    )
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
        head["check_id"].as_str().unwrap_or(""),
        head["status"].as_str().unwrap_or(""),
        head["title"].as_str().unwrap_or("")
    )
}

fn label(aggregate: &str) -> &str {
    match aggregate {
        "waiting_for_confirmation" => "waiting for confirmation",
        other => other,
    }
}

/// Human rendering of a Check: sources grouped by kind with per-source status.
pub(super) fn render_show(value: &Value) -> String {
    let mut out = vec![line(&value["check"])];
    let definition = &value["revision"]["definition"];
    let run = &value["latest_run"];
    let results = run["source_results"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let status_of = |id: &str| {
        results
            .iter()
            .find(|r| r["source_binding_id"] == id)
            .and_then(|r| r["status"].as_str())
            .unwrap_or("pending")
            .to_owned()
    };
    let mut kinds: Vec<&str> = vec![];
    let sources = definition["sources"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    for source in &sources {
        let kind = source["source_kind"].as_str().unwrap_or("");
        if !kinds.contains(&kind) {
            kinds.push(kind);
        }
    }
    for kind in kinds {
        out.push(format!("{kind}:"));
        for source in sources.iter().filter(|s| s["source_kind"] == kind) {
            let id = source["source_binding_id"].as_str().unwrap_or("");
            let status = if run.is_null() {
                "not run".into()
            } else {
                status_of(id)
            };
            out.push(format!(
                "  [{status}] {id} ({}) {}",
                source["role"].as_str().unwrap_or(""),
                source["ref"].as_str().unwrap_or("")
            ));
        }
    }
    if run.is_null() {
        out.push("No run on the current revision yet.".into());
    } else {
        let aggregate = run["aggregate_status"]
            .as_str()
            .or(run["status"].as_str())
            .unwrap_or("");
        let stale = if run["stale"] == true { " (stale)" } else { "" };
        out.push(format!(
            "Run {}: {}{stale}",
            run["run_id"].as_str().unwrap_or(""),
            label(aggregate)
        ));
    }
    out.join("\n")
}

fn parse_inputs(invocation: &Invocation) -> Result<CheckInput, CliError> {
    let sources = invocation
        .values("source")
        .into_iter()
        .map(parse_source_spec)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(CheckInput {
        check_id: None,
        revision_id: None,
        title: input::required(invocation, "title")?.to_owned(),
        description: input::text(invocation, "description")?.map(str::to_owned),
        status: None,
        requires_deterministic: invocation.boolean("requires-deterministic"),
        sources,
    })
}

pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    _store: Option<&RuntimeStore>,
) -> Result<CliOutput, CliError> {
    let active = client.session().and_then(|s| s.active_team_id.clone());
    let team = team(invocation, active)?;
    run(invocation, client.checks().with_team(team), cancel).await
}

pub async fn execute_sdk_checks(
    invocation: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    client.set_operation_cancel(cancel.clone());
    let team = team(invocation, None)?;
    run(invocation, client.checks().with_team(team), cancel).await
}

async fn run(
    invocation: &Invocation,
    mut service: Checks<'_>,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if cancel.is_cancelled() {
        return Err(openmates_sdk::Error::Cancelled.into());
    }
    let project = input::text(invocation, "project")?;
    let check = input::text(invocation, "check")?;
    let id = || input::positional(invocation, 0, "ID");
    let path = invocation.command_path();
    match path.as_str() {
        "checks list" => {
            let plan = input::text(invocation, "plan")?;
            if project.is_none() && plan.is_none() {
                return Err(CliError::Invalid("Provide --project or --plan.".into()));
            }
            let rows = service.list(project, plan, 100).await?;
            let text = if rows.is_empty() {
                "No Checks found.".into()
            } else {
                rows.iter().map(line).collect::<Vec<_>>().join("\n")
            };
            output(invocation, json!({"checks": rows}), text)
        }
        "checks show" => {
            let value = service
                .show(id()?, project, input::text(invocation, "subject")?)
                .await?;
            let text = render_show(&value);
            output(invocation, value, text)
        }
        "checks create" => {
            let value = service
                .create(
                    input::required(invocation, "project")?,
                    parse_inputs(invocation)?,
                )
                .await?;
            let text = format!(
                "Created Check {}.",
                value["check"]["check_id"].as_str().unwrap_or("")
            );
            output(invocation, value, text)
        }
        "checks run" => {
            let value = service
                .start_run(id()?, input::text(invocation, "subject")?, None, project)
                .await?;
            let text = format!(
                "Started run {}.",
                value["run"]["run_id"].as_str().unwrap_or("")
            );
            output(invocation, value, text)
        }
        "checks result" => {
            let result = SourceResultInput {
                status: input::required(invocation, "status")?.to_owned(),
                test_result_embed_id: input::text(invocation, "test-result")?.map(str::to_owned),
                ai_score: None,
                ai_threshold: None,
                detail: input::text(invocation, "detail")?.map(str::to_owned),
            };
            let binding = input::positional(invocation, 1, "Source binding ID")?;
            let check = input::required(invocation, "check")?;
            let value = service
                .report_source_result(check, id()?, binding, result, project)
                .await?;
            let text = format!(
                "Run is {}.",
                label(value["run"]["status"].as_str().unwrap_or(""))
            );
            output(invocation, value, text)
        }
        "checks confirm" => {
            let binding = input::positional(invocation, 1, "Source binding ID")?;
            let note = input::text(invocation, "note")?;
            let pair = check.zip(note);
            if note.is_some() && check.is_none() {
                return Err(CliError::Invalid("--note needs --check.".into()));
            }
            let decision = input::required(invocation, "decision")?;
            let value = service
                .confirm_human(id()?, binding, decision, pair, project)
                .await?;
            let text = format!(
                "Run is {}.",
                label(value["run"]["status"].as_str().unwrap_or(""))
            );
            output(invocation, value, text)
        }
        "checks ai-evaluate" => {
            let binding = input::positional(invocation, 1, "Source binding ID")?;
            let file = input::required(invocation, "evidence-file")?;
            let evidence = std::fs::read_to_string(file)
                .map_err(|_| CliError::Invalid("--evidence-file could not be read.".into()))?;
            let threshold = input::text(invocation, "threshold")?
                .map(|v| {
                    v.parse::<f64>()
                        .map_err(|_| CliError::Invalid("--threshold must be a number.".into()))
                })
                .transpose()?;
            let check = input::required(invocation, "check")?;
            let value = service
                .ai_evaluate(check, id()?, binding, &evidence, threshold, project)
                .await?;
            let text = format!(
                "Verdict: {} (score {})\n{}",
                value["verdict"].as_str().unwrap_or(""),
                value["score"],
                value["feedback"].as_str().unwrap_or("")
            );
            output(invocation, value, text)
        }
        "checks link-plan" => {
            let plan = input::required(invocation, "plan")?;
            let value = service
                .link_plan(
                    id()?,
                    plan,
                    !invocation.boolean("supporting"),
                    input::text(invocation, "criterion")?,
                )
                .await?;
            output(invocation, value, format!("Linked to Plan {plan}."))
        }
        _ => Err(CliError::Unsupported {
            command: path,
            reason: "Unknown Check command.".into(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn show_groups_sources_by_kind_and_names_the_waiting_state() {
        let value = json!({
            "check": {"check_id": "c1", "status": "ready", "title": "Login works"},
            "revision": {"definition": {"sources": [
                {"source_binding_id": "s1", "source_kind": "e2e", "role": "required", "ref": "login.spec"},
                {"source_binding_id": "s2", "source_kind": "human_confirmation", "role": "required", "ref": "Look at it"},
                {"source_binding_id": "s3", "source_kind": "e2e", "role": "supporting", "ref": "smoke.spec"}
            ]}},
            "latest_run": {"run_id": "r1", "aggregate_status": "waiting_for_confirmation", "stale": true,
                           "source_results": [{"source_binding_id": "s1", "status": "passed"}]}
        });
        let text = render_show(&value);
        assert!(text.contains(
            "e2e:\n  [passed] s1 (required) login.spec\n  [pending] s3 (supporting) smoke.spec"
        ));
        assert!(text.contains("human_confirmation:\n  [pending] s2"));
        assert!(text.contains("Run r1: waiting for confirmation (stale)"));
        let none = render_show(
            &json!({"check": {}, "revision": {"definition": {"sources": []}}, "latest_run": null}),
        );
        assert!(none.contains("No run"));
    }
}
