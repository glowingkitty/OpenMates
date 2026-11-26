//! Browser opened-chat completion receipts, scoped to Personal storage and key.
//! The shell seals the encoded receipt with the existing master-key operation.
//! A database mutation revision is needed at both publication and readback.

use crate::client::parse_startup_opened_chat_ids;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const FORMAT: &str = "openmates:web-opened-coverage:v1";
const MAX_VERSION: u64 = (1 << 53) - 1;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct StorageBinding {
    owner: String,
    chat_id: String,
    team_id: Option<String>,
    encrypted_chat_key: String,
    key_version: Option<u64>,
    row_revision: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Receipt {
    format: String,
    storage_binding: [u8; 32],
    messages_version: u64,
    retained_rows: usize,
}

fn valid_id(value: &str) -> bool {
    parse_startup_opened_chat_ids(&json!([value])).is_ok()
}

fn fingerprint(binding: StorageBinding) -> Result<[u8; 32], &'static str> {
    if binding.team_id.is_some()
        || !valid_id(&binding.owner)
        || !valid_id(&binding.chat_id)
        || (!valid_id(&binding.row_revision) && !digest_shape(&binding.row_revision))
        || binding.encrypted_chat_key.is_empty()
        || binding.encrypted_chat_key.len() > 2048
    {
        return Err("protocol");
    }
    let encoded = json!([
        FORMAT,
        binding.owner,
        binding.chat_id,
        binding.encrypted_chat_key,
        binding.key_version,
        binding.row_revision
    ]);
    Ok(Sha256::digest(encoded.to_string()).into())
}

const ROW_FIELDS: &[&str] = &[
    "id",
    "message_id",
    "client_message_id",
    "chat_id",
    "created_at",
    "role",
    "status",
    "key_version",
    "has_thinking",
    "thinking_token_count",
    "queue_revision",
    "queue_mode",
    "queue_dispatch_status",
    "queue_dispatch_mode",
    "queue_dispatch_task_id",
    "encrypted_content",
    "encrypted_sender_name",
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_thinking_content",
    "encrypted_thinking_signature",
    "encrypted_pii_mappings",
    "pending_encrypted_embed_bundle_v1",
    "pending_encrypted_turn_preflight_v1",
    "pending_turn_preflight_v1",
];

fn digest_shape(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn row_position(row: &Value) -> Option<(u64, &str)> {
    let created = row["created_at"].as_u64()?;
    let id = row["message_id"]
        .as_str()
        .filter(|id| !id.is_empty() && id.len() <= 512)?;
    Some((created, id))
}

// Legacy databases have no universal mutation journal. Use a versioned
// rolling digest of their exact encrypted row projection instead.
pub(super) fn coverage_digest(input: &Value) -> Result<Value, &'static str> {
    let chat = input["chatId"]
        .as_str()
        .filter(|id| valid_id(id))
        .ok_or("protocol")?;
    let rows = input["rows"]
        .as_array()
        .filter(|rows| rows.len() <= 20)
        .ok_or("protocol")?;
    let mut digest = match &input["previous"] {
        Value::Null => format!("{:x}", Sha256::digest(FORMAT)),
        Value::String(value) if digest_shape(value) => value.clone(),
        _ => return Err("protocol"),
    };
    let mut ordered = Vec::with_capacity(rows.len());
    for row in rows {
        let row_object = row.as_object().ok_or("protocol")?;
        if row["chat_id"].as_str() != Some(chat)
            || row["encrypted_content"].as_str().is_none_or(str::is_empty)
            || row_object.iter().any(|(key, value)| {
                !ROW_FIELDS.contains(&key.as_str()) || value.is_object() || value.is_array()
            })
        {
            return Err("protocol");
        }
        ordered.push((row_position(row).ok_or("protocol")?, row));
    }
    ordered.sort_unstable_by(|a, b| b.0.cmp(&a.0));
    for (_, row) in ordered {
        let mut hash = Sha256::new();
        hash.update(digest.as_bytes());
        for field in ROW_FIELDS {
            // Include field presence, since omitted and explicit null can
            // have different write/replay semantics in the cache protocol.
            hash.update(if row.get(field).is_some() { [1] } else { [0] });
            serde_json::to_writer(&mut DigestWriter(&mut hash), &row[field])
                .map_err(|_| "protocol")?;
            hash.update([0]);
        }
        digest = format!("{:x}", hash.finalize());
    }
    Ok(json!({"digest":digest}))
}

struct DigestWriter<'a>(&'a mut Sha256);
impl std::io::Write for DigestWriter<'_> {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.update(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

