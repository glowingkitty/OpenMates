//! Adopt pending records from the npm CLI's on-disk Task outboxes
//! (`taskMutationDelivery.ts` `TaskMutation`, `taskActivityDelivery.ts`
//! `Delivery`) as native `TaskDelivery` intents. Shared core; the CLI adapter
//! (`openmates-tui-native/src/task_legacy_outbox.rs`) owns file IO and locks.
//!
//! Invariant: the original npm ciphertext is delivered byte-for-byte (same
//! master/Task keys, same random IVs), so backend idempotency and the npm
//! reconciliation fingerprints still hold. Transient `plaintext_*` fields that
//! npm stored for OpenMates-assigned creates are dropped: `execute_delivery`
//! re-derives them from the ciphertext at dispatch. Records whose original
//! Codex caller cannot be proven (creator/assignee provenance) are refused and
//! left in the npm outbox rather than replayed under a different identity.
use super::*;

/// Why an npm outbox record cannot be adopted; the record stays untouched.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LegacyRefusal {
    /// The record shape is not a known npm Task outbox format.
    Malformed,
    /// Codex creator/assignee provenance is not recorded in the npm outbox.
    UnverifiedCaller,
    /// npm refuses these kinds in Team scope; no personal fallback.
    TeamUnsupported,
}
impl LegacyRefusal {
    /// Stable code for CLI notices.
    pub fn code(self) -> &'static str {
        match self {
            Self::Malformed => "legacy_task_outbox_malformed",
            Self::UnverifiedCaller => "legacy_task_outbox_unverified_caller",
            Self::TeamUnsupported => "legacy_task_outbox_team_unsupported",
        }
    }
}

fn hex64(id: &str) -> bool {
    id.len() == 64
        && id
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn without_plaintext(input: &Value) -> Result<Value> {
    let mut map = input.as_object().ok_or(Error::Protocol)?.clone();
    map.retain(|key, _| !key.starts_with("plaintext_"));
    Ok(Value::Object(map))
}

impl Tasks<'_> {
    /// Convert one npm `TaskMutation` (`{kind, taskId, input|version, ownerHash?,
    /// creator?}`) into a native intent bound to this account/scope/caller.
    ///
    /// # Errors
    /// `Ok(Err(refusal))` for records that must stay in the npm outbox;
    /// `Err` for local key/scope failures.
    pub async fn adopt_npm_mutation(
        &mut self,
        mutation: &Value,
        delivery_id: &str,
    ) -> Result<std::result::Result<TaskDelivery, LegacyRefusal>> {
        let Some(task_id) = mutation["taskId"].as_str().map(str::to_owned) else {
            return Ok(Err(LegacyRefusal::Malformed));
        };
        if !hex64(delivery_id) || uuid(&task_id).is_err() {
            return Ok(Err(LegacyRefusal::Malformed));
        }
        let kind = mutation["kind"].as_str().unwrap_or_default();
        if self.filters.team_id.is_some() && kind != "update" {
            return Ok(Err(LegacyRefusal::TeamUnsupported));
        }
        let owner = match &mutation["ownerHash"] {
            Value::Null => None,
            Value::String(hash) if hash.len() == 64 => Some(hash.clone()),
            _ => return Ok(Err(LegacyRefusal::Malformed)),
        };
        let version = |value: &Value| value.as_u64().filter(|v| *v > 0);
        let (kind, input) = match kind {
            "create" => {
                if !mutation["creator"].is_null() {
                    return Ok(Err(LegacyRefusal::UnverifiedCaller));
                }
                let input = without_plaintext(&mutation["input"])?;
                if input["task_id"] != task_id {
                    return Ok(Err(LegacyRefusal::Malformed));
                }
                (TaskMutationKind::Create, input)
            }
            "update" => {
                let input = without_plaintext(&mutation["input"])?;
                if version(&input["version"]).is_none() {
                    return Ok(Err(LegacyRefusal::Malformed));
                }
                (TaskMutationKind::Update, input)
            }
            "complete" => match version(&mutation["input"]["version"]) {
                Some(v) => (
                    TaskMutationKind::Complete,
                    json!({"version":v,"team_id":null}),
                ),
                None => return Ok(Err(LegacyRefusal::Malformed)),
            },
            "delete" => match version(&mutation["version"]) {
                Some(v) => (
                    TaskMutationKind::Delete,
                    json!({"version":v,"projection_scheduled_at":null}),
                ),
                None => return Ok(Err(LegacyRefusal::Malformed)),
            },
            _ => return Ok(Err(LegacyRefusal::Malformed)),
        };
        let headers = TaskHeaders {
            owner,
            ..TaskHeaders::default()
        };
        Ok(Ok(self
            .prepare(delivery_id, kind, task_id, input, headers)
            .await?))
    }
    /// Convert one npm Activity `Delivery` (`{input, owner_hash?}`) queued for
    /// `task_id` by `actor` (`user` | `assignee`).
    ///
    /// # Errors
    /// As [`Tasks::adopt_npm_mutation`].
    pub async fn adopt_npm_activity(
        &mut self,
        task_id: &str,
        actor: &str,
        record: &Value,
        delivery_id: &str,
    ) -> Result<std::result::Result<TaskDelivery, LegacyRefusal>> {
        if actor == "assignee" {
            return Ok(Err(LegacyRefusal::UnverifiedCaller));
        }
        if actor != "user"
            || !hex64(delivery_id)
            || uuid(task_id).is_err()
            || record["input"]["entry_id"] != delivery_id
            || !record["input"]["encrypted_message"].is_string()
        {
            return Ok(Err(LegacyRefusal::Malformed));
        }
        let owner = match &record["owner_hash"] {
            Value::Null => None,
            Value::String(hash) if hash.len() == 64 => Some(hash.clone()),
            _ => return Ok(Err(LegacyRefusal::Malformed)),
        };
        let headers = TaskHeaders {
            owner,
            ..TaskHeaders::default()
        };
        let input = without_plaintext(&record["input"])?;
        Ok(Ok(self
            .prepare(
                delivery_id,
                TaskMutationKind::Activity,
                task_id.into(),
                input,
                headers,
            )
            .await?))
    }
}

#[cfg(test)]
#[path = "legacy_delivery_tests.rs"]
mod tests;
