//! Pure fences for the existing client-encrypted Task update-job protocol.
//! Claims omit authenticated owner/Team routing in the current backend. A caller
//! MUST resolve the canonical Task under its active owner/Team and authenticate
//! its key wrapper before preparing an update; absent Team markers prove nothing.
use crate::error::{Error, Result};
use aes_gcm::{Aes256Gcm, KeyInit, Nonce, aead::Aead};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use rand::{RngCore, rngs::OsRng};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use zeroize::{Zeroize, Zeroizing};
const MAX_INTEGER: u64 = 9_007_199_254_740_991;
const MAX_PRIVATE_BYTES: usize = 200 * 1024;
const SAFE_KEYS: &[&str] = &[
    "slug_lookup_hash",
    "assignee_identity",
    "assignee_hash",
    "assignee_type",
    "blocked_reason_code",
    "created_at",
    "due_at",
    "ai_execution_state",
    "key_wrappers",
    "label_hashes",
    "linked_project_ids",
    "parent_task_id",
    "plan_id",
    "position",
    "primary_chat_id",
    "priority",
    "queue_state",
    "status",
    "task_id",
    "task_type",
    "updated_at",
    "verification_id",
    "version",
];
fn erase(value: &mut Value) {
    match value {
        Value::String(s) => s.zeroize(),
        Value::Array(v) => v.iter_mut().for_each(erase),
        Value::Object(v) => v.values_mut().for_each(erase),
        _ => {}
    }
}
struct Private(Value);
impl Drop for Private {
    fn drop(&mut self) {
        erase(&mut self.0);
    }
}
fn integer(value: &Value) -> Result<u64> {
    value
        .as_u64()
        .filter(|n| *n <= MAX_INTEGER)
        .ok_or(Error::Protocol)
}
fn id(value: &Value) -> Result<&str> {
    value
        .as_str()
        .filter(|s| {
            !s.is_empty()
                && s.len() <= 128
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b':'))
        })
        .ok_or(Error::Protocol)
}
fn optional_id(value: &Value, field: &str) -> Result<Option<String>> {
    match value.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(value) => Ok(Some(id(value)?.into())),
    }
}
fn scalar(value: &Value) -> bool {
    match value {
        Value::String(s) => s.len() <= 512 && !s.chars().any(char::is_control),
        Value::Number(n) => n.as_i64().is_some_and(|n| n.unsigned_abs() <= MAX_INTEGER),
        Value::Bool(_) => true,
        Value::Null => true,
        _ => false,
    }
}
fn cipher(value: &str) -> Result<()> {
    if value.is_empty() || value.len() > (MAX_PRIVATE_BYTES + 34).div_ceil(3) * 4 {
        return Err(Error::Crypto);
    }
    let bytes = Zeroizing::new(STANDARD.decode(value).map_err(|_| Error::Crypto)?);
    if bytes.len() < 28 || STANDARD.encode(bytes.as_slice()) != value {
        return Err(Error::Crypto);
    }
    Ok(())
}
pub(super) struct TaskJobClaim {
    pub job_id: String,
    pub task_id: String,
    pub chat_id: String,
    pub source_task_chat_id: Option<String>,
    pub message_id: String,
    pub operation: String,
    pub state: String,
    pub lease_token: Zeroizing<String>,
    pub lease_generation: u64,
    pub lease_expires_at: u64,
    pub expected_task_version: u64,
    pub task_key_version: u64,
    pub private_patch: Value,
    pub safe_metadata: Value,
}
impl Drop for TaskJobClaim {
    fn drop(&mut self) {
        erase(&mut self.private_patch);
        erase(&mut self.safe_metadata);
    }
}
impl TaskJobClaim {
    pub(super) fn parse(
        payload: &Value,
        expected_job: &Value,
        expected_team: Option<&str>,
        expected_chat: Option<&str>,
        expected_user_message: Option<&str>,
        now_seconds: u64,
    ) -> Result<Self> {
        if !payload.is_object()
            || !expected_job.is_object()
            || payload.get("protocol_version").is_some_and(|v| v != 1)
        {
            return Err(Error::Protocol);
        }
        let job_id = id(&payload["job_id"])?;
        let task_id = id(&payload["task_id"])?;
        if job_id != id(&expected_job["job_id"])?
            || task_id != id(&expected_job["task_id"])?
            || integer(&expected_job["expires_at"])? <= now_seconds
        {
            return Err(Error::Protocol);
        }
        for record in [payload, expected_job] {
            if let Some(team) = record.get("team_id")
                && match (expected_team, team.as_str()) {
                    (Some(a), Some(b)) => a != b,
                    (None, None) => !team.is_null(),
                    _ => true,
                }
            {
                return Err(Error::Forbidden);
            }
            if let Some(hash) = record.get("hashed_team_id").filter(|v| !v.is_null())
                && !expected_team.is_some_and(|team| {
                    hash.as_str() == Some(format!("{:x}", Sha256::digest(team.as_bytes())).as_str())
                })
            {
                return Err(Error::Forbidden);
            }
        }
        for field in ["owner_id", "owner_hash"] {
            if let Some(owner) = payload.get(field).filter(|v| !v.is_null())
                && (!owner.is_string() || expected_job.get(field) != Some(owner))
            {
                return Err(Error::Forbidden);
            }
        }
        let chat_id = optional_id(payload, "chat_id")?
            .or_else(|| expected_chat.map(str::to_owned))
            .ok_or(Error::Protocol)?;
        if optional_id(expected_job, "chat_id")?.is_some_and(|s| s != chat_id)
            || expected_chat.is_some_and(|s| s != chat_id)
        {
            return Err(Error::Forbidden);
        }
        let message_id = optional_id(payload, "message_id")?
            .or_else(|| expected_user_message.map(str::to_owned))
            .ok_or(Error::Protocol)?;
        if expected_user_message.is_some_and(|s| s != message_id) {
            return Err(Error::Forbidden);
        }
        let operation = payload["operation"].as_str().ok_or(Error::Protocol)?;
        if !matches!(
            operation,
            "create" | "update" | "move" | "block" | "complete" | "unblock"
        ) || expected_team.is_some() && operation == "create"
        {
            return Err(Error::Forbidden);
        }
        let state = payload["state"].as_str().ok_or(Error::Protocol)?;
        if !matches!(state, "LEASED" | "TASK_PERSISTED") {
            return Err(Error::Protocol);
        }
        let lease_token = payload["lease_token"]
            .as_str()
            .filter(|s| {
                !s.is_empty()
                    && s.len() <= 256
                    && s.bytes()
                        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
            })
            .ok_or(Error::Protocol)?;
        let lease_generation = integer(&payload["lease_generation"])?;
        let lease_expires_at = integer(&payload["lease_expires_at"])?;
        if lease_generation == 0
            || lease_expires_at == 0
            || state == "LEASED" && lease_expires_at <= now_seconds
        {
            return Err(Error::Protocol);
        }
        let expected_task_version = integer(&payload["expected_task_version"])?;
        let task_key_version = integer(&payload["task_key_version"])?;
        if expected_task_version != integer(&expected_job["revision"])?
            || task_key_version != 1
            || task_key_version != integer(&expected_job["task_key_version"])?
            || (operation == "create") != (expected_task_version == 0)
        {
            return Err(Error::Protocol);
        }
        let empty = json!({});
        let private_patch = payload
            .get("private_patch")
            .filter(|v| !v.is_null())
            .unwrap_or(&empty);
        let safe_metadata = payload
            .get("safe_metadata")
            .filter(|v| !v.is_null())
            .unwrap_or(&empty);
        if !private_patch.as_object().is_some_and(|o| {
            o.iter().all(|(k, v)| {
                matches!(k.as_str(), "title" | "description")
                    && v.as_str().is_some_and(|s| s.len() <= MAX_PRIVATE_BYTES)
            })
        }) || !safe_metadata.as_object().is_some_and(|o| {
            o.iter().all(|(k, v)| {
                (SAFE_KEYS.contains(&k.as_str())
                    || matches!(k.as_str(), "operation" | "expected_version"))
                    && (scalar(v)
                        || k == "linked_project_ids"
                            && v.as_array().is_some_and(|a| {
                                a.len() <= 1000 && a.iter().all(|v| id(v).is_ok())
                            }))
            })
        }) {
            return Err(Error::Protocol);
        }
        if safe_metadata
            .get("operation")
            .is_some_and(|v| v != operation)
            || safe_metadata
                .get("expected_version")
                .is_some_and(|v| v.as_u64() != Some(expected_task_version))
        {
            return Err(Error::Protocol);
        }
        Ok(Self {
            job_id: job_id.into(),
            task_id: task_id.into(),
            chat_id,
            source_task_chat_id: optional_id(payload, "source_task_chat_id")?,
            message_id,
            operation: operation.into(),
            state: state.into(),
            lease_token: Zeroizing::new(lease_token.into()),
            lease_generation,
            lease_expires_at,
            expected_task_version,
            task_key_version,
            private_patch: private_patch.clone(),
            safe_metadata: safe_metadata.clone(),
        })
    }
}
fn wrapper(value: &Value) -> Result<()> {
    let value = value.as_object().ok_or(Error::Protocol)?;
    let kind = value
        .get("key_type")
        .and_then(Value::as_str)
        .filter(|s| matches!(*s, "master" | "chat" | "project" | "team" | "plan"))
        .ok_or(Error::Protocol)?;
    for (key, value) in value {
        match key.as_str() {
            "key_type" => {}
            "encrypted_task_key" => cipher(value.as_str().ok_or(Error::Protocol)?)?,
            "hashed_task_id" | "hashed_chat_id" | "hashed_project_id" | "hashed_team_id"
            | "hashed_plan_id" => {
                if !value
                    .as_str()
                    .is_some_and(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
                {
                    return Err(Error::Protocol);
                }
            }
            "created_at" => {
                integer(value)?;
            }
            "team_key_epoch" => {
                if integer(value)? != 1 {
                    return Err(Error::Protocol);
                }
            }
            "expires_at" if value.is_null() => {}
            "expires_at" => {
                integer(value)?;
            }
            _ => return Err(Error::Protocol),
        }
    }
    cipher(
        value
            .get("encrypted_task_key")
            .and_then(Value::as_str)
            .ok_or(Error::Protocol)?,
    )?;
    if kind != "master"
        && !value.contains_key(match kind {
            "chat" => "hashed_chat_id",
            "project" => "hashed_project_id",
            "plan" => "hashed_plan_id",
            _ => "hashed_team_id",
        })
    {
        return Err(Error::Protocol);
    }
    if kind == "team" && value.get("team_key_epoch").and_then(Value::as_u64) != Some(1) {
        return Err(Error::Protocol);
    }
    Ok(())
}
pub(super) fn persist_payload(
    claim: &TaskJobClaim,
    encrypted_task: Value,
    event_cipher: &str,
) -> Result<Value> {
    let mut task = Private(encrypted_task);
    let object = task.0.as_object_mut().ok_or(Error::Protocol)?;
    // Preserve explicit authorized lifecycle clears. The legacy broad null
    // pruning would retain a stale blocked reason on an unblock job.
    object.retain(|key, value| {
        !value.is_null()
            || matches!(
                key.as_str(),
                "primary_chat_id" | "blocked_reason_code" | "ai_execution_state" | "due_at"
            )
    });
    cipher(event_cipher)?;
    for (key, value) in object.iter() {
        if key.starts_with("encrypted_") {
            cipher(value.as_str().ok_or(Error::Protocol)?)?;
            continue;
        }
        if !SAFE_KEYS.contains(&key.as_str()) {
            return Err(Error::Protocol);
        }
        match key.as_str() {
            "key_wrappers" => {
                let values = value
                    .as_array()
                    .filter(|a| a.len() <= 1000)
                    .ok_or(Error::Protocol)?;
                for value in values {
                    wrapper(value)?;
                }
            }
            "linked_project_ids" => {
                if !value
                    .as_array()
                    .is_some_and(|a| a.len() <= 1000 && a.iter().all(|v| id(v).is_ok()))
                {
                    return Err(Error::Protocol);
                }
            }
            "label_hashes" => {
                if !value.as_array().is_some_and(|a| {
                    a.len() <= 1000
                        && a.iter().all(|v| {
                            v.as_str().is_some_and(|s| {
                                s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit())
                            })
                        })
                }) {
                    return Err(Error::Protocol);
                }
            }
            _ if scalar(value) => {}
            _ => return Err(Error::Protocol),
        }
    }
    let version = integer(&task.0["version"])?;
    if claim.state != "LEASED"
        || version
            != if claim.operation == "create" {
                1
            } else {
                claim.expected_task_version
            }
        || task
            .0
            .get("task_id")
            .is_some_and(|v| v.as_str() != Some(claim.task_id.as_str()))
    {
        return Err(Error::Protocol);
    }
    if claim.operation == "create"
        && (!task.0.get("encrypted_title").is_some_and(Value::is_string)
            || !task
                .0
                .get("encrypted_task_key")
                .is_some_and(Value::is_string)
            || task.0.get("task_id").is_none())
    {
        return Err(Error::Protocol);
    }
    Ok(
        json!({"protocol_version":1,"job_id":claim.job_id,"lease_token":claim.lease_token.as_str(),"lease_generation":claim.lease_generation,"expected_task_version":claim.expected_task_version,"encrypted_task_payload":std::mem::take(&mut task.0),"encrypted_task_event_message":event_cipher}),
    )
}
pub(super) fn event_message(
    job_id: &str,
    user_message: &str,
    event: &Value,
    chat_key: &[u8; 32],
    created_at: u64,
) -> Result<Value> {
    id(&json!(job_id))?;
    id(&json!(user_message))?;
    let event_id = id(&event["event_id"])?;
    let message_id = format!("task-event-{event_id}");
    if message_id.len() > 128
        || ["message_id", "user_message_id"].iter().any(|key| {
            event
                .get(*key)
                .filter(|v| !v.is_null())
                .is_some_and(|v| v != user_message)
        })
        || event
            .get("task_update_job_id")
            .filter(|v| !v.is_null())
            .is_some_and(|v| v != job_id)
    {
        return Err(Error::Protocol);
    }
    let label = event["short_id"]
        .as_str()
        .filter(|s| !s.is_empty())
        .unwrap_or(id(&event["task_id"])?);
    let text = |name: &str| -> Result<&str> {
        match event.get(name) {
            None | Some(Value::Null) => Ok(""),
            Some(Value::String(s)) if s.len() <= MAX_PRIVATE_BYTES => Ok(s),
            _ => Err(Error::Protocol),
        }
    };
    let title = text("title")?;
    let status = text("status")?;
    let reason = text("reason")?;
    let title_part = Zeroizing::new(if title.is_empty() {
        String::new()
    } else {
        format!(" \"{title}\"")
    });
    let status_part = Zeroizing::new(if status.is_empty() {
        String::new()
    } else {
        format!(" ({status})")
    });
    let reason_part = Zeroizing::new(if reason.is_empty() {
        String::new()
    } else {
        format!(": {reason}")
    });
    let (title, status, reason) = (
        title_part.as_str(),
        status_part.as_str(),
        reason_part.as_str(),
    );
    let kind = id(&event["event_type"])?;
    let content = Zeroizing::new(match kind {
        "started" => format!("Task queue continuation: {label} started{title}{status}"),
        "continuing" => format!("Task queue continuation: continuing {label}{title}{status}"),
        "created" => format!("{label} created{title}{status}"),
        "updated" => format!("{label} updated{title}{status}"),
        "blocked" => format!("{label} blocked{reason}"),
        "completed" => format!("{label} completed{title}"),
        "unblocked" => format!("{label} unblocked"),
        _ => format!("{label} {kind}{title}{status}{reason}"),
    });
    if content.len() > MAX_PRIVATE_BYTES {
        return Err(Error::Protocol);
    }
    let timestamp = event
        .get("created_at")
        .filter(|v| !v.is_null())
        .map(integer)
        .transpose()?
        .unwrap_or(created_at);
    if timestamp > MAX_INTEGER {
        return Err(Error::Protocol);
    }
    // The canonical CLI event format is base64(IV || ciphertext || tag), not
    // the SDK's optional OM fingerprint framing.
    let mut nonce = [0u8; 12];
    OsRng.fill_bytes(&mut nonce);
    let mut combined = nonce.to_vec();
    combined.extend(
        Aes256Gcm::new_from_slice(chat_key)
            .map_err(|_| Error::Crypto)?
            .encrypt(Nonce::from_slice(&nonce), content.as_bytes())
            .map_err(|_| Error::Crypto)?,
    );
    Ok(
        json!({"message_id":message_id,"role":"system","encrypted_content":STANDARD.encode(combined),"created_at":timestamp,"user_message_id":user_message,"task_update_job_id":job_id}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn job() -> Value {
        json!({"job_id":"task-update-job-fixture","task_id":"task-1","chat_id":"chat-1","revision":2,"task_key_version":1,"expires_at":2000})
    }
    fn payload() -> Value {
        json!({"job_id":"task-update-job-fixture","task_id":"task-1","chat_id":"chat-1","source_task_chat_id":"task-chat-1","message_id":"user-message-1","operation":"update","state":"LEASED","lease_token":"synthetic-lease-token","lease_generation":3,"lease_expires_at":1100,"expected_task_version":2,"task_key_version":1,"private_patch":{"title":"Private title","description":"Private details"},"safe_metadata":{"operation":"update","expected_version":2,"updated_at":1000}})
    }
    fn parse(value: &Value) -> Result<TaskJobClaim> {
        TaskJobClaim::parse(
            value,
            &job(),
            None,
            Some("chat-1"),
            Some("user-message-1"),
            1000,
        )
    }
    fn encrypted() -> String {
        crate::crypto::encrypt_combined("synthetic private data", &[7; 32]).unwrap()
    }
    #[test]
    fn claim_binds_summary_turn_revision_and_live_lease() {
        let claim = parse(&payload()).unwrap();
        assert_eq!(claim.task_id, "task-1");
        assert_eq!(claim.source_task_chat_id.as_deref(), Some("task-chat-1"));
        assert_eq!(claim.lease_generation, 3);
        assert_eq!(claim.lease_expires_at, 1100);
        assert_eq!(claim.task_key_version, 1);
        for (key, value) in [
            ("job_id", json!("other")),
            ("task_id", json!("other")),
            ("chat_id", json!("other")),
            ("message_id", json!("other")),
            ("expected_task_version", json!(3)),
            ("task_key_version", json!(2)),
            ("lease_generation", json!(0)),
            ("lease_generation", json!(1.5)),
            ("lease_token", json!("bad token")),
            ("lease_expires_at", json!(1000)),
            ("protocol_version", json!(2)),
            ("state", json!("PENDING")),
            ("state", json!("TERMINAL")),
            ("operation", json!("delete")),
        ] {
            let mut value_payload = payload();
            value_payload[key] = value;
            assert!(
                parse(&value_payload).is_err(),
                "accepted invalid claim field {key}"
            );
        }
        let mut expected = job();
        expected["expires_at"] = json!(1000);
        assert!(TaskJobClaim::parse(&payload(), &expected, None, None, None, 1000).is_err());
        let mut changed = payload();
        changed["safe_metadata"]["expected_version"] = json!(3);
        assert!(parse(&changed).is_err());
    }
    #[test]
    fn task_persisted_is_event_recovery_without_requiring_an_unexpired_lease() {
        let mut value = payload();
        value["state"] = json!("TASK_PERSISTED");
        value["lease_expires_at"] = json!(900);
        let claim = parse(&value).unwrap();
        assert_eq!(claim.state, "TASK_PERSISTED");
        assert!(persist_payload(&claim, json!({"version":2}), &encrypted()).is_err());
    }
    #[test]
    fn explicit_owner_team_markers_never_cross_scope_and_absence_is_not_proof() {
        let value = payload();
        // The coordinator still must authenticate the canonical Team Task.
        assert!(TaskJobClaim::parse(&value, &job(), Some("team-1"), None, None, 1000).is_ok());
        let mut value = payload();
        value["team_id"] = json!("team-2");
        assert!(TaskJobClaim::parse(&value, &job(), Some("team-1"), None, None, 1000).is_err());
        assert!(parse(&value).is_err());
        value["team_id"] = json!("team-1");
        assert!(TaskJobClaim::parse(&value, &job(), Some("team-1"), None, None, 1000).is_ok());
        value["hashed_team_id"] = json!("0".repeat(64));
        assert!(TaskJobClaim::parse(&value, &job(), Some("team-1"), None, None, 1000).is_err());
        let mut value = payload();
        value["owner_id"] = json!("owner-1");
        assert!(parse(&value).is_err());
        let mut expected = job();
        expected["owner_id"] = json!("owner-1");
        assert!(TaskJobClaim::parse(&value, &expected, None, None, None, 1000).is_ok());
        expected["owner_id"] = json!("owner-2");
        assert!(TaskJobClaim::parse(&value, &expected, None, None, None, 1000).is_err());
    }
    #[test]
    fn private_patch_and_safe_metadata_shapes_reject_unrequested_private_fields() {
        for (object, key, value) in [
            ("private_patch", "primary_chat_id", json!("wrong-chat")),
            ("private_patch", "title", json!({"nested":"secret"})),
            ("safe_metadata", "title", json!("plaintext")),
            ("safe_metadata", "status", json!({"title":"plaintext"})),
            ("safe_metadata", "operation", json!("move")),
        ] {
            let mut input = payload();
            input[object][key] = value;
            assert!(parse(&input).is_err());
        }
        let mut raw = json!({"title":"secret","nested":["private"]});
        erase(&mut raw);
        assert_eq!(raw, json!({"title":"","nested":[""]}));
    }
    #[test]
    fn persistence_is_ciphertext_only_and_preserves_authorized_null_clears() {
        let claim = parse(&payload()).unwrap();
        let ciphertext = encrypted();
        let result=persist_payload(&claim,json!({"version":2,"encrypted_title":ciphertext,"encrypted_description":null,"primary_chat_id":null,"blocked_reason_code":null,"ai_execution_state":null,"due_at":null,"status":"todo"}),&ciphertext).unwrap();
        assert_eq!(result["protocol_version"], 1);
        assert_eq!(result["expected_task_version"], 2);
        let value = &result["encrypted_task_payload"];
        assert!(value.get("encrypted_description").is_none());
        for field in [
            "primary_chat_id",
            "blocked_reason_code",
            "ai_execution_state",
            "due_at",
        ] {
            assert_eq!(value.get(field), Some(&Value::Null));
        }
        for (key, value) in [
            ("title", json!("leaked")),
            ("description", json!("leaked")),
            ("private_patch", json!({"title":"leaked"})),
            (
                "encrypted_title",
                json!("plaintext pretending to be ciphertext"),
            ),
            ("status", json!({"title":"leaked"})),
            ("version", json!(3)),
            ("task_id", json!("other")),
        ] {
            let mut value_payload = json!({"version":2});
            value_payload[key] = value;
            assert!(
                persist_payload(&claim, value_payload, &ciphertext).is_err(),
                "accepted unsafe persistence field {key}"
            );
        }
        assert!(persist_payload(&claim, json!({"version":2}), "").is_err());
    }
    #[test]
    fn create_requires_initial_revision_private_cipher_and_refuses_team_creation() {
        let mut value = payload();
        value["operation"] = json!("create");
        value["expected_task_version"] = json!(0);
        value["safe_metadata"] = json!({});
        let mut expected = job();
        expected["revision"] = json!(0);
        let claim = TaskJobClaim::parse(&value, &expected, None, None, None, 1000).unwrap();
        assert!(TaskJobClaim::parse(&value, &expected, Some("team-1"), None, None, 1000).is_err());
        let cipher = encrypted();
        assert!(persist_payload(&claim,json!({"task_id":"task-1","version":1,"encrypted_title":cipher,"encrypted_task_key":cipher}),&cipher).is_ok());
        assert!(
            persist_payload(
                &claim,
                json!({"task_id":"task-1","version":1,"encrypted_title":cipher}),
                &cipher
            )
            .is_err()
        );
        value["task_key_version"] = json!(2);
        expected["task_key_version"] = json!(2);
        assert!(TaskJobClaim::parse(&value, &expected, None, None, None, 1000).is_err());
    }
    #[test]
    fn nested_wrappers_allow_ciphertext_metadata_including_plan_without_plaintext_escape() {
        let claim = parse(&payload()).unwrap();
        let cipher = encrypted();
        let hash = "a".repeat(64);
        let mut value = json!({"version":2,"key_wrappers":[{"key_type":"plan","hashed_plan_id":hash,"encrypted_task_key":cipher,"created_at":1000,"expires_at":null}]});
        assert!(persist_payload(&claim, value.clone(), &cipher).is_ok());
        value["key_wrappers"][0]["title"] = json!("leaked");
        assert!(persist_payload(&claim, value, &cipher).is_err());
        assert!(persist_payload(&claim,json!({"version":2,"key_wrappers":[{"key_type":"project","encrypted_task_key":cipher}]}),&cipher).is_err());
    }
    #[test]
    fn event_messages_match_legacy_text_ids_timestamps_and_legacy_aead_wire() {
        for (kind, expected) in [
            (
                "started",
                "Task queue continuation: TASK-42 started \"Private title\" (todo)",
            ),
            (
                "continuing",
                "Task queue continuation: continuing TASK-42 \"Private title\" (todo)",
            ),
            ("created", "TASK-42 created \"Private title\" (todo)"),
            ("updated", "TASK-42 updated \"Private title\" (todo)"),
            ("blocked", "TASK-42 blocked: waiting"),
            ("completed", "TASK-42 completed \"Private title\""),
            ("unblocked", "TASK-42 unblocked"),
            ("moved", "TASK-42 moved \"Private title\" (todo): waiting"),
        ] {
            let event = json!({"event_id":"task-event-fixture","task_id":"task-1","short_id":"TASK-42","event_type":kind,"title":"Private title","status":"todo","reason":"waiting","created_at":55,"task_update_job_id":"job-1"});
            let output = event_message("job-1", "user-1", &event, &[7; 32], 99).unwrap();
            assert_eq!(output["message_id"], "task-event-task-event-fixture");
            assert_eq!(output["created_at"], 55);
            assert_eq!(output["task_update_job_id"], "job-1");
            assert!(output.get("content").is_none());
            let bytes = STANDARD
                .decode(output["encrypted_content"].as_str().unwrap())
                .unwrap();
            let plaintext = Zeroizing::new(
                Aes256Gcm::new_from_slice(&[7; 32])
                    .unwrap()
                    .decrypt(Nonce::from_slice(&bytes[..12]), &bytes[12..])
                    .unwrap(),
            );
            assert_eq!(plaintext.as_slice(), expected.as_bytes());
        }
        let event = json!({"event_id":"event-1","task_id":"task-1","event_type":"updated"});
        assert_eq!(
            event_message("job-1", "user-1", &event, &[7; 32], 99).unwrap()["created_at"],
            99
        );
        let mut wrong = event;
        wrong["task_update_job_id"] = json!("other");
        assert!(event_message("job-1", "user-1", &wrong, &[7; 32], 99).is_err());
    }
}