pub(super) fn coverage_decision(input: &Value) -> Result<Value, &'static str> {
    let binding = serde_json::from_value(input["binding"].clone()).map_err(|_| "protocol")?;
    let storage_binding = fingerprint(binding)?;
    if let Some(document) = input["document"].as_str() {
        if document.len() > 2048 {
            return Err("protocol");
        }
        let receipt: Receipt = serde_json::from_str(document).map_err(|_| "protocol")?;
        if receipt.format != FORMAT
            || receipt.storage_binding != storage_binding
            || receipt.messages_version > MAX_VERSION
        {
            return Err("protocol");
        }
        return Ok(json!({
            "messagesVersion": receipt.messages_version,
            "retainedRows": receipt.retained_rows,
        }));
    }
    let messages_version = input["messagesVersion"]
        .as_u64()
        .filter(|version| *version <= MAX_VERSION)
        .ok_or("protocol")?;
    let retained_rows = input["retainedRows"]
        .as_u64()
        .and_then(|rows| usize::try_from(rows).ok())
        .ok_or("protocol")?;
    let receipt = Receipt {
        format: FORMAT.into(),
        storage_binding,
        messages_version,
        retained_rows,
    };
    Ok(json!({"document":serde_json::to_string(&receipt).map_err(|_| "protocol")?}))
}

#[cfg(test)]
mod tests {
    use super::*;

    // contract-test: infrastructure
    #[test]
    fn exact_legacy_digest_distinguishes_modified_and_missing_ciphertext_rows() {
        let chat = "00000000-0000-0000-0000-000000000002";
        let first = json!({"chat_id":chat,"message_id":"middle","created_at":3,"encrypted_content":"wrapped-first"});
        let last = json!({"chat_id":chat,"message_id":"second","created_at":1,"encrypted_content":"wrapped-second"});
        let digest = |previous: Value, rows: Value| {
            coverage_digest(&json!({"chatId":chat,"previous":previous,"rows":rows})).unwrap()
                ["digest"]
                .clone()
        };
        let whole = digest(Value::Null, json!([last, first]));
        let partial = digest(Value::Null, json!([first]));
        assert_eq!(digest(partial.clone(), json!([last])), whole);
        assert_ne!(whole, partial);
        let mut changed = last;
        changed["encrypted_content"] = json!("modified");
        assert_ne!(digest(partial, json!([changed])), whole);
    }

    // contract-test: infrastructure
    #[test]
    fn wrapper_only_personal_header_needs_no_local_key_version() {
        let binding = json!({
            "owner": "00000000-0000-0000-0000-000000000001",
            "chatId": "00000000-0000-0000-0000-000000000002",
            "teamId": null, "encryptedChatKey": "restored-from-authorized-wrapper",
            "keyVersion": null, "rowRevision": "00000000-0000-0000-0000-000000000003",
        });
        let sealed = coverage_decision(&json!({
            "binding":binding, "messagesVersion":8, "retainedRows":10,
        }))
        .unwrap();
        assert_eq!(
            coverage_decision(&json!({"binding":binding, "document":sealed["document"]})).unwrap(),
            json!({"messagesVersion":8, "retainedRows":10})
        );
    }

    // contract-test: infrastructure
    #[test]
    fn binds_completion_to_personal_owner_chat_key_and_mutation_revision() {
        let owner = "00000000-0000-0000-0000-000000000001";
        let chat = "00000000-0000-0000-0000-000000000002";
        let revision = "00000000-0000-0000-0000-000000000003";
        let binding = json!({
            "owner": owner, "chatId": chat, "teamId": null, "encryptedChatKey": "wrap",
            "keyVersion": 1, "rowRevision": revision,
        });
        let sealed = coverage_decision(&json!({
            "binding": binding, "messagesVersion": 17, "retainedRows": 90,
        }))
        .unwrap();
        let mut restore = json!({"binding": binding, "document": sealed["document"]});
        assert_eq!(
            coverage_decision(&restore).unwrap(),
            json!({
                "messagesVersion":17, "retainedRows":90,
            })
        );
        for (key, changed) in [
            ("owner", json!(chat)),
            ("chatId", json!(owner)),
            ("rowRevision", json!(owner)),
            ("encryptedChatKey", json!("replacement")),
            ("keyVersion", json!(2)),
            ("teamId", json!("team")),
        ] {
            restore["binding"][key] = changed;
            assert!(coverage_decision(&restore).is_err());
            restore["binding"][key] = binding[key].clone();
        }
    }
}
