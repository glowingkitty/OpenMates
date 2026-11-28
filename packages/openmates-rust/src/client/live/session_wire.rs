//! JSON shapes between [`super::session::LiveSession`] and a shell binding: the actions the
//! host performs and the answers it gives back. Marshalling only.

use super::LiveError;
use super::engine::SealedUpdate;
use super::session_types::{Action, CheckpointResult, Event};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};

fn invalid(error: impl ToString) -> LiveError {
    LiveError::InvalidUpdate(error.to_string())
}

/// Outbox entries as persisted in the cache: `[{client_msg_id, epoch, sealed(base64)}]`.
pub fn outbox_to_json(entries: &[SealedUpdate]) -> Value {
    Value::Array(
        entries
            .iter()
            .map(|e| json!({"client_msg_id": e.client_msg_id, "epoch": e.epoch, "sealed": STANDARD.encode(&e.sealed)}))
            .collect(),
    )
}

/// Parses [`outbox_to_json`] output (an empty string is an empty outbox).
///
/// # Errors
/// [`LiveError::InvalidUpdate`] for malformed input.
pub fn outbox_from_json(text: &str) -> Result<Vec<SealedUpdate>, LiveError> {
    if text.is_empty() {
        return Ok(Vec::new());
    }
    let list: Vec<Value> = serde_json::from_str(text).map_err(invalid)?;
    list.iter()
        .map(|e| {
            Ok(SealedUpdate {
                client_msg_id: e["client_msg_id"]
                    .as_str()
                    .ok_or_else(|| invalid("client_msg_id"))?
                    .to_string(),
                epoch: u32::try_from(e["epoch"].as_u64().ok_or_else(|| invalid("epoch"))?)
                    .map_err(invalid)?,
                sealed: STANDARD
                    .decode(e["sealed"].as_str().ok_or_else(|| invalid("sealed"))?)
                    .map_err(invalid)?,
            })
        })
        .collect()
}

/// Parses a checkpoint answer: `{"result":"written","version":8}`,
/// `{"result":"conflict","version":7}` or `{"result":"failed"}`.
///
/// # Errors
/// [`LiveError::InvalidUpdate`] for anything else.
pub fn checkpoint_result_from_json(text: &str) -> Result<CheckpointResult, LiveError> {
    let value: Value = serde_json::from_str(text).map_err(invalid)?;
    let version = value["version"].as_i64();
    match (value["result"].as_str(), version) {
        (Some("written"), Some(v)) => Ok(CheckpointResult::Written(v)),
        (Some("conflict"), Some(v)) => Ok(CheckpointResult::Conflict(v)),
        (Some("failed"), _) => Ok(CheckpointResult::Failed),
        _ => Err(invalid("checkpoint result")),
    }
}

/// The unit event for a shell-bound action: `(event name, payload)`. Plain Yjs bytes
/// (`liveRemoteUpdate`) are returned as `None`: the binding sends them as `Uint8Array`.
/// Host work is delivered as `liveHost` with a `kind` (`send`, `persistOutbox`, `needKey`,
/// `needContent`, `writeCheckpoint`).
pub fn action_event(action: &Action) -> Option<(&'static str, Value)> {
    Some(match action {
        Action::Emit(Event::RemoteUpdate { .. }) => return None,
        Action::Emit(Event::View { item_id, view }) => {
            ("liveView", json!({"itemId": item_id, "view": view}))
        }
        Action::Emit(Event::Presence { item_id, peers }) => {
            ("livePresence", json!({"itemId": item_id, "peers": peers}))
        }
        Action::Emit(Event::Status { item_id, status }) => (
            "liveStatus",
            json!({"itemId": item_id, "status": status.as_str()}),
        ),
        Action::Emit(Event::PrivateCopy {
            item_id,
            copy_id,
            kind,
            text,
        }) => (
            "livePrivateCopy",
            json!({"itemId": item_id, "copyId": copy_id, "kind": kind.as_str(), "text": text}),
        ),
        Action::Emit(Event::VersionWritten {
            item_id,
            version,
            text,
        }) => (
            "liveVersion",
            json!({"itemId": item_id, "version": version, "text": text}),
        ),
        Action::Send {
            message_type,
            payload,
        } => (
            "liveHost",
            json!({"kind": "send", "type": message_type, "payload": payload}),
        ),
        Action::PersistOutbox { item_id, entries } => (
            "liveHost",
            json!({"kind": "persistOutbox", "itemId": item_id, "entries": outbox_to_json(entries)}),
        ),
        Action::NeedKey { item_id, stale } => (
            "liveHost",
            json!({"kind": "needKey", "itemId": item_id, "stale": stale}),
        ),
        Action::NeedContent { item_id } => (
            "liveHost",
            json!({"kind": "needContent", "itemId": item_id}),
        ),
        Action::WriteCheckpoint(r) => (
            "liveHost",
            json!({"kind": "writeCheckpoint", "itemId": r.item_id, "text": r.text,
                "baseVersion": r.base_version, "versionKind": r.version_kind,
                "contributors": r.contributors}),
        ),
        Action::AssistantNeedBase {
            embed_id,
            turn_id,
            base_version,
        } => (
            "liveHost",
            json!({"kind": "assistantNeedBase", "embedId": embed_id, "turnId": turn_id,
                "baseVersion": base_version}),
        ),
        Action::PostAssistantOutcome { embed_id, body } => (
            "liveHost",
            json!({"kind": "postAssistantOutcome", "embedId": embed_id, "body": body}),
        ),
        Action::AssistantChangeNotOpen { embed_id, frame } => (
            "liveHost",
            json!({"kind": "assistantChangeNotOpen", "embedId": embed_id, "frame": frame}),
        ),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outbox_round_trips() {
        let entries = vec![SealedUpdate {
            client_msg_id: "m".into(),
            epoch: 2,
            sealed: vec![1, 2, 3],
        }];
        let text = outbox_to_json(&entries).to_string();
        assert_eq!(outbox_from_json(&text).unwrap(), entries);
        assert!(outbox_from_json("").unwrap().is_empty());
        assert!(outbox_from_json("{").is_err());
    }

    #[test]
    fn checkpoint_results_parse() {
        assert_eq!(
            checkpoint_result_from_json(r#"{"result":"conflict","version":4}"#).unwrap(),
            CheckpointResult::Conflict(4)
        );
        assert_eq!(
            checkpoint_result_from_json(r#"{"result":"failed"}"#).unwrap(),
            CheckpointResult::Failed
        );
        assert!(checkpoint_result_from_json(r#"{"result":"written"}"#).is_err());
    }
}
