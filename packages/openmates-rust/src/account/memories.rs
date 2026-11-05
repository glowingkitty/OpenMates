//! Personal app-settings Memories: list/decrypt, schema-validated create/update
//! and delete, mirroring the legacy CLI client (listMemories/upsertMemory).
//! Item JSON is encrypted locally with the master key before the WebSocket
//! write; the server never receives plaintext memory values or item keys.
//! Account Memory documents (`account-memory-*`) are listed read-only here.
use super::{Account, decrypt_settings};
use crate::{Error, Result, crypto};
use reqwest::Method;
use serde::Deserialize;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

/// One field of a registered memory type.
#[derive(Clone, Debug, Deserialize)]
pub struct MemoryField {
    pub name: String,
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(default, rename = "enum")]
    pub allowed: Option<Vec<String>>,
}
/// A registered memory type (legacy MEMORY_TYPE_REGISTRY entry, in order).
#[derive(Clone, Debug, Deserialize)]
pub struct MemoryType {
    pub key: String,
    pub app_id: String,
    pub item_type: String,
    pub entry_type: String,
    pub required: Vec<String>,
    pub properties: Vec<MemoryField>,
}

/// The production memory types, in the legacy CLI's registry order. Source:
/// `MEMORY_TYPE_REGISTRY` in frontend/packages/openmates-cli/src/client.ts.
pub fn memory_types() -> &'static [MemoryType] {
    static TYPES: std::sync::OnceLock<Vec<MemoryType>> = std::sync::OnceLock::new();
    TYPES.get_or_init(|| {
        serde_json::from_str(include_str!("memory_types.json"))
            .expect("maintained memory type registry must be valid")
    })
}

