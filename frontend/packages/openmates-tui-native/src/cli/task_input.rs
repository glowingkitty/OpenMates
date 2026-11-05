//! Native validation for the Task CLI. Every recognized option is either mapped
//! into a typed SDK payload or rejected explicitly by the command handler.
use super::{CliError, Invocation};
use openmates_sdk::work::{ExternalChat, TaskCreate, TaskFilters, TaskPatch};
use serde_json::Value;
use std::collections::BTreeSet;
pub(super) const SCOPE: &[&str] = &[
    "personal",
    "team",
    "status",
    "chat",
    "project",
    "plan",
    "label",
    "labels",
    "tag",
    "tags",
    "external-chat",
    "external-chat-title",
    "priority",
];
const GLOBALS: &[&str] = &[
    "json",
    "profile",
    "api-url",
    "api-key",
    "state-dir",
    "encrypted-vault",
    "demo",
];
const REPEATED: &[&str] = &[
    "label",
    "labels",
    "tag",
    "tags",
    "add-label",
    "add-labels",
    "add-tag",
    "add-tags",
    "remove-label",
    "remove-labels",
    "remove-tag",
    "remove-tags",
    "project",
    "projects",
];
pub(super) fn check_flags(invocation: &Invocation, allowed: &[&str]) -> Result<(), CliError> {
    for (key, value) in &invocation.flags {
        if !GLOBALS.contains(&key.as_str())
            && !SCOPE.contains(&key.as_str())
            && !allowed.contains(&key.as_str())
        {
            return Err(CliError::Unsupported {
                command: invocation.command_path(),
                reason: format!("Option --{key} is not ported for this native Task operation."),
            });
        }
        if value.is_array() && !REPEATED.contains(&key.as_str()) {
            return Err(CliError::Invalid(format!(
                "Option --{key} must be supplied once."
            )));
        }
    }
    Ok(())
}
pub(super) fn text<'a>(invocation: &'a Invocation, key: &str) -> Result<Option<&'a str>, CliError> {
    match invocation.flags.get(key) {
        None => Ok(None),
        Some(Value::String(value)) => Ok(Some(value)),
        Some(Value::Null) => Ok(None),
        _ => Err(CliError::Invalid(format!(
            "Option --{key} requires a value."
        ))),
    }
}
pub(super) fn required<'a>(invocation: &'a Invocation, key: &str) -> Result<&'a str, CliError> {
    text(invocation, key)?
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| CliError::Invalid(format!("Missing --{key}.")))
}
pub(super) fn positional<'a>(
    invocation: &'a Invocation,
    index: usize,
    label: &str,
) -> Result<&'a str, CliError> {
    invocation
        .positionals
        .get(index)
        .map(String::as_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| CliError::Invalid(format!("Missing {label}.")))
}
pub(super) fn labels(invocation: &Invocation, names: &[&str]) -> Vec<String> {
    let mut seen = BTreeSet::new();
    let mut values = vec![];
    for name in names {
        for raw in invocation.values(name) {
            for part in raw.split([',', '\n']) {
                let value = part
                    .split_whitespace()
                    .collect::<Vec<_>>()
                    .join(" ")
                    .to_lowercase();
                if !value.is_empty() && seen.insert(value.clone()) {
                    values.push(value);
                }
            }
        }
    }
    values
}
pub(super) fn ids(invocation: &Invocation, names: &[&str]) -> Vec<String> {
    let mut seen = BTreeSet::new();
    let mut values = vec![];
    for name in names {
        for raw in invocation.values(name) {
            for part in raw.split([',', '\n']) {
                let value = part.trim();
                if !value.is_empty() && seen.insert(value.to_owned()) {
                    values.push(value.to_owned());
                }
            }
        }
    }
    values
}
pub(super) fn priority(value: &str) -> Result<u8, CliError> {
    match value {
        "none" => Ok(0),
        "low" => Ok(1),
        "medium" => Ok(2),
        "high" => Ok(3),
        "urgent" => Ok(4),
        _ => value
            .parse::<u8>()
            .ok()
            .filter(|value| *value <= 4)
            .ok_or_else(|| {
                CliError::Invalid(
                    "Task priority must be none, low, medium, high, urgent or 0–4.".into(),
                )
            }),
    }
}
pub(super) fn status(value: &str) -> Result<String, CliError> {
    if ["backlog", "todo", "in_progress", "blocked", "done"].contains(&value) {
        Ok(value.into())
    } else {
        Err(CliError::Invalid("Unknown Task status.".into()))
    }
}
pub(super) fn external(invocation: &Invocation) -> Result<Option<ExternalChat>, CliError> {
    let Some(value) = text(invocation, "external-chat")? else {
        if invocation.has("external-chat-title") {
            return Err(CliError::Invalid(
                "--external-chat-title requires --external-chat.".into(),
            ));
        }
        return Ok(None);
    };
    super::codex::parse_external(
        value,
        text(invocation, "external-chat-title")?.unwrap_or(""),
    )
    .map(Some)
}
pub(super) fn filters(
    invocation: &Invocation,
    team: Option<String>,
    mutation: bool,
) -> Result<TaskFilters, CliError> {
    if mutation {
        return Ok(TaskFilters {
            team_id: team,
            personal: invocation.boolean("personal"),
            ..Default::default()
        });
    }
    Ok(TaskFilters {
        team_id: team,
        personal: invocation.boolean("personal"),
        status: text(invocation, "status")?.map(status).transpose()?,
        chat_id: text(invocation, "chat")?.map(str::to_owned),
        project_id: text(invocation, "project")?.map(str::to_owned),
        plan_id: text(invocation, "plan")?.map(str::to_owned),
        labels: labels(invocation, &["label", "labels", "tag", "tags"]),
        external_chat: external(invocation)?,
        priority: text(invocation, "priority")?.map(priority).transpose()?,
        ..Default::default()
    })
}
fn due(value: &str) -> Result<i64, CliError> {
    if let Ok(number) = value.parse::<f64>()
        && number.is_finite()
        && number > 0.0
        && number < (i64::MAX as f64)
    {
        return Ok(number.floor() as i64);
    }
    if let Ok(date) =
        time::OffsetDateTime::parse(value, &time::format_description::well_known::Rfc3339)
    {
        return Ok(date.unix_timestamp());
    }
    let format = time::format_description::parse_borrowed::<2>("[year]-[month]-[day]")
        .map_err(|_| CliError::Invalid("Date parser is unavailable.".into()))?;
    time::Date::parse(value, &format)
        .map(|date| date.midnight().assume_utc().unix_timestamp())
        .map_err(|_| {
            CliError::Invalid(
                "--due requires epoch seconds, an ISO date, or an RFC3339 timestamp.".into(),
            )
        })
}
fn assign(invocation: &Invocation) -> Result<Option<String>, CliError> {
    let value = text(invocation, "assign")?.or(text(invocation, "assignee")?);
    if let Some(value) = value
        && ![
            "user",
            "openmates",
            "codex",
            "external_ai",
            "external-ai",
            "unassigned",
        ]
        .contains(&value)
        && !(value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit()))
    {
        return Err(CliError::Invalid("Unknown Task assignee.".into()));
    }
    Ok(value.map(str::to_owned))
}
pub(super) fn create(invocation: &Invocation) -> Result<TaskCreate, CliError> {
    let title = text(invocation, "title")?
        .map(str::to_owned)
        .unwrap_or_else(|| invocation.positionals.join(" ").trim().to_owned());
    if title.is_empty() {
        return Err(CliError::Invalid(
            "Provide a Task title with --title or a positional title.".into(),
        ));
    }
    Ok(TaskCreate {
        title,
        description: text(invocation, "description")?.unwrap_or("").into(),
        slug: text(invocation, "slug")?.map(str::to_owned),
        assign: assign(invocation)?,
        labels: labels(invocation, &["label", "labels", "tag", "tags"]),
        status: text(invocation, "status")?.map(status).transpose()?,
        priority: text(invocation, "priority")?.map(priority).transpose()?,
        due_at: text(invocation, "due")?.map(due).transpose()?,
        primary_chat_id: text(invocation, "chat")?.map(str::to_owned),
        linked_project_ids: ids(invocation, &["project", "projects"]),
        plan_id: text(invocation, "plan")?.map(str::to_owned),
        external_chat: external(invocation)?,
        ..Default::default()
    })
}
pub(super) fn patch(invocation: &Invocation) -> Result<TaskPatch, CliError> {
    let patch = TaskPatch {
        title: text(invocation, "title")?.map(str::to_owned),
        description: text(invocation, "description")?.map(str::to_owned),
        slug: text(invocation, "slug")?.map(str::to_owned),
        assign: assign(invocation)?,
        labels: ["label", "labels", "tag", "tags"]
            .iter()
            .any(|name| invocation.has(name))
            .then(|| labels(invocation, &["label", "labels", "tag", "tags"])),
        add_labels: labels(
            invocation,
            &["add-label", "add-labels", "add-tag", "add-tags"],
        ),
        remove_labels: labels(
            invocation,
            &["remove-label", "remove-labels", "remove-tag", "remove-tags"],
        ),
        status: text(invocation, "status")?.map(status).transpose()?,
        priority: text(invocation, "priority")?.map(priority).transpose()?,
        due_at: invocation
            .has("due")
            .then(|| text(invocation, "due")?.map(due).transpose())
            .transpose()?,
        primary_chat_id: invocation
            .has("chat")
            .then(|| text(invocation, "chat").map(|value| value.map(str::to_owned)))
            .transpose()?,
        plan_id: invocation
            .has("plan")
            .then(|| text(invocation, "plan").map(|value| value.map(str::to_owned)))
            .transpose()?,
        linked_project_ids: ["project", "projects"]
            .iter()
            .any(|name| invocation.has(name))
            .then(|| ids(invocation, &["project", "projects"])),
        external_chat: external(invocation)?.map(Some),
    };
    if patch
        .title
        .as_ref()
        .is_some_and(|title| title.trim().is_empty())
    {
        return Err(CliError::Invalid("Task title cannot be empty.".into()));
    }
    let ignored = [
        "personal",
        "team",
        "json",
        "profile",
        "api-url",
        "api-key",
        "state-dir",
        "encrypted-vault",
        "demo",
    ];
    if !invocation
        .flags
        .keys()
        .any(|key| !ignored.contains(&key.as_str()))
    {
        return Err(CliError::Invalid(
            "Provide at least one Task field to edit.".into(),
        ));
    }
    Ok(patch)
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn invocation(flags: &[(&str, Value)], args: &[&str]) -> Invocation {
        Invocation {
            path: vec!["tasks".into(), "create".into()],
            positionals: args.iter().map(|value| (*value).into()).collect(),
            flags: flags
                .iter()
                .map(|(key, value)| ((*key).into(), value.clone()))
                .collect(),
        }
    }
    #[test]
    fn creation_preserves_repeatable_labels_priority_and_project_membership() {
        let invocation = invocation(
            &[
                ("label", json!([" Critical , Design ", "critical\nFeature"])),
                ("project", json!(["project-a", "project-b"])),
                ("priority", json!("high")),
                ("due", json!("2026-10-22")),
            ],
            &["Native Task"],
        );
        let value = create(&invocation).ok().unwrap();
        assert_eq!(value.title, "Native Task");
        assert_eq!(value.labels, ["critical", "design", "feature"]);
        assert_eq!(value.linked_project_ids, ["project-a", "project-b"]);
        assert_eq!(value.priority, Some(3));
        assert_eq!(value.due_at, Some(1792627200));
    }
    #[test]
    fn edit_distinguishes_clear_from_missing_fields() {
        let value = patch(&invocation(
            &[
                ("chat", Value::Null),
                ("plan", Value::Null),
                ("description", json!("")),
            ],
            &[],
        ))
        .ok()
        .unwrap();
        assert_eq!(value.primary_chat_id, Some(None));
        assert_eq!(value.plan_id, Some(None));
        assert_eq!(value.description, Some(String::new()));
        assert!(value.labels.is_none());
    }
    #[test]
    fn invalid_dates_and_flags_fail_without_disclosing_values() {
        assert!(due("2026-02-30").is_err());
        assert!(due("NaN").is_err());
        assert_eq!(
            due("2026-10-22T02:00:00+02:00").ok(),
            due("2026-10-22").ok()
        );
        assert_eq!(due("1234.8").ok(), Some(1234));
        let command = invocation(&[("unknown-private-option", json!("private-value"))], &[]);
        let error = check_flags(&command, &[]).err().unwrap();
        assert!(!error.to_string().contains("private-value"));
    }
}
