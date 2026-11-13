//! Receipt decision of an offline sync batch (port of `decideOfflineBatchReceipt`).
//!
//! spec: specifications/features/chats#chats.message.identity-idempotent
use super::protocol;
use serde_json::{Value, json};
use std::collections::HashSet;

fn strings(value: &Value, key: &str) -> Result<Vec<String>, String> {
    value.get(key).and_then(Value::as_array).ok_or("protocol")?.iter()
        .map(|item| item.as_str().map(str::to_string).ok_or_else(|| "protocol".to_string()))
        .collect()
}

/// `{changeIds, terminalConflictDeleteIds, successfulIds, counts?}` -> `{accepted, retiredConflictIds}`.
pub fn offline_batch_receipt_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let (ids, terminal, successes) = (
        strings(&value, "changeIds")?, strings(&value, "terminalConflictDeleteIds")?,
        strings(&value, "successfulIds")?,
    );
    // The batch is a Set: first occurrence order, no duplicates.
    let mut batch: Vec<&String> = Vec::new();
    let mut batch_set: HashSet<&String> = HashSet::new();
    for id in &ids {
        if batch_set.insert(id) {
            batch.push(id);
        }
    }
    let accepted: Vec<&String> = successes.iter().filter(|id| batch_set.contains(id)).collect();
    let counts = value.get("counts").filter(|counts| !counts.is_null());
    let mut retired: Vec<&String> = Vec::new();
    if let Some(counts) = counts {
        let number = |key: &str| counts.get(key).and_then(Value::as_f64);
        let (processed, errors, conflicts) = (number("processed"), number("errors"), number("conflicts"));
        let unique: HashSet<&String> = successes.iter().collect();
        let missing: Vec<&String> = batch.iter().copied().filter(|id| !unique.contains(*id)).collect();
        let size = batch.len() as f64;
        let exact = errors == Some(0.0) && conflicts == Some(1.0)
            && processed.is_some_and(|p| p.fract() == 0.0 && p == size - 1.0)
            && successes.len() == unique.len()
            && unique.len() as f64 == size - 1.0
            && unique.iter().all(|id| batch_set.contains(*id))
            && missing.len() == 1
            && terminal.contains(missing[0]);
        if exact {
            retired = missing;
        }
    }
    Ok(json!({"accepted": accepted, "retiredConflictIds": retired}).to_string())
}
