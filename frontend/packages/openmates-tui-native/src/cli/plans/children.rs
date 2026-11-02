//! Native Plan child authoring. Only explicitly mapped fields reach typed SDK inputs.
use super::*;
use openmates_sdk::work::{
    DependencyTarget, PlanAssumptionInput, PlanCriterionInput, PlanLearningInput,
    PlanLearningSelection, PlanVerificationEvidence, PlanVerificationInput, WorkKind,
};
use serde::de::DeserializeOwned;

pub(super) fn supported(i: &Invocation) -> bool {
    if i.path.len() != 3 {
        return false;
    }
    let family = i.path[1].as_str();
    let action = i.path[2].as_str();
    match family {
        "dependencies" => ["list", "add", "remove"].contains(&action),
        "revisions" => ["list", "status", "submit-for-review"].contains(&action),
        "assumptions" => ["list", "create", "add", "update"].contains(&action),
        "success-criteria" | "criterion" | "criteria" => {
            ["add", "create", "edit", "update", "remove", "delete"].contains(&action)
        }
        "learning" | "learnings" => [
            "list",
            "show",
            "add",
            "create",
            "edit",
            "update",
            "remove",
            "delete",
            "create-tasks",
        ]
        .contains(&action),
        "check" | "checks" | "verification" => [
            "add", "create", "edit", "update", "remove", "delete", "evidence", "record",
        ]
        .contains(&action),
        _ => false,
    }
}
fn typed<T: DeserializeOwned>(value: Value) -> Result<T, CliError> {
    serde_json::from_value(value).map_err(|_| CliError::Invalid("Invalid typed Plan input.".into()))
}
fn fields(i: &Invocation, mapping: &[(&str, &[&str])], extra: &[&str]) -> Result<Value, CliError> {
    let mut allowed = vec!["status", "chat", "project", "active"];
    allowed.extend_from_slice(extra);
    for (_, aliases) in mapping {
        allowed.extend_from_slice(aliases);
    }
    check(i, &allowed)?;
    let mut value = json!({});
    for (field, aliases) in mapping {
        for alias in *aliases {
            if let Some(input) = i.flags.get(*alias) {
                if value.get(*field).is_some() {
                    return Err(CliError::Invalid(format!(
                        "Use only one alias for {field}."
                    )));
                }
                value[*field] = input.clone();
            }
        }
    }
    Ok(value)
}
fn child_id<'a>(i: &'a Invocation, names: &[&str]) -> Result<&'a str, CliError> {
    for name in names {
        if let Some(value) = input::text(i, name)?
            && !value.trim().is_empty()
        {
            return Ok(value);
        }
    }
    input::positional(i, 1, "Plan child ID")
}
fn required_text(i: &Invocation, name: &str) -> Result<String, CliError> {
    let positional = i
        .positionals
        .iter()
        .skip(1)
        .cloned()
        .collect::<Vec<_>>()
        .join(" ");
    let value = input::text(i, name)?.unwrap_or(&positional).trim();
    if value.is_empty() {
        Err(CliError::Invalid(format!("Provide --{name} <text>.")))
    } else {
        Ok(value.into())
    }
}
fn required_flag(i: &Invocation, v: &mut Value, field: &str) {
    if i.boolean("required") {
        v[field] = json!(true)
    } else if i.boolean("optional") {
        v[field] = json!(false)
    }
}
fn list_field(i: &Invocation, v: &mut Value, field: &str, aliases: &[&str], create: bool) {
    if create || aliases.iter().any(|name| i.has(name)) {
        v[field] = json!(input::ids(i, aliases));
    }
}
fn number_fields(v: &mut Value, fields: &[&str]) -> Result<(), CliError> {
    for field in fields {
        if let Some(value) = v.get(*field) {
            let number = value
                .as_str()
                .and_then(|s| s.parse::<f64>().ok())
                .filter(|n| n.is_finite())
                .ok_or_else(|| CliError::Invalid(format!("--{field} requires a finite number.")))?;
            v[*field] = json!(number);
        }
    }
    Ok(())
}
fn enum_field(v: &Value, field: &str, allowed: &[&str]) -> Result<(), CliError> {
    if let Some(value) = v.get(field).filter(|v| !v.is_null())
        && !value.as_str().is_some_and(|s| allowed.contains(&s))
    {
        return Err(CliError::Invalid(format!("Unknown Plan {field}.")));
    }
    Ok(())
}
fn proof(i: &Invocation) -> Result<Option<String>, CliError> {
    let mut values = vec![];
    for id in input::ids(i, &["proof-embed"]) {
        values.push(json!({"kind":"embed","embed_id":id}));
    }
    for url in input::ids(i, &["proof-url"]) {
        let url = url::Url::parse(&url)
            .ok()
            .filter(|u| u.scheme() == "https")
            .ok_or_else(|| CliError::Invalid("Assumption proof URLs must use HTTPS.".into()))?;
        values.push(json!({"kind":"url","url":url.as_str()}));
    }
    for file in input::ids(i, &["proof-file"]) {
        let parts = file.split(':').collect::<Vec<_>>();
        let path = parts[0];
        if path.is_empty()
            || path.starts_with('/')
            || path.starts_with('\\')
            || path.split(['/', '\\']).any(|p| p == "..")
            || parts.len() > 3
        {
            return Err(CliError::Invalid(
                "Assumption proof file paths must be repository-relative.".into(),
            ));
        }
        let mut value = json!({"kind":"file","path":path});
        let mut start = 1;
        for (index, field) in [(1, "start_line"), (2, "end_line")] {
            if let Some(raw) = parts.get(index).filter(|s| !s.is_empty()) {
                let line = raw
                    .parse::<u32>()
                    .ok()
                    .filter(|n| *n >= start)
                    .ok_or_else(|| {
                        CliError::Invalid("Proof line ranges must be positive and ordered.".into())
                    })?;
                value[field] = json!(line);
                start = line;
            }
        }
        values.push(value);
    }
    if values.is_empty() {
        Ok(None)
    } else {
        Ok(Some(
            serde_json::to_string(&values).map_err(|_| CliError::Client(Error::Protocol))?,
        ))
    }
}
fn assumption(i: &Invocation, create: bool) -> Result<PlanAssumptionInput, CliError> {
    let map = &[
        ("assumption_id", &["id"][..]),
        ("status", &["status"]),
        ("linked_sub_chat_id", &["sub-chat"]),
        ("corrected_text", &["corrected"]),
    ];
    let mut v = fields(
        i,
        map,
        &[
            "assumption",
            "text",
            "proof-embed",
            "proof-url",
            "proof-file",
        ],
    )?;
    if create {
        v["text"] = json!(required_text(i, "text")?);
    } else if i.has("text") || i.has("id") {
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "The server does not support editing assumption text or identity.".into(),
        });
    }
    if let Some(sources) = proof(i)? {
        v["sources"] = json!(sources)
    }
    typed(v)
}
fn criterion(i: &Invocation, create: bool) -> Result<PlanCriterionInput, CliError> {
    let mut v = fields(
        i,
        &[
            ("criterion_id", &["id"]),
            ("type", &["type"]),
            ("status", &["status"]),
        ],
        &[
            "criterion",
            "text",
            "required",
            "optional",
            "task",
            "tasks",
            "verification",
            "verifications",
        ],
    )?;
    if create {
        v["text"] = json!(required_text(i, "text")?);
        required_flag(i, &mut v, "required");
        list_field(i, &mut v, "linked_task_ids", &["task", "tasks"], true);
    } else {
        for flag in [
            "id", "type", "text", "required", "optional", "task", "tasks",
        ] {
            if i.has(flag) {
                return Err(CliError::Unsupported {
                    command: i.command_path(),
                    reason: format!("The server does not support criterion PATCH --{flag}."),
                });
            }
        }
    }
    list_field(
        i,
        &mut v,
        "verification_ids",
        &["verification", "verifications"],
        create,
    );
    typed(v)
}
fn learning(i: &Invocation, create: bool) -> Result<PlanLearningInput, CliError> {
    let mut v = fields(
        i,
        &[
            ("learning_id", &["id"]),
            ("type", &["type"]),
            ("target_kind", &["target", "target-kind"]),
            ("status", &["status"]),
            ("severity", &["severity"]),
            ("confidence", &["confidence"]),
            ("applied_task_id", &["applied-task"]),
            ("title", &["title"]),
            ("observation", &["observation"]),
            ("root_cause", &["root-cause"]),
            ("suggested_change", &["change", "suggested-change"]),
            ("evidence_summary", &["evidence", "summary"]),
            ("task_draft", &["task-draft"]),
            ("rejection_reason", &["rejection-reason"]),
        ],
        &["learning", "task", "tasks", "check", "checks"],
    )?;
    if create {
        v["title"] = json!(required_text(i, "title")?);
        if v.get("type").is_none() {
            v["type"] = json!("workflow_improvement")
        };
        if v.get("target_kind").is_none() {
            v["target_kind"] = json!("workflow")
        }
    } else {
        for name in ["id", "type", "target", "target-kind"] {
            if i.has(name) {
                return Err(CliError::Unsupported {
                    command: i.command_path(),
                    reason: format!("Learning edits do not support --{name}."),
                });
            }
        }
    }
    enum_field(
        &v,
        "type",
        &["workflow_improvement", "agent_instruction_improvement"],
    )?;
    enum_field(
        &v,
        "target_kind",
        &["workflow", "project_agent_instructions"],
    )?;
    enum_field(
        &v,
        "status",
        &[
            "draft",
            "proposed",
            "accepted",
            "applied",
            "rejected",
            "duplicate",
            "merged",
        ],
    )?;
    for field in ["severity", "confidence"] {
        enum_field(&v, field, &["low", "medium", "high"])?;
    }
    list_field(i, &mut v, "linked_task_ids", &["task", "tasks"], create);
    list_field(i, &mut v, "linked_check_ids", &["check", "checks"], create);
    typed(v)
}
const CHECK_STATUS: &[&str] = &[
    "proposed",
    "pending",
    "passed",
    "failed",
    "passed_unexpectedly",
    "skipped",
    "skipped_with_reason",
    "not_applicable",
    "waived",
];
fn verification(i: &Invocation, create: bool) -> Result<PlanVerificationInput, CliError> {
    let mut v = fields(
        i,
        &[
            ("verification_id", &["id"]),
            ("linked_task_id", &["task"]),
            ("run_id", &["run"]),
            ("kind", &["kind", "type"]),
            ("phase", &["phase"]),
            ("status", &["status"]),
            ("lifecycle_status", &["lifecycle", "lifecycle-status"]),
            ("source_hash", &["source-hash"]),
            ("score", &["score"]),
            ("threshold", &["threshold"]),
            ("confidence", &["confidence"]),
            ("linked_sub_chat_id", &["sub-chat"]),
            ("source_embed_id", &["embed", "source-embed"]),
            ("runner_kind", &["runner", "runner-kind"]),
            ("description", &["description"]),
            ("command", &["command"]),
            ("evaluation_prompt", &["prompt", "evaluation-prompt"]),
            (
                "evaluator_instructions",
                &["instructions", "evaluator-instructions"],
            ),
            ("expected_result", &["expected", "expected-result"]),
            ("source_path", &["path", "source-path"]),
            ("red_phase_reason", &["red-phase-reason"]),
        ],
        &[
            "verification",
            "check",
            "required",
            "optional",
            "cover",
            "covers",
        ],
    )?;
    if create {
        if v.get("kind").is_none() {
            return Err(CliError::Invalid(
                "Creating a check requires --kind.".into(),
            ));
        }
        if v.get("status").is_none() {
            v["status"] = json!("pending")
        }
    }
    enum_field(&v, "kind", &["manual_check", "command", "ai_evaluator"])?;
    enum_field(&v, "status", CHECK_STATUS)?;
    number_fields(&mut v, &["score", "threshold"])?;
    required_flag(i, &mut v, "required_for_done");
    list_field(i, &mut v, "covers", &["cover", "covers"], create);
    typed(v)
}
fn evidence(i: &Invocation) -> Result<PlanVerificationEvidence, CliError> {
    let mut v = fields(
        i,
        &[
            ("status", &["status"]),
            ("score", &["score"]),
            ("threshold", &["threshold"]),
            ("confidence", &["confidence"]),
            ("run_id", &["run"]),
            ("result_summary", &["summary"]),
            ("required_fixes", &["required-fixes"]),
        ],
        &["verification", "check"],
    )?;
    if v.get("status").is_none() {
        return Err(CliError::Invalid(
            "Recording evidence requires --status.".into(),
        ));
    }
    enum_field(&v, "status", CHECK_STATUS)?;
    number_fields(&mut v, &["score", "threshold"])?;
    typed(v)
}
fn dependency(i: &Invocation) -> Result<DependencyTarget, CliError> {
    let raw = input::text(i, "target")?
        .or(i.positionals.get(1).map(String::as_str))
        .ok_or_else(|| CliError::Invalid("Provide --target task:<id> or plan:<id>.".into()))?;
    let (kind, id) = raw
        .split_once(':')
        .filter(|(_, id)| !id.trim().is_empty())
        .ok_or_else(|| CliError::Invalid("Invalid dependency target.".into()))?;
    Ok(DependencyTarget {
        kind: match kind {
            "task" => WorkKind::Task,
            "plan" => WorkKind::Plan,
            _ => {
                return Err(CliError::Invalid(
                    "Dependency target must be task:<id> or plan:<id>.".into(),
                ));
            }
        },
        id: id.into(),
    })
}
pub(super) async fn execute(
    i: &Invocation,
    service: &mut Plans<'_>,
) -> Result<CliOutput, CliError> {
    let plan = input::positional(i, 0, "Plan ID")?;
    let family = i.path[1].as_str();
    let action = i.path[2].as_str();
    let create = ["add", "create"].contains(&action);
    let delete = ["remove", "delete"].contains(&action);
    let value = match family {
        "dependencies" => {
            check(i, &["target", "project", "chat", "active"])?;
            match action {
                "list" => service.list_dependencies(plan).await?,
                "add" => service.add_dependency(plan, &dependency(i)?).await?,
                _ => service.remove_dependency(plan, &dependency(i)?).await?,
            }
        }
        "revisions" => {
            check(i, &["project", "chat", "active"])?;
            match action {
                "list" => json!({"revisions":service.list_revisions(plan).await?}),
                "status" => json!({"approval":service.approval_status(plan).await?}),
                _ => service.submit_for_review(plan).await?,
            }
        }
        "assumptions" => match action {
            "list" => {
                check(i, &["project", "chat", "active"])?;
                json!({"assumptions":service.list_assumptions(plan).await?})
            }
            _ if create => {
                json!({"assumption":service.create_assumption(plan,assumption(i,true)?).await?})
            }
            _ => {
                json!({"assumption":service.update_assumption(plan,child_id(i,&["assumption"])?,assumption(i,false)?).await?})
            }
        },
        "success-criteria" | "criterion" | "criteria" => {
            if delete {
                check(i, &["criterion", "project", "chat", "active"])?;
                service
                    .delete_criterion(plan, child_id(i, &["criterion"])?)
                    .await?
            } else if create {
                json!({"criterion":service.create_criterion(plan,criterion(i,true)?).await?})
            } else {
                json!({"criterion":service.update_criterion(plan,child_id(i,&["criterion"])?,criterion(i,false)?).await?})
            }
        }
        "learning" | "learnings" => match action {
            "list" => {
                check(i, &["project", "chat", "active"])?;
                json!({"learnings":service.list_learnings(plan).await?})
            }
            "show" => {
                check(i, &["learning", "project", "chat", "active"])?;
                json!({"learning":service.show_learning(plan,child_id(i,&["learning"])?).await?})
            }
            "create-tasks" => {
                check(
                    i,
                    &["learning", "learnings", "all", "project", "chat", "active"],
                )?;
                let mut ids = input::ids(i, &["learning", "learnings"]);
                ids.extend(i.positionals.iter().skip(1).cloned());
                service
                    .create_learning_tasks(
                        plan,
                        PlanLearningSelection {
                            learning_ids: ids,
                            all: i.boolean("all"),
                        },
                    )
                    .await?
            }
            _ if delete => {
                check(i, &["learning", "project", "chat", "active"])?;
                service
                    .delete_learning(plan, child_id(i, &["learning"])?)
                    .await?
            }
            _ if create => {
                json!({"learning":service.create_learning(plan,learning(i,true)?).await?})
            }
            _ => {
                json!({"learning":service.update_learning(plan,child_id(i,&["learning"])?,learning(i,false)?).await?})
            }
        },
        _ => {
            if delete {
                check(i, &["verification", "check", "project", "chat", "active"])?;
                service
                    .delete_verification(plan, child_id(i, &["verification", "check"])?)
                    .await?
            } else if ["evidence", "record"].contains(&action) {
                json!({"verification":service.add_verification_evidence(plan,child_id(i,&["verification","check"])?,evidence(i)?).await?})
            } else if create {
                json!({"verification":service.create_verification(plan,verification(i,true)?).await?})
            } else {
                json!({"verification":service.update_verification(plan,child_id(i,&["verification","check"])?,verification(i,false)?).await?})
            }
        }
    };
    let text = render(i, &value);
    output(i, value, text)
}
fn render(i: &Invocation, value: &Value) -> String {
    if let Some(url) = value["review_url"].as_str() {
        return format!("Plan revision submitted for web review: {url}");
    }
    fn row(value: &Value) -> String {
        let id = [
            "short_id",
            "learning_id",
            "assumption_id",
            "criterion_id",
            "verification_id",
            "revision_id",
            "task_id",
            "target_ref",
            "source_ref",
        ]
        .iter()
        .find_map(|key| value[*key].as_str())
        .unwrap_or("");
        let text = value["title"]
            .as_str()
            .or(value["text"].as_str())
            .or(value["reason"].as_str())
            .unwrap_or("");
        let status = value["status"]
            .as_str()
            .or(value["approval_state"].as_str());
        format!(
            "{id}  {text}{}",
            status
                .map(|status| format!("  [{status}]"))
                .unwrap_or_default()
        )
        .trim()
        .to_owned()
    }
    let mut lines = vec![];
    for key in [
        "assumptions",
        "learnings",
        "revisions",
        "tasks",
        "dependencies",
        "blockers",
        "skipped",
    ] {
        if let Some(rows) = value[key].as_array() {
            lines.push(format!("{key}: {}", rows.len()));
            lines.extend(rows.iter().map(row));
        }
    }
    for key in ["assumption", "criterion", "learning", "verification"] {
        if value[key].is_object() {
            lines.push(format!("Plan {key}: {}", row(&value[key])));
            for field in [
                "observation",
                "root_cause",
                "suggested_change",
                "evidence_summary",
                "task_draft",
                "rejection_reason",
            ] {
                if let Some(text) = value[key][field].as_str().filter(|text| !text.is_empty()) {
                    lines.push(format!("{field}: {text}"));
                }
            }
        }
    }
    if let Some(fields) = value["approval"].as_object() {
        for (key, v) in fields {
            if !v.is_object() && !v.is_array() {
                lines.push(format!("{key}: {v}"));
            }
        }
    }
    if lines.is_empty() {
        format!("{} completed.", i.command_path())
    } else {
        lines.join("\n")
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn i(f: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: vec!["plans".into(), "checks".into(), "edit".into()],
            positionals: vec!["PLAN-42".into(), "check-a".into()],
            flags: f.iter().map(|(k, v)| (k.to_string(), v.clone())).collect(),
        }
    }
    #[test]
    fn typed_children_preserve_nulls_fractions_and_reject_unknown_or_nonfinite() {
        let v = verification(
            &i(&[
                ("score", json!("0.75")),
                ("confidence", Value::Null),
                ("source-hash", Value::Null),
            ]),
            false,
        )
        .ok()
        .unwrap();
        assert_eq!(v.score, Some(Some(0.75)));
        assert_eq!(v.confidence, Some(None));
        assert_eq!(v.source_hash, Some(None));
        assert!(verification(&i(&[("score", json!("NaN"))]), false).is_err());
        assert!(verification(&i(&[("password", json!("private"))]), false).is_err());
        assert!(evidence(&i(&[])).is_err());
    }
    #[test]
    fn assumption_proof_is_typed_https_and_relative_with_ordered_lines() {
        let v = proof(&i(&[
            ("proof-file", json!("src/lib.rs:2:8")),
            ("proof-url", json!("https://example.com/proof")),
        ]))
        .ok()
        .unwrap()
        .unwrap();
        let v: Value = serde_json::from_str(&v).unwrap();
        assert_eq!(v[1]["start_line"], 2);
        assert!(proof(&i(&[("proof-file", json!("../private:1:2"))])).is_err());
        assert!(proof(&i(&[("proof-url", json!("http://example.com"))])).is_err());
        assert!(proof(&i(&[("proof-file", json!("src/lib.rs:8:2"))])).is_err());
    }
    #[test]
    fn unsupported_criterion_patch_cannot_report_ignored_changes() {
        assert!(criterion(&i(&[("required", json!(true))]), false).is_err());
        let v = criterion(
            &i(&[
                ("status", json!("satisfied")),
                ("verification", json!("check-a,check-b")),
            ]),
            false,
        )
        .ok()
        .unwrap();
        assert_eq!(v.verification_ids.unwrap(), ["check-a", "check-b"]);
    }
}
