//! API-key Memories (npm `client.memories`). Entries are user-private: item JSON is
//! encrypted and decrypted locally with the API-key-wrapped account master key; the
//! server only sees the hashed item key, ciphertext and version metadata.
//!
//! Create, update and types were removed on 2026-11-07 (the backend answers 410),
//! matching npm and Python: only list, published and delete remain.
use crate::{Error, OpenMates, Result, crypto, sdk_ops::segment, sdk_transport::with_query};
use serde_json::{Value, json};
use zeroize::Zeroizing;

/// Decrypted memory plaintext exactly like npm `memories.list` (`parseMaybeJson`):
/// empty plaintext is `null`, JSON wins, then the shared non-strict TOON decoder
/// ([`crate::toon_decode`], the `@toon-format/toon` `strict: false` reading), and
/// only text neither can read stays the raw string. Proved by the `sdk.memories`
/// vectors in `tests/sdk-conformance/fixtures/sdk-api-key-wire.json`.
fn memory_data(text: &str) -> Value {
    if text.is_empty() {
        return Value::Null;
    }
    if let Ok(json) = serde_json::from_str(text) {
        return json;
    }
    match crate::toon_decode::decode(text) {
        Ok(value) => value.to_json_value(),
        // Not readable as TOON either: npm keeps the plaintext string.
        Err(_) => Value::String(text.to_owned()),
    }
}

fn decrypt_row(row: &Value, master: &[u8; 32]) -> Result<Value> {
    let mut decrypted = row.clone();
    if let Some(ciphertext) = row.get("encrypted_item_json").and_then(Value::as_str) {
        // Like npm, an unauthenticated or empty plaintext yields `data: null`.
        decrypted["data"] = match crypto::decrypt_combined(ciphertext, master) {
            Ok(text) => memory_data(&Zeroizing::new(text)),
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
    ///
    /// An empty `app_id` reads every app, like npm/Python (falsy id). The id is
    /// one path segment encoded like npm `encodeURIComponent` (space is `%20`,
    /// never the form `+`).
    ///
    /// # Errors
    /// Transport and protocol errors from the public metadata read.
    pub async fn published(&self, app_id: Option<&str>) -> Result<Value> {
        if let Some(app_id) = app_id.filter(|id| !id.is_empty()) {
            let encoded = segment(app_id)?;
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
    /// Transitional delete of one legacy typed entry; needs `confirmed = true`.
    /// The id is one `encodeURIComponent`-style path segment (npm/Python parity).
    ///
    /// # Errors
    /// [`Error::Invalid`] without confirmation or for an empty id; otherwise the
    /// typed transport error.
    pub async fn delete(&self, id: &str, confirmed: bool) -> Result<Value> {
        if !confirmed {
            return Err(Error::Invalid("Deleting a memory requires confirmed: true"));
        }
        let encoded = segment(id)?;
        self.client
            .delete(&format!("/v1/sdk/memories/{encoded}"))
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
