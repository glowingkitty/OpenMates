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