/// Legacy schema validation with its exact user-facing messages.
pub fn validate_memory(
    app_id: &str,
    item_type: &str,
    value: &Value,
) -> std::result::Result<(), String> {
    let key = format!("{app_id}/{item_type}");
    let Some(schema) = memory_types().iter().find(|t| t.key == key) else {
        let known = memory_types()
            .iter()
            .map(|t| format!("  {}", t.key))
            .collect::<Vec<_>>()
            .join("\n");
        return Err(format!(
            "Unknown memory type '{key}'.\n\nAvailable types:\n{known}"
        ));
    };
    let fields = value
        .as_object()
        .ok_or_else(|| "Memory --data must be a JSON object.".to_owned())?;
    let missing = schema
        .required
        .iter()
        .filter(|f| {
            matches!(fields.get(f.as_str()), None | Some(Value::Null))
                || fields.get(f.as_str()) == Some(&json!(""))
        })
        .cloned()
        .collect::<Vec<_>>();
    if !missing.is_empty() {
        return Err(format!(
            "Missing required fields for '{key}': {}\nRequired: {}",
            missing.join(", "),
            schema.required.join(", ")
        ));
    }
    for field in &schema.properties {
        let (Some(allowed), Some(value)) = (&field.allowed, fields.get(&field.name)) else {
            continue;
        };
        let text = js_string(value);
        if !allowed.contains(&text) {
            return Err(format!(
                "Invalid value '{text}' for field '{}'. Allowed values: {}",
                field.name,
                allowed.join(", ")
            ));
        }
    }
    Ok(())
}
/// JavaScript `String(value)` for JSON values used by enum validation.
fn js_string(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Null => "null".into(),
        Value::Array(items) => items.iter().map(js_string).collect::<Vec<_>>().join(","),
        Value::Object(_) => "[object Object]".into(),
        other => other.to_string(),
    }
}
/// Legacy `hashItemKey`: first 32 hex chars of sha256("{app}-{type}-{millis}").
pub(crate) fn hash_item_key(app_id: &str, item_type: &str, millis: u128) -> String {
    let digest = Sha256::digest(format!("{app_id}-{item_type}-{millis}").as_bytes());
    digest
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>()[..32]
        .to_owned()
}
fn now() -> Result<std::time::Duration> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| Error::Protocol)
}
/// Decrypt one Personal row; corrupt or undecryptable rows are skipped exactly
/// like the legacy list (which keeps every other valid Memory).
fn decode_row(raw: &Value, master: &[u8; 32]) -> Option<Value> {
    let ciphertext = raw.get("encrypted_item_json")?.as_str()?;
    let plaintext = Zeroizing::new(crypto::decrypt_combined(ciphertext, master).ok()?);
    let data: Value = serde_json::from_str(&plaintext).ok()?;
    data.is_object().then(|| {
        let text = |field: &str| match &raw[field] {
            Value::Null => String::new(),
            Value::String(text) => text.clone(),
            other => other.to_string(),
        };
        json!({"id":text("id"),"app_id":text("app_id"),"item_type":text("item_type"),
            "item_key_hash":text("item_key"),
            "item_version":raw["item_version"].as_f64().map(|_| raw["item_version"].clone()).unwrap_or(json!(1)),
            "created_at":raw["created_at"].as_f64().map(|_| raw["created_at"].clone()).unwrap_or(json!(0)),
            "updated_at":raw["updated_at"].as_f64().map(|_| raw["updated_at"].clone()).unwrap_or(json!(0)),
            "data":data})
    })
}
/// Account Memory documents from decrypted account settings (legacy
/// customRuleDocumentsFromEncryptedSettings limits and title extraction).
pub(crate) fn account_documents(settings: &Value) -> Vec<Value> {
    let mut order: Vec<String> = vec![];
    let mut by_id: Map<String, Value> = Map::new();
    for name in ["rule_documents", "memory_documents"] {
        for value in settings[name].as_array().into_iter().flatten() {
            if let Some(id) = value.get("id").and_then(Value::as_str) {
                if !by_id.contains_key(id) {
                    order.push(id.to_owned());
                }
                by_id.insert(id.to_owned(), value.clone());
            }
        }
    }
    let title = regex::Regex::new(r"(?m)^title:\s*(.+)$").expect("static title expression");
    let mut chars = 0;
    let mut documents = vec![];
    for id in order.into_iter().take(24) {
        let value = &by_id[&id];
        let source_ok = matches!(value.get("source"), None) || value["source"] == "personal";
        let Some(document) = value["document"].as_str() else {
            continue;
        };
        let length = document.encode_utf16().count();
        if !source_ok || id.is_empty() || id.encode_utf16().count() > 240 || length > 24_000 {
            continue;
        }
        if chars + length > 64_000 {
            continue;
        }
        chars += length;
        let mut name = title
            .captures(document)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().to_owned())
            .unwrap_or_else(|| "Memory".into());
        for quote in ['\'', '"'] {
            if let Some(rest) = name.strip_prefix(quote) {
                name = rest.to_owned();
                break;
            }
        }
        for quote in ['\'', '"'] {
            if let Some(rest) = name.strip_suffix(quote) {
                name = rest.to_owned();
                break;
            }
        }
        documents.push(json!({"id":format!("account-memory-{}",id.strip_prefix("personal:").unwrap_or(&id)),
            "app_id":"openmates","item_type":"memories","item_key_hash":"",
            "data":{"title":name,"document":document},"created_at":0,"updated_at":0,"item_version":1}));
    }
    documents
}

/// The exact `store_app_settings_memories_entry` payload with locally
/// encrypted item JSON (`{...value, settings_group, _original_item_key, added_date}`).
pub(crate) fn memory_entry(
    entry_id: &str,
    app_id: &str,
    item_type: &str,
    value: &Value,
    version: u64,
    master: &[u8; 32],
    elapsed: std::time::Duration,
) -> Result<Value> {
    let seconds = elapsed.as_secs();
    let mut plaintext = value.as_object().cloned().ok_or(Error::Protocol)?;
    plaintext.insert("settings_group".into(), json!(app_id));
    plaintext.insert("_original_item_key".into(), json!(item_type));
    plaintext.insert("added_date".into(), json!(seconds));
    let serialized = Zeroizing::new(serde_json::to_string(&Value::Object(plaintext))?);
    let encrypted = crypto::encrypt_combined(&serialized, master)?;
    Ok(json!({"entry":{"id":entry_id,"app_id":app_id,
        "item_key":hash_item_key(app_id, item_type, elapsed.as_millis()),"item_type":item_type,
        "encrypted_item_json":encrypted,"encrypted_app_key":"","created_at":seconds,
        "updated_at":seconds,"item_version":version}}))
}

