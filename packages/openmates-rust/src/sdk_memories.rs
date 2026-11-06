//! API-key Memories (npm `client.memories`). Entries are user-private: item JSON is
//! encrypted and decrypted locally with the API-key-wrapped account master key; the
//! server only sees the hashed item key, ciphertext and version metadata.
use crate::{Error, OpenMates, Result, crypto, sdk_transport::with_query};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

/// Create/update input. `item_value` that is not a JSON object is stored as `{"value": ...}`.
#[derive(Clone, Default)]
pub struct MemoryInput {
    pub id: Option<String>,
    pub app_id: String,
    pub item_type: String,
    pub item_value: Value,
    pub item_version: Option<u64>,
    pub created_at: Option<i64>,
}

/// npm `hashItemKey`: first 32 hex chars of sha256("{app}-{type}-{millis}").
pub fn hash_item_key(app_id: &str, item_type: &str, millis: u128) -> String {
    let digest = Sha256::digest(format!("{app_id}-{item_type}-{millis}").as_bytes());
    digest
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>()[..32]
        .to_owned()
}

/// Item plaintext exactly as npm `storeMemory` builds it.
pub fn memory_plaintext(
    app_id: &str,
    item_type: &str,
    value: &Value,
    added_date: u64,
) -> Zeroizing<String> {
    let mut item: Map<String, Value> = match value {
        Value::Object(map) => map.clone(),
        other => {
            let mut map = Map::new();
            map.insert("value".into(), other.clone());
            map
        }
    };
    item.insert("settings_group".into(), json!(app_id));
    item.insert("_original_item_key".into(), json!(item_type));
    item.insert("added_date".into(), json!(added_date));
    Zeroizing::new(Value::Object(item).to_string())
}

fn decrypt_row(row: &Value, master: &[u8; 32]) -> Result<Value> {
    let mut decrypted = row.clone();
    if let Some(ciphertext) = row.get("encrypted_item_json").and_then(Value::as_str) {
        // Like npm, an unauthenticated or empty plaintext yields `data: null`.
        decrypted["data"] = match crypto::decrypt_combined(ciphertext, master) {
            Ok(text) => {
                let text = Zeroizing::new(text);
                serde_json::from_str(&text).unwrap_or_else(|_| Value::String(text.to_string()))
            }
            Err(Error::Crypto) => Value::Null,
            Err(error) => return Err(error),
        };
    }
    Ok(decrypted)
}

pub struct Memories<'a> {
    client: &'a mut OpenMates,
}
impl<'a> Memories<'a> {
    pub(crate) fn new(client: &'a mut OpenMates) -> Self {
        Self { client }
    }
    /// Reviewed read-only app guidance; independent of private encrypted entries.
    pub async fn published(&self, app_id: Option<&str>) -> Result<Value> {
        if let Some(app_id) = app_id {
            let encoded: String = url::form_urlencoded::byte_serialize(app_id.as_bytes()).collect();
            let app = self
                .client
                .get_public(&format!(
                    "/v1/apps/{encoded}/metadata?include_unavailable=true"
                ))
                .await?;
            return Ok(json!({"memories": app.get("memories").cloned().unwrap_or(json!([]))}));
        }
        let metadata = self
            .client
            .get_public("/v1/apps/metadata?include_unavailable=true")
            .await?;
        let mut all = vec![];
        for app in metadata
            .get("apps")
            .and_then(Value::as_object)
            .ok_or(Error::Protocol)?
            .values()
        {
            if let Some(items) = app.get("memories").and_then(Value::as_array) {
                all.extend(items.iter().cloned());
            }
        }
        Ok(json!({"memories": all}))
    }
    /// `query` pairs are forwarded (for example `app_id`, `item_type`).
    pub async fn list(&mut self, query: &[(&str, Option<String>)]) -> Result<Value> {
        let data = self
            .client
            .get(&with_query("/v1/sdk/memories", query))
            .await?;
        let rows = data
            .get("memories")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let mut memories = Vec::with_capacity(rows.len());
        for row in &rows {
            let master = if row.get("encrypted_item_json").is_some_and(Value::is_string) {
                Some(self.client.master_key().await?)
            } else {
                None
            };
            memories.push(match master {
                Some(master) => decrypt_row(row, &master)?,
                None => row.clone(),
            });
        }
        Ok(json!({"memories": memories}))
    }
    pub async fn types(&self, query: &[(&str, Option<String>)]) -> Result<Value> {
        self.client
            .get(&with_query("/v1/sdk/memories/types", query))
            .await
    }
    pub async fn create(&mut self, input: MemoryInput) -> Result<Value> {
        self.store(input).await
    }
    pub async fn update(&mut self, id: &str, mut input: MemoryInput) -> Result<Value> {
        input.id = Some(id.to_owned());
        self.store(input).await
    }
    pub async fn delete(&self, id: &str, confirmed: bool) -> Result<Value> {
        if !confirmed {
            return Err(Error::Invalid("Deleting a memory requires confirmed: true"));
        }
        let encoded: String = url::form_urlencoded::byte_serialize(id.as_bytes()).collect();
        self.client
            .delete(&format!("/v1/sdk/memories/{encoded}"))
            .await
    }
    async fn store(&mut self, input: MemoryInput) -> Result<Value> {
        if input.app_id.is_empty() || input.item_type.is_empty() {
            return Err(Error::Invalid(
                "Memory create/update requires appId and itemType",
            ));
        }
        self.client.verify_private_operation()?;
        let elapsed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| Error::Protocol)?;
        let now = elapsed.as_secs();
        let master = self.client.master_key().await?;
        let plaintext = memory_plaintext(&input.app_id, &input.item_type, &input.item_value, now);
        let entry = json!({
            "id": input.id.unwrap_or_else(|| uuid::Uuid::new_v4().to_string()),
            "app_id": input.app_id,
            "item_key": hash_item_key(&input.app_id, &input.item_type, elapsed.as_millis()),
            "item_type": input.item_type,
            "encrypted_item_json": crypto::encrypt_combined(&plaintext, &master)?,
            "encrypted_app_key": "",
            "created_at": input.created_at.unwrap_or(now as i64),
            "updated_at": now,
            "item_version": input.item_version.unwrap_or(1),
        });
        self.client
            .post("/v1/sdk/memories", json!({"entry": entry}))
            .await
    }
}
impl OpenMates {
    pub fn memories(&mut self) -> Memories<'_> {
        Memories::new(self)
    }
}

#[cfg(test)]
#[path = "sdk_memories_tests.rs"]
mod tests;
