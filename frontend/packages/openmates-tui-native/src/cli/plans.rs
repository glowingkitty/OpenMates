//! Plan CLI commands use the shared encrypted SDK namespace. Unsupported Plan
//! subfamilies remain explicit; no arbitrary HTTP route or alternate runtime.
mod children;
use super::{CliError, CliOutput, Invocation, task_input as input};
use crate::{client::Client, error::Error, runtime_store::RuntimeStore};
use openmates_sdk::{
    OpenMates,
    work::{PlanAskOptions, PlanCreate, PlanFilters, PlanFlow, PlanPatch, Plans, RestoreState},
};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;
const GLOBALS: &[&str] = &[
    "json",
    "profile",
    "api-url",
    "api-key",
    "state-dir",
    "encrypted-vault",
    "demo",
    "personal",
    "team",
];
const FIELDS: &[&str] = &[
    "title",
    "goal",
    "slug",
    "scope-in",
    "scope-out",
    "user-flows",
    "assumptions",
    "open-questions",
    "constraints",
    "decisions",
    "risks",
    "reference-patterns",
    "context",
    "status",
    "chat",
    "project",
    "projects",
    "focus",
];
const TEXT_SECTIONS: &[&str] = &[
    "goal",
    "scope-in",
    "scope-out",
    "open-questions",
    "constraints",
    "decisions",
    "risks",
    "reference-patterns",
    "context",
];
const TEXT_ACTIONS: &[&str] = &[
    "set",
    "clear",
    "add",
    "edit",
    "update",
    "remove",
    "answer",
    "supersede",
];
fn text_section(invocation: &Invocation) -> bool {
    invocation.path.len() == 3
        && TEXT_SECTIONS.contains(&invocation.path[1].as_str())
        && TEXT_ACTIONS.contains(&invocation.path[2].as_str())
}
fn section_patch(
    section: &str,
    action: &str,
    current: &str,
    text: Option<&str>,
) -> Result<PlanPatch, CliError> {
    let value = if matches!(action, "clear" | "remove") {
        String::new()
    } else {
        let text = text
            .map(str::trim)
            .filter(|text| !text.is_empty())
            .ok_or_else(|| CliError::Invalid("Provide --text <text> or positional text.".into()))?;
        if matches!(action, "add" | "answer" | "supersede") {
            if current.trim().is_empty() {
                format!("- {text}")
            } else {
                format!("{}\n- {text}", current.trim())
            }
        } else {
            text.to_owned()
        }
    };
    let mut patch = PlanPatch::default();
    match section {
        "goal" => patch.goal = Some(value),
        "scope-in" => patch.scope_in = Some(value),
        "scope-out" => patch.scope_out = Some(value),
        "open-questions" => patch.open_questions = Some(value),
        "constraints" => patch.constraints = Some(value),
        "decisions" => patch.decisions = Some(value),
        "risks" => patch.risks = Some(value),
        "reference-patterns" => patch.reference_patterns = Some(value),
        "context" => patch.context = Some(value),
        _ => return Err(CliError::Invalid("Unknown Plan text section.".into())),
    }
    Ok(patch)
}
pub(super) fn supported(invocation: &Invocation) -> bool {
    children::supported(invocation)
        || text_section(invocation)
        || matches!(
            invocation.command_path().as_str(),
            "plans list"
                | "plans ask"
                | "plans status"
                | "plans show"
                | "plans create"
                | "plans edit"
                | "plans update"
                | "plans delete"
                | "plans activate"
                | "plans approve"
                | "plans attach"
                | "plans start"
                | "plans pause"
                | "plans resume"
                | "plans archive"
                | "plans complete"
                | "plans done"
                | "plans history"
                | "plans restore"
                | "plans add-to-project"
                | "plans remove-from-project"
        )
        || invocation
            .path
            .starts_with(&["plans".into(), "tasks".into()])
            && invocation.path.len() > 2
}
fn check(invocation: &Invocation, allowed: &[&str]) -> Result<(), CliError> {
    for (key, value) in &invocation.flags {
        if !GLOBALS.contains(&key.as_str()) && !allowed.contains(&key.as_str()) {
            return Err(CliError::Unsupported {
                command: invocation.command_path(),
                reason: format!("Option --{key} is not ported for this native Plan operation."),
            });
        }
        if value.is_array()
            && ![
                "project",
                "projects",
                "task",
                "tasks",
                "check",
                "checks",
                "verification",
                "verifications",
                "cover",
                "covers",
                "learning",
                "learnings",
                "proof-file",
                "proof-url",
                "proof-embed",
            ]
            .contains(&key.as_str())
        {
            return Err(CliError::Invalid(format!(
                "Option --{key} must be supplied once."
            )));
        }
    }
    Ok(())
}
fn status(value: &str) -> Result<String, CliError> {
    if [
        "draft",
        "checking_assumptions",
        "awaiting_confirmation",
        "active",
        "executing",
        "running_checks",
        "blocked",
        "completed",
        "archived",
    ]
    .contains(&value)
    {
        Ok(value.into())
    } else {
        Err(CliError::Invalid("Unknown Plan status.".into()))
    }
}
fn filters(
    invocation: &Invocation,
    team: Option<String>,
    mutation: bool,
) -> Result<PlanFilters, CliError> {
    let mut filters = PlanFilters {
        team_id: team,
        personal: invocation.boolean("personal"),
        ..Default::default()
    };
    if !mutation {
        filters.status = input::text(invocation, "status")?.map(status).transpose()?;
    }
    if !mutation || children::supported(invocation) || text_section(invocation) {
        filters.chat_id = input::text(invocation, "chat")?.map(str::to_owned);
        filters.project_id = input::text(invocation, "project")?.map(str::to_owned);
        filters.active_only = invocation
            .has("active")
            .then(|| invocation.boolean("active"));
    }
    Ok(filters)
}
fn flows(invocation: &Invocation) -> Result<Option<Vec<PlanFlow>>, CliError> {
    input::text(invocation, "user-flows")?
        .map(|raw| {
            let flows: Vec<PlanFlow> = serde_json::from_str(raw).map_err(|_| {
                CliError::Invalid(
                    "--user-flows must contain a typed JSON array of ordered user flows.".into(),
                )
            })?;
            if flows.len() > 100 {
                return Err(CliError::Invalid(
                    "At most 100 Plan user flows are supported.".into(),
                ));
            }
            Ok(flows)
        })
        .transpose()
}
fn create(invocation: &Invocation) -> Result<PlanCreate, CliError> {
    check(invocation, FIELDS)?;
    let goal = input::required(invocation, "goal")?.to_owned();
    let linked_project_ids = input::ids(invocation, &["project", "projects"]);
    if linked_project_ids.is_empty() {
        return Err(CliError::Invalid(
            "Creating a Plan requires --project <id>.".into(),
        ));
    }
    let title = input::text(invocation, "title")?
        .map(str::to_owned)
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| {
            let positional = invocation.positionals.join(" ");
            if positional.trim().is_empty() {
                goal.chars().take(80).collect()
            } else {
                positional.trim().into()
            }
        });
    Ok(PlanCreate {
        title,
        goal,
        slug: input::text(invocation, "slug")?.map(str::to_owned),
        scope_in: input::text(invocation, "scope-in")?.unwrap_or("").into(),
        scope_out: input::text(invocation, "scope-out")?.unwrap_or("").into(),
        user_flows: flows(invocation)?.unwrap_or_default(),
        assumptions: input::text(invocation, "assumptions")?.unwrap_or("").into(),
        open_questions: input::text(invocation, "open-questions")?
            .unwrap_or("")
            .into(),
        constraints: input::text(invocation, "constraints")?.unwrap_or("").into(),
        decisions: input::text(invocation, "decisions")?.unwrap_or("").into(),
        risks: input::text(invocation, "risks")?.unwrap_or("").into(),
        reference_patterns: input::text(invocation, "reference-patterns")?
            .unwrap_or("")
            .into(),
        context: input::text(invocation, "context")?.unwrap_or("").into(),
        status: input::text(invocation, "status")?.map(status).transpose()?,
        primary_chat_id: input::text(invocation, "chat")?.map(str::to_owned),
        linked_project_ids,
        planner_focus_id: input::text(invocation, "focus")?.map(str::to_owned),
        ..Default::default()
    })
}
fn patch(invocation: &Invocation) -> Result<PlanPatch, CliError> {
    check(invocation, FIELDS)?;
    if !FIELDS.iter().any(|name| invocation.has(name)) {
        return Err(CliError::Invalid(
            "Provide at least one Plan field to edit.".into(),
        ));
    }
    Ok(PlanPatch {
        title: input::text(invocation, "title")?.map(str::to_owned),
        goal: input::text(invocation, "goal")?.map(str::to_owned),
        slug: input::text(invocation, "slug")?.map(str::to_owned),
        scope_in: input::text(invocation, "scope-in")?.map(str::to_owned),
        scope_out: input::text(invocation, "scope-out")?.map(str::to_owned),
        user_flows: flows(invocation)?,
        assumptions: input::text(invocation, "assumptions")?.map(str::to_owned),
        open_questions: input::text(invocation, "open-questions")?.map(str::to_owned),
        constraints: input::text(invocation, "constraints")?.map(str::to_owned),
        decisions: input::text(invocation, "decisions")?.map(str::to_owned),
        risks: input::text(invocation, "risks")?.map(str::to_owned),
        reference_patterns: input::text(invocation, "reference-patterns")?.map(str::to_owned),
        context: input::text(invocation, "context")?.map(str::to_owned),
        status: input::text(invocation, "status")?.map(status).transpose()?,
        primary_chat_id: invocation
            .has("chat")
            .then(|| input::text(invocation, "chat").map(|value| value.map(str::to_owned)))
            .transpose()?,
        linked_project_ids: ["project", "projects"]
            .iter()
            .any(|name| invocation.has(name))
            .then(|| input::ids(invocation, &["project", "projects"])),
        planner_focus_id: invocation
            .has("focus")
            .then(|| input::text(invocation, "focus").map(|value| value.map(str::to_owned)))
            .transpose()?,
    })
}
fn render(plan: &Value) -> String {
    let mut text = format!(
        "{}: {}\nStatus: {}",
        plan["short_id"]
            .as_str()
            .or(plan["plan_id"].as_str())
            .unwrap_or("Plan"),
        plan["title"].as_str().unwrap_or(""),
        plan["status"].as_str().unwrap_or("")
    );
    for (field, label) in [
        ("plan_id", "ID"),
        ("goal", "Goal"),
        ("scope_in", "In scope"),
        ("scope_out", "Out of scope"),
        ("assumptions", "Assumptions"),
        ("open_questions", "Open questions"),
        ("constraints", "Constraints"),
        ("decisions", "Decisions"),
        ("risks", "Risks"),
        ("reference_patterns", "Reference patterns"),
        ("context", "Context"),
        ("primary_chat_id", "Chat"),
    ] {
        if let Some(value) = plan[field].as_str().filter(|value| !value.is_empty()) {
            text.push_str(&format!("\n{label}: {value}"));
        }
    }
    if let Some(projects) = plan["linked_project_ids"].as_array() {
        let ids = projects
            .iter()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>();
        if !ids.is_empty() {
            text.push_str(&format!("\nProjects: {}", ids.join(", ")));
        }
    }
    for flow in plan["user_flows"].as_array().into_iter().flatten() {
        text.push_str(&format!("\nFlow: {}", flow["title"].as_str().unwrap_or("")));
        for (index, step) in flow["steps"].as_array().into_iter().flatten().enumerate() {
            text.push_str(&format!(
                "\n  {}. {}",
                index + 1,
                step["text"].as_str().unwrap_or("")
            ));
        }
        if let Some(outcome) = flow["expected_outcome"].as_str() {
            text.push_str(&format!("\n  Expected: {outcome}"));
        }
    }
    text
}
fn output(invocation: &Invocation, value: Value, text: String) -> Result<CliOutput, CliError> {
    if invocation.boolean("json") {
        CliOutput::json(&value)
    } else {
        Ok(CliOutput::text(text))
    }
}
fn delegated(invocation: &Invocation, plan: &Value) -> Result<Invocation, CliError> {
    let plan_id = plan["plan_id"]
        .as_str()
        .ok_or(CliError::Client(Error::Protocol))?;
    let mut flags = invocation.flags.clone();
    flags.insert("plan".into(), json!(plan_id));
    let mut path = vec!["tasks".into()];
    path.extend(invocation.path.iter().skip(2).cloned());
    Ok(Invocation {
        path,
        positionals: invocation.positionals.iter().skip(1).cloned().collect(),
        flags,
    })
}
fn ask_input(invocation: &Invocation) -> Result<(String, PlanAskOptions), CliError> {
    check(
        invocation,
        &[
            "text",
            "goal",
            "summary",
            "slug",
            "status",
            "chat",
            "project",
            "projects",
            "auto-approve",
            "auto-approve-memories",
            "no-pii-detection",
            "response-timeout-seconds",
        ],
    )?;
    let positional = invocation.positionals.join(" ");
    let instruction = input::text(invocation, "text")?
        .unwrap_or(&positional)
        .trim();
    if instruction.is_empty() {
        return Err(CliError::Invalid("Provide a Plan instruction.".into()));
    }
    let goal = input::text(invocation, "goal")?
        .or(input::text(invocation, "summary")?)
        .unwrap_or("");
    Ok((
        instruction.to_owned(),
        PlanAskOptions {
            defaults: PlanCreate {
                goal: goal.into(),
                slug: input::text(invocation, "slug")?.map(str::to_owned),
                status: input::text(invocation, "status")?.map(status).transpose()?,
                primary_chat_id: input::text(invocation, "chat")?.map(str::to_owned),
                linked_project_ids: input::ids(invocation, &["project", "projects"]),
                ..Default::default()
            },
            ..Default::default()
        },
    ))
}
pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    store: Option<&RuntimeStore>,
) -> Result<CliOutput, CliError> {
    let team = client
        .session()
        .and_then(|session| session.active_team_id.clone());
    if invocation.command_path() == "plans ask" {
        let (instruction, options) = ask_input(invocation)?;
        let value = client
            .plans()
            .with_filters(filters(invocation, team, true)?)
            .ask(&instruction, options)
            .await?;
        return super::tasks::workspace_ask_output(
            invocation,
            client,
            cancel,
            instruction,
            value,
            "plan",
        )
        .await;
    }
    if invocation.path.get(1).is_some_and(|path| path == "tasks") {
        let plan = client
            .plans()
            .with_filters(filters(invocation, team, true)?)
            .show(input::positional(invocation, 0, "Plan ID")?)
            .await?;
        let task = delegated(invocation, &plan)?;
        return super::tasks::execute(&task, client, cancel, store).await;
    }
    let mutation = !matches!(
        invocation.command_path().as_str(),
        "plans list" | "plans status" | "plans show" | "plans history" | "plans restore"
    );
    execute_service(
        invocation,
        client
            .plans()
            .with_filters(filters(invocation, team, mutation)?),
        cancel,
    )
    .await
}
pub async fn execute_sdk_plans_with_delivery(
    invocation: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
    store: &RuntimeStore,
    api_url: &str,
) -> Result<CliOutput, CliError> {
    if invocation.boolean("personal") && invocation.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    client.set_operation_cancel(cancel.clone());
    let team = input::text(invocation, "team")?.map(str::to_owned);
    if invocation.path.get(1).is_some_and(|path| path == "tasks") {
        let plan = client
            .plans()
            .with_filters(filters(invocation, team, true)?)
            .show(input::positional(invocation, 0, "Plan ID")?)
            .await?;
        let task = delegated(invocation, &plan)?;
        return super::tasks::execute_sdk_tasks_with_delivery(
            &task, client, cancel, store, api_url,
        )
        .await;
    }
    let mutation = !matches!(
        invocation.command_path().as_str(),
        "plans list" | "plans status" | "plans show" | "plans history" | "plans restore"
    );
    execute_service(
        invocation,
        client
            .plans()
            .with_filters(filters(invocation, team, mutation)?),
        cancel,
    )
    .await
}
async fn execute_service(
    invocation: &Invocation,
    mut service: Plans<'_>,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    if children::supported(invocation) {
        return children::execute(invocation, &mut service).await;
    }
    let path = invocation.command_path();
    if text_section(invocation) {
        check(invocation, &["text", "status", "chat", "project", "active"])?;
        let id = input::positional(invocation, 0, "Plan ID")?;
        let section = &invocation.path[1];
        let current = service.show(id).await?;
        let positional = invocation
            .positionals
            .iter()
            .skip(1)
            .cloned()
            .collect::<Vec<_>>()
            .join(" ");
        let text = input::text(invocation, "text")?.or(Some(positional.as_str()));
        let patch = section_patch(
            section,
            &invocation.path[2],
            current[section.replace('-', "_")].as_str().unwrap_or(""),
            text,
        )?;
        let plan = service.update(id, patch).await?;
        return output(invocation, json!({"plan":plan}), render(&plan));
    }
    let id = || input::positional(invocation, 0, "Plan ID");
    let value = match path.as_str() {
        "plans list" | "plans status" => {
            check(invocation, &["status", "active", "chat", "project"])?;
            if path == "plans status" && !invocation.positionals.is_empty() {
                let plan = service.show(id()?).await?;
                return output(invocation, json!({"plan":plan}), render(&plan));
            }
            let plans = service.list().await?;
            let text = if plans.is_empty() {
                "No Plans found.".into()
            } else {
                plans
                    .iter()
                    .map(|plan| {
                        format!(
                            "{}  {}  [{}]",
                            plan["short_id"]
                                .as_str()
                                .or(plan["plan_id"].as_str())
                                .unwrap_or("Plan"),
                            plan["title"].as_str().unwrap_or(""),
                            plan["status"].as_str().unwrap_or("")
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("\n")
            };
            return output(invocation, json!({"plans":plans}), text);
        }
        "plans show" => {
            check(invocation, &["status", "chat", "project"])?;
            service.show(id()?).await?
        }
        "plans ask" => {
            let (instruction, options) = ask_input(invocation)?;
            let value = service.ask(&instruction, options).await?;
            if value["fallback_to_chat"] == true || value["outcome"] == "fallback_to_chat" {
                return Err(Error::Unavailable { code: "workspace_ask_chat_fallback_unavailable", reason: "API-key Plan ask requires more chat context; use the interactive account CLI." }.into());
            }
            let text = super::tasks::ask_text(&value, "plan");
            return output(invocation, value, text);
        }
        "plans create" => service.create(create(invocation)?).await?,
        "plans edit" | "plans update" => service.update(id()?, patch(invocation)?).await?,
        "plans activate" | "plans approve" | "plans attach" => {
            check(invocation, &["chat"])?;
            if path == "plans attach" {
                service
                    .attach(id()?, input::text(invocation, "chat")?)
                    .await?
            } else {
                service
                    .activate(id()?, input::text(invocation, "chat")?)
                    .await?
            }
        }
        "plans start" | "plans resume" | "plans complete" | "plans done" => {
            check(invocation, &[])?;
            match path.as_str() {
                "plans start" => service.start(id()?).await?,
                "plans resume" => service.resume(id()?).await?,
                _ => service.complete(id()?).await?,
            }
        }
        "plans pause" | "plans archive" => {
            check(invocation, &[])?;
            service
                .update(
                    id()?,
                    PlanPatch {
                        status: Some(
                            if path == "plans pause" {
                                "awaiting_confirmation"
                            } else {
                                "archived"
                            }
                            .into(),
                        ),
                        ..Default::default()
                    },
                )
                .await?
        }
        "plans delete" => {
            check(invocation, &["confirm"])?;
            if !invocation.boolean("confirm") {
                return Err(CliError::Invalid(
                    "Deleting a Plan requires --confirm.".into(),
                ));
            }
            let value = service.delete(id()?, true).await?;
            return output(invocation, value, "Plan deleted.".into());
        }
        "plans history" => {
            check(invocation, &["limit"])?;
            let limit = input::text(invocation, "limit")?
                .map(|value| {
                    value
                        .parse::<u16>()
                        .ok()
                        .filter(|limit| *limit > 0 && *limit <= 500)
                        .ok_or_else(|| CliError::Invalid("--limit must be from 1 to 500.".into()))
                })
                .transpose()?;
            let entries = service.history(id()?, limit).await?;
            return super::history::output(invocation, entries);
        }
        "plans restore" => {
            check(invocation, &["entry", "entry-id", "state"])?;
            let entry = super::history::entry(invocation)?;
            let state = match input::text(invocation, "state")?.unwrap_or("before") {
                "before" => RestoreState::Before,
                "after" => RestoreState::After,
                _ => return Err(CliError::Invalid("--state must be before or after.".into())),
            };
            let value = service.restore(id()?, entry, state).await?;
            return output(invocation, value, "Plan restored.".into());
        }
        "plans add-to-project" | "plans remove-from-project" => {
            check(invocation, &[])?;
            let project = input::positional(invocation, 1, "Project ID")?;
            if path == "plans add-to-project" {
                service.add_to_project(id()?, project).await?
            } else {
                service.remove_from_project(id()?, project).await?
            }
        }
        _ => {
            return Err(CliError::Unsupported {
                command: path,
                reason: "This Plan subfamily has not been ported to the native CLI.".into(),
            });
        }
    };
    let text = render(&value);
    output(invocation, json!({"plan":value}), text)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn invocation(flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: vec!["plans".into(), "create".into()],
            positionals: vec![],
            flags: flags
                .iter()
                .map(|(key, value)| ((*key).into(), value.clone()))
                .collect(),
        }
    }
    #[test]
    fn nested_plan_router_preserves_personal_scope_child_status_and_explicit_clears() {
        let parsed = super::super::parse_from([
            "openmates",
            "plans",
            "checks",
            "update",
            "PLAN-42",
            "--check",
            "check-a",
            "--personal",
            "--project",
            "engineering",
            "--status",
            "passed",
            "--confidence",
            "--source-hash",
            "--required",
        ])
        .ok()
        .unwrap();
        let invocation = parsed.invocation.as_ref().unwrap();
        assert!(supported(invocation));
        let scope = filters(invocation, None, true).ok().unwrap();
        assert!(scope.personal);
        assert!(scope.team_id.is_none());
        assert!(scope.status.is_none());
        assert_eq!(scope.project_id.as_deref(), Some("engineering"));
        assert!(invocation.flags["confidence"].is_null());
        assert!(invocation.flags["source-hash"].is_null());
        assert!(invocation.boolean("required"));
        let parsed = super::super::parse_from([
            "openmates",
            "plans",
            "tasks",
            "activity",
            "PLAN-42",
            "list",
            "TASK-27",
            "--personal",
            "--project",
            "engineering",
        ])
        .ok()
        .unwrap();
        let invocation = parsed.invocation.as_ref().unwrap();
        let task = delegated(invocation, &json!({"plan_id":"plan-uuid"}))
            .ok()
            .unwrap();
        assert_eq!(task.path, ["tasks", "activity", "list"]);
        assert_eq!(task.positionals, ["TASK-27"]);
        assert!(task.boolean("personal"));
        assert_eq!(task.text("project"), Some("engineering"));
        assert_eq!(task.text("plan"), Some("plan-uuid"));
    }
    #[test]
    fn ask_defaults_keep_nullable_links_and_do_not_require_projects_for_exact_mutations() {
        let mut command = invocation(&[
            ("text", json!("Rename @plan:PLAN-42 to Native")),
            ("status", json!("active")),
        ]);
        command.path = vec!["plans".into(), "ask".into()];
        let (text, options) = ask_input(&command).ok().unwrap();
        assert!(text.contains("@plan:PLAN-42"));
        assert_eq!(options.defaults.status.as_deref(), Some("active"));
        assert!(options.defaults.linked_project_ids.is_empty());
        assert!(ask_input(&invocation(&[("auto-approve", json!(true))])).is_err());
    }
    #[test]
    fn dynamic_text_sections_parse_real_plan_and_positional_text() {
        let parsed = super::super::parse_from([
            "openmates",
            "plans",
            "risks",
            "add",
            "PLAN-42",
            "Network",
            "failure",
            "--json",
        ])
        .ok()
        .unwrap();
        let invocation = parsed.invocation.as_ref().unwrap();
        assert!(text_section(invocation));
        assert_eq!(invocation.positionals, ["PLAN-42", "Network", "failure"]);
        let output = output(invocation, json!({"plan":{"plan_id":"p"}}), String::new())
            .ok()
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&output.stdout).unwrap()["plan"]["plan_id"],
            "p"
        );
    }
    #[test]
    fn text_sections_append_trimmed_bullets_and_preserve_explicit_clears() {
        assert_eq!(
            section_patch("risks", "add", "  Existing  ", Some(" Next "))
                .ok()
                .unwrap()
                .risks
                .as_deref(),
            Some("Existing\n- Next")
        );
        assert_eq!(
            section_patch("goal", "set", "Old", Some(" New "))
                .ok()
                .unwrap()
                .goal
                .as_deref(),
            Some("New")
        );
        assert_eq!(
            section_patch("context", "remove", "Private", None)
                .ok()
                .unwrap()
                .context
                .as_deref(),
            Some("")
        );
        assert!(section_patch("goal", "answer", "Old", Some(" ")).is_err());
        let text = render(
            &json!({"plan_id":"p","risks":"- Network failure","user_flows":[{"title":"Retry","steps":[{"text":"Inspect saved delivery"}],"expected_outcome":"No duplicate"}]}),
        );
        assert!(text.contains("Risks: - Network failure"));
        assert!(text.contains("1. Inspect saved delivery"));
    }
    #[test]
    fn plan_creation_requires_goal_and_project_and_preserves_typed_flows() {
        assert!(create(&invocation(&[("title", json!("Plan"))])).is_err());
        let flow = json!([{"flow_id":"flow-a","title":"Flow","steps":[{"step_id":"step-a","text":"Do action"}],"expected_outcome":"Result"}]);
        let plan = create(&invocation(&[
            ("goal", json!("Ship native workspace")),
            ("project", json!(["engineering", "design"])),
            ("user-flows", json!(flow.to_string())),
        ]))
        .ok()
        .unwrap();
        assert_eq!(plan.title, "Ship native workspace");
        assert_eq!(plan.linked_project_ids, ["engineering", "design"]);
        assert_eq!(plan.user_flows[0].steps[0].text, "Do action");
    }
    #[test]
    fn plan_edits_preserve_absent_and_clear_fields_and_reject_unported_options() {
        let value = patch(&invocation(&[
            ("chat", Value::Null),
            ("focus", Value::Null),
            ("scope-out", json!("")),
        ]))
        .ok()
        .unwrap();
        assert_eq!(value.primary_chat_id, Some(None));
        assert_eq!(value.planner_focus_id, Some(None));
        assert_eq!(value.scope_out, Some(String::new()));
        assert!(value.goal.is_none());
        assert!(
            create(&invocation(&[(
                "summary",
                json!("private unsupported field")
            )]))
            .is_err()
        );
    }
    #[test]
    fn plan_task_delegation_preserves_task_options_and_canonical_plan_id() {
        let mut command = invocation(&[("priority", json!("high"))]);
        command.path = vec!["plans".into(), "tasks".into(), "create".into()];
        command.positionals = vec!["plan-short-id".into(), "Task title".into()];
        let task = delegated(&command, &json!({"plan_id":"canonical-plan-id"}))
            .ok()
            .unwrap();
        assert_eq!(task.path, ["tasks", "create"]);
        assert_eq!(task.positionals, ["Task title"]);
        assert_eq!(task.text("plan"), Some("canonical-plan-id"));
        assert_eq!(task.text("priority"), Some("high"));
    }
    #[test]
    fn original_plan_task_project_links_delegate_task_and_project_without_swapping_plan() {
        for operation in ["add-to-project", "remove-from-project"] {
            let command = super::super::parse_from([
                "openmates",
                "plans",
                "tasks",
                "TASK-27",
                "PLAN-42",
                operation,
                "project-uuid",
                "--personal",
            ])
            .unwrap()
            .invocation
            .unwrap();
            assert!(supported(&command));
            assert_eq!(
                input::positional(&command, 0, "Plan ID").ok().unwrap(),
                "PLAN-42"
            );
            let task = delegated(&command, &json!({"plan_id":"canonical-plan-uuid"}))
                .ok()
                .unwrap();
            assert_eq!(task.path, ["tasks", operation]);
            assert_eq!(task.positionals, ["TASK-27", "project-uuid"]);
            assert_eq!(task.text("plan"), Some("canonical-plan-uuid"));
            assert!(task.boolean("personal"));
        }
    }
}