impl Account<'_> {
    fn personal_memories(&self) -> Result<()> {
        if self.client.require_session()?.active_team_id.is_some() {
            return Err(Error::Unavailable {
                code: "team_memories_unavailable",
                reason: "Team Memories require an explicitly scoped native flow.",
            });
        }
        Ok(())
    }

    /// Decrypted Personal Memories followed by account Memory documents.
    pub async fn memories(&mut self) -> Result<Vec<Value>> {
        self.personal_memories()?;
        let data = self
            .client
            .request(Method::GET, "/v1/sdk/memories", None)
            .await?;
        let rows = match data.get("memories") {
            None | Some(Value::Null) => vec![],
            Some(Value::Array(rows)) => rows.clone(),
            Some(_) => return Err(Error::Protocol),
        };
        let master = self.client.require_session()?.master_key.clone();
        let mut result = rows
            .iter()
            .filter(|row| row.is_object())
            .filter_map(|row| decode_row(row, &master))
            .collect::<Vec<_>>();
        // Like the legacy list, account documents are best-effort context:
        // valid row Memories are still returned when settings cannot be read.
        if let Ok(user) = self.profile().await
            && let Ok(settings) = decrypt_settings(&user, &master)
        {
            result.extend(account_documents(&settings));
        }
        Ok(result)
    }

    async fn store_memory(
        &mut self,
        entry_id: &str,
        app_id: &str,
        item_type: &str,
        value: &Value,
        version: u64,
    ) -> Result<Value> {
        self.personal_memories()?;
        if validate_memory(app_id, item_type, value).is_err() {
            return Err(Error::Invalid(
                "Memory data does not match its registered type.",
            ));
        }
        let master = self.client.require_session()?.master_key.clone();
        let entry = memory_entry(entry_id, app_id, item_type, value, version, &master, now()?)?;
        self.client
            .settings_memory_exchange(
                "store_app_settings_memories_entry",
                entry,
                "app_settings_memories_entry_stored",
                entry_id,
            )
            .await?;
        Ok(json!({"success":true,"id":entry_id}))
    }

    /// Create a registered Memory; returns `{"success":true,"id":...}`.
    pub async fn create_memory(
        &mut self,
        app_id: &str,
        item_type: &str,
        value: &Value,
    ) -> Result<Value> {
        let id = uuid::Uuid::new_v4().to_string();
        self.store_memory(&id, app_id, item_type, value, 1).await
    }

    /// Replace a Memory's value at `current_version + 1`.
    pub async fn update_memory(
        &mut self,
        entry_id: &str,
        app_id: &str,
        item_type: &str,
        value: &Value,
        current_version: u64,
    ) -> Result<Value> {
        uuid::Uuid::parse_str(entry_id).map_err(|_| Error::Invalid("Invalid memory entry ID."))?;
        self.store_memory(
            entry_id,
            app_id,
            item_type,
            value,
            current_version.saturating_add(1),
        )
        .await
    }

    pub async fn delete_memory(&mut self, entry_id: &str) -> Result<Value> {
        self.personal_memories()?;
        uuid::Uuid::parse_str(entry_id).map_err(|_| Error::Invalid("Invalid memory entry ID."))?;
        self.client
            .settings_memory_exchange(
                "delete_app_settings_memories_entry",
                json!({"entry_id":entry_id}),
                "app_settings_memories_entry_deleted",
                entry_id,
            )
            .await?;
        Ok(json!({"success":true}))
    }
}

#[cfg(test)]
#[path = "memories_tests.rs"]
mod tests;
