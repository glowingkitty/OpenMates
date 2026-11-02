//! Thin source-list parsing/presentation. Resolution and name-only decryption
//! belong to the shared SDK; encrypted metadata never enters the output value.
use super::super::global_history::js_string;
use super::*;

fn selector(i: &Invocation) -> Result<&str, CliError> {
    check(i, &[])?;
    i.positionals
        .first()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| CliError::Contract {
            code: "command_failed",
            message: "Missing project.".into(),
        })
}
fn nullish(row: &Value, field: &str, default: Value) -> Value {
    row.get(field)
        .filter(|value| !value.is_null())
        .cloned()
        .unwrap_or(default)
}
/// Keep the exact TS safeProjectSources six-field allowlist. Core's decoded
/// records may still carry encrypted metadata and future protocol fields.
fn presentation(project_id: &str, rows: &[Value]) -> Result<Value, CliError> {
    let mut sources = Vec::with_capacity(rows.len());
    for row in rows {
        let source_id = row["source_id"]
            .as_str()
            .ok_or(CliError::Client(Error::Protocol))?;
        let source_type = row["source_type"]
            .as_str()
            .ok_or(CliError::Client(Error::Protocol))?;
        sources.push(json!({
            "source_id":source_id,
            "source_type":source_type,
            "display_name":row["display_name"].as_str().unwrap_or(""),
            "capabilities":nullish(row,"capabilities",json!([])),
            "status":nullish(row,"status",json!("offline")),
            "ownership_label":nullish(row,"ownership_label",Value::Null),
        }));
    }
    Ok(json!({"project_id":project_id,"sources":sources}))
}
fn list_text(value: &Value) -> String {
    let rows = value["sources"]
        .as_array()
        .expect("private source-list projection");
    if rows.is_empty() {
        return "No Project sources.".into();
    }
    rows.iter()
        .map(|row| {
            format!(
                "{}  {}  {}",
                js_string(&row["source_id"]),
                js_string(&row["display_name"]),
                js_string(&row["status"]),
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}
pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    let selector = selector(i)?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let listed = service.list_sources_decoded_names(selector).await?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let value = presentation(&listed.project_id, &listed.sources)?;
    let text = list_text(&value);
    output(i, value, text)
}

#[cfg(test)]
#[path = "sources_tests.rs"]
mod tests;

/// `projects sources remove <project> --source <id> [--confirm <id>]`, with the
/// legacy exact-ID confirmation (flag, else an interactive typed ID).
pub(super) async fn remove(
    i: &Invocation,
    service: &mut Projects<'_>,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    check(i, &["source", "confirm"])?;
    let contract = |code: &'static str, message: String| CliError::Contract { code, message };
    let non_interactive = i.boolean("json") || !std::io::IsTerminal::is_terminal(&std::io::stdin());
    if non_interactive && i.text("confirm").is_none() {
        return Err(contract(
            "confirmation_required",
            "Project source removal requires --confirm <source-id>.".into(),
        ));
    }
    let selector = i
        .positionals
        .first()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| contract("command_failed", "Missing project.".into()))?;
    let source = i
        .text("source")
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| contract("command_failed", "Missing --source <source-id>.".into()))?;
    let confirmation = match i.text("confirm") {
        Some(value) if value == source => value.to_owned(),
        Some(_) => {
            return Err(contract(
                "confirmation_mismatch",
                format!("Project source removal confirmation must exactly match '{source}'."),
            ));
        }
        None => {
            use std::io::Write;
            let mut stdout = std::io::stdout();
            write!(stdout, "Project source removal. Type {source} to continue: ")
                .and_then(|()| stdout.flush())
                .map_err(|_| Error::Io)?;
            let answer = tokio::task::spawn_blocking(|| {
                let mut line = String::new();
                std::io::stdin().read_line(&mut line).map(|_| line)
            })
            .await
            .map_err(|_| Error::Io)?
            .map_err(|_| Error::Io)?;
            if answer.trim() != source {
                return Err(contract(
                    "confirmation_cancelled",
                    "Project source removal cancelled.".into(),
                ));
            }
            source.to_owned()
        }
    };
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let value = service.delete_source(selector, source, &confirmation).await?;
    output(i, value, format!("Project source removed: {source}"))
}
