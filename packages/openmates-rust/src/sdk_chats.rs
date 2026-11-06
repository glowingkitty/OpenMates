//! Explicit API-key chat reads. Listing, search and load decrypt chat metadata,
//! messages and embeds locally with the API-key-wrapped account key, in memory
//! only. No CLI profile, cookie session, keychain or durable plaintext is used.
//! Output field names match the Python SDK (`sender_name`, `model_name`,
//! `text_preview`); npm keeps its existing camelCase message/embed names.
use crate::{Error, OpenMates, Result, crypto};
use reqwest::Method;
use serde_json::Value;
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

type ChatKey = Zeroizing<[u8; 32]>;

/// Server pagination for `list`; `limit: 0` asks the server for every chat.
#[derive(Clone, Copy, Debug)]
pub struct ChatListOptions {
    pub limit: u32,
    pub offset: u32,
}
impl Default for ChatListOptions {
    fn default() -> Self {
        Self { limit: 10, offset: 0 }
    }
}

pub struct Chats<'a> {
    pub(crate) client: &'a mut OpenMates,
}
impl<'a> Chats<'a> {
    pub(crate) fn new(client: &'a mut OpenMates) -> Self {
        Self { client }
    }
    pub(crate) async fn read(&self, path: String) -> Result<Value> {
        if self.client.is_anonymous() {
            return Err(Error::Authentication);
        }
        self.client.verify_private_operation()?;
        self.client.task_request(Method::GET, &path, None, false, None).await
    }
    /// Owned chats with locally decrypted `title`, `chat_summary`, `category`
    /// and `slug`. Rows without key material are returned unchanged.
    pub async fn list(&mut self, options: ChatListOptions) -> Result<Vec<Value>> {
        let response = self
            .read(format!("/v1/sdk/chats?limit={}&offset={}", options.limit, options.offset))
            .await?;
        let rows = match response.get("chats") {
            Some(Value::Array(rows)) => rows.clone(),
            _ => vec![],
        };
        let mut chats = Vec::with_capacity(rows.len());
        for chat in rows {
            chats.push(self.decrypt_metadata(chat, &[]).await?);
        }
        Ok(chats)
    }
    /// Case-insensitive local match over decrypted title, summary, category,
    /// slug and id. Plaintext never leaves this process.
    pub async fn search(&mut self, query: &str, options: ChatListOptions) -> Result<Vec<Value>> {
        let needle = query.trim().to_lowercase();
        let all = self.list(ChatListOptions { limit: 0, offset: 0 }).await?;
        let matches = all.into_iter().filter(|chat| {
            ["title", "chat_summary", "category", "slug", "id"]
                .iter()
                .filter_map(|key| chat[*key].as_str())
                .collect::<Vec<_>>()
                .join("\n")
                .to_lowercase()
                .contains(&needle)
        });
        let skipped = matches.skip(options.offset as usize);
        Ok(if options.limit == 0 {
            skipped.collect()
        } else {
            skipped.take(options.limit as usize).collect()
        })
    }
    /// Load one chat by canonical id, unique id prefix (8+ chars), slug or
    /// title, then decrypt its metadata, messages and embeds locally.
    pub async fn load(&mut self, chat_id: &str) -> Result<Value> {
        let resolved = self.resolve_id(chat_id).await?;
        let payload = match self.read(format!("/v1/sdk/chats/{resolved}")).await {
            Err(Error::Invalid(_)) if resolved != chat_id => {
                return Err(Error::Invalid("The chat was not found."));
            }
            other => other?,
        };
        self.decrypt_payload(payload).await
    }
    pub(crate) async fn resolve_id(&mut self, chat_id: &str) -> Result<String> {
        if is_canonical_uuid(chat_id) {
            return Ok(chat_id.to_owned());
        }
        if chat_id.is_empty() || chat_id.len() > 512 {
            return Err(Error::Invalid("Supply a chat id, slug or title."));
        }
        let chats = self.list(ChatListOptions { limit: 0, offset: 0 }).await?;
        let id_of = |chat: &Value| chat["id"].as_str().unwrap_or_default().to_owned();
        if let Some(chat) = chats.iter().find(|chat| chat["id"].as_str() == Some(chat_id)) {
            return Ok(id_of(chat));
        }
        let lower = chat_id.to_lowercase();
        let unique = |found: Vec<&Value>, ambiguous: &'static str| -> Result<Option<String>> {
            match found.as_slice() {
                [] => Ok(None),
                [chat] => Ok(Some(id_of(chat))),
                _ => Err(Error::Invalid(ambiguous)),
            }
        };
        let ambiguous = "The chat is ambiguous. Use the full chat ID.";
        if chat_id.len() >= 8 {
            let prefix = chats
                .iter()
                .filter(|chat| chat["id"].as_str().is_some_and(|id| id.to_lowercase().starts_with(&lower)))
                .collect();
            if let Some(id) = unique(prefix, ambiguous)? {
                return Ok(id);
            }
        }
        let query_slug = crypto::normalize_object_slug(chat_id).ok();
        let slugs = chats
            .iter()
            .filter(|chat| {
                query_slug.as_deref().is_some_and(|wanted| {
                    chat["slug"]
                        .as_str()
                        .filter(|slug| !slug.is_empty())
                        .and_then(|slug| crypto::normalize_object_slug(slug).ok())
                        .is_some_and(|slug| slug == wanted)
                })
            })
            .collect();
        if let Some(id) = unique(slugs, "The chat slug is ambiguous. Use the full chat ID.")? {
            return Ok(id);
        }
        let title = collapse(chat_id);
        let titles = chats
            .iter()
            .filter(|chat| chat["title"].as_str().is_some_and(|t| collapse(t) == title))
            .collect();
        if let Some(id) = unique(titles, ambiguous)? {
            return Ok(id);
        }
        Err(Error::Invalid("The chat was not found."))
    }
    pub(crate) async fn chat_key(&mut self, chat: &Value, wrappers: &[Value]) -> Result<Option<ChatKey>> {
        if chat["chat_visibility"] == "direct" {
            // Direct chats need the account chat identity enrollment, which this
            // Rust API-key slice does not implement yet. Refuse explicitly.
            return Err(Error::Unavailable {
                code: "direct_chat_unavailable",
                reason: "DIRECT_CHAT_KEY_REQUIRES_CHAT_IDENTITY",
            });
        }
        let hashed = sha256_hex(chat["id"].as_str().unwrap_or_default());
        let wrapped = wrappers
            .iter()
            .find(|row| {
                row["key_type"] == "master"
                    && row["hashed_chat_id"].as_str() == Some(hashed.as_str())
                    && row["encrypted_chat_key"].is_string()
            })
            .and_then(|row| row["encrypted_chat_key"].as_str())
            .or_else(|| chat["encrypted_chat_key"].as_str());
        let Some(wrapped) = wrapped else { return Ok(None) };
        let master = self.client.master_key().await?;
        Ok(open_key(wrapped, &master))
    }
    async fn decrypt_metadata(&mut self, chat: Value, wrappers: &[Value]) -> Result<Value> {
        let Some(key) = self.chat_key(&chat, wrappers).await? else {
            return Ok(chat);
        };
        Ok(metadata_with_key(chat, &key))
    }
    async fn decrypt_payload(&mut self, mut payload: Value) -> Result<Value> {
        if !payload["chat"].is_object() {
            return Ok(payload);
        }
        let wrappers = match (&payload["chat_key_wrappers"], &payload["chat"]["chat_key_wrappers"]) {
            (Value::Array(rows), _) | (_, Value::Array(rows)) => rows.clone(),
            _ => vec![],
        };
        let chat = payload["chat"].take();
        let key = self.chat_key(&chat, &wrappers).await?;
        let Some(key) = key else {
            payload["chat"] = chat;
            return Ok(payload);
        };
        payload["chat"] = metadata_with_key(chat, &key);
        // Mirror npm/Python: a missing or non-array messages field is untouched.
        if !payload["messages"].is_array() {
            return Ok(payload);
        }
        if let Value::Array(messages) = payload["messages"].take() {
            let mut opened = Vec::with_capacity(messages.len());
            for raw in messages {
                let mut message = match raw {
                    Value::String(text) => serde_json::from_str(&text)?,
                    other => other,
                };
                for (source, target) in [
                    ("encrypted_content", "content"),
                    ("encrypted_sender_name", "sender_name"),
                    ("encrypted_category", "category"),
                    ("encrypted_model_name", "model_name"),
                ] {
                    set_opened(&mut message, source, target, &key);
                }
                opened.push(message);
            }
            payload["messages"] = Value::Array(opened);
        }
        if !payload["embeds"].is_array() {
            return Ok(payload);
        }
        if let Value::Array(embeds) = payload["embeds"].take() {
            let keys = match &payload["embed_keys"] {
                Value::Array(rows) => rows.clone(),
                _ => vec![],
            };
            let master = self.client.master_key().await?;
            let opened = embeds
                .into_iter()
                .map(|embed| open_embed(embed, &keys, &master, &key))
                .collect();
            payload["embeds"] = Value::Array(opened);
        }
        Ok(payload)
    }
}

fn metadata_with_key(mut chat: Value, key: &[u8; 32]) -> Value {
    for (source, target) in [
        ("encrypted_title", "title"),
        ("encrypted_chat_summary", "chat_summary"),
        ("encrypted_category", "category"),
    ] {
        set_opened(&mut chat, source, target, key);
    }
    if let Some(slug) = chat["encrypted_slug"].as_str() {
        let slug = crypto::decrypt_combined(slug, key).unwrap_or_default();
        chat["slug"] = Value::String(slug);
    }
    chat
}

/// npm/Python store `null` for a field whose ciphertext fails to authenticate.
fn set_opened(row: &mut Value, source: &str, target: &str, key: &[u8; 32]) {
    if let Some(ciphertext) = row[source].as_str() {
        let opened = crypto::decrypt_combined(ciphertext, key).map(Value::String).unwrap_or(Value::Null);
        if let Value::Object(map) = row {
            map.insert(target.to_owned(), opened);
        }
    }
}

fn open_key(ciphertext: &str, key: &[u8; 32]) -> Option<ChatKey> {
    let raw = crypto::decrypt_bytes(ciphertext, key).ok()?;
    let bytes: [u8; 32] = raw.as_slice().try_into().ok()?;
    Some(Zeroizing::new(bytes))
}

fn open_embed(embed: Value, keys: &[Value], master: &[u8; 32], chat_key: &[u8; 32]) -> Value {
    let id = embed["embed_id"].as_str().or_else(|| embed["id"].as_str()).unwrap_or_default();
    if id.is_empty() {
        return embed;
    }
    let mut hashed = sha256_hex(id);
    // Result children share the parent's key only when they have no wrapper.
    if !keys.iter().any(|row| row["hashed_embed_id"].as_str() == Some(hashed.as_str()))
        && let Some(parent) = embed["parent_embed_id"].as_str().filter(|p| !p.is_empty())
    {
        hashed = sha256_hex(parent);
    }
    let row = |kind: &str| {
        keys.iter()
            .find(|row| row["hashed_embed_id"].as_str() == Some(hashed.as_str()) && row["key_type"] == kind)
            .and_then(|row| row["encrypted_embed_key"].as_str())
    };
    let embed_key = row("master")
        .and_then(|wrapped| open_key(wrapped, master))
        .or_else(|| row("chat").and_then(|wrapped| open_key(wrapped, chat_key)));
    let Some(embed_key) = embed_key else { return embed };
    let mut embed = embed;
    set_opened(&mut embed, "encrypted_type", "type", &embed_key);
    set_opened(&mut embed, "encrypted_text_preview", "text_preview", &embed_key);
    if let Some(ciphertext) = embed["encrypted_content"].as_str() {
        let content = match crypto::decrypt_combined(ciphertext, &embed_key) {
            Ok(text) => serde_json::from_str(&text).unwrap_or(Value::String(text)),
            Err(_) => Value::Null,
        };
        if let Value::Object(map) = &mut embed {
            map.insert("content".into(), content);
        }
    }
    embed
}

fn sha256_hex(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

fn collapse(value: &str) -> String {
    value.trim().to_lowercase().split_whitespace().collect::<Vec<_>>().join(" ")
}

fn is_canonical_uuid(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 36
        && bytes.iter().enumerate().all(|(index, byte)| match index {
            8 | 13 | 18 | 23 => *byte == b'-',
            _ => byte.is_ascii_hexdigit(),
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn canonical_uuid_shape_only() {
        assert!(is_canonical_uuid("11111111-1111-4111-8111-111111111111"));
        assert!(!is_canonical_uuid("11111111-1111-4111-8111-11111111111"));
        assert!(!is_canonical_uuid("my-chat"));
    }

    #[test]
    fn metadata_decrypts_and_failed_fields_become_null() {
        let key = [7u8; 32];
        let other = [9u8; 32];
        let chat = json!({
            "id": "c",
            "encrypted_title": crypto::encrypt_combined("Title", &key).unwrap(),
            "encrypted_category": crypto::encrypt_combined("x", &other).unwrap(),
            "encrypted_slug": crypto::encrypt_combined("my-slug", &key).unwrap(),
        });
        let opened = metadata_with_key(chat, &key);
        assert_eq!(opened["title"], "Title");
        assert_eq!(opened["category"], Value::Null);
        assert_eq!(opened["slug"], "my-slug");
    }

    #[test]
    fn child_embed_uses_parent_key_and_parses_json_content() {
        let master = [1u8; 32];
        let chat_key = [2u8; 32];
        let embed_key = [3u8; 32];
        let keys = vec![json!({
            "hashed_embed_id": sha256_hex("parent"),
            "key_type": "chat",
            "encrypted_embed_key": crypto::encrypt_bytes(&embed_key, &chat_key).unwrap(),
        })];
        let child = json!({
            "embed_id": "child",
            "parent_embed_id": "parent",
            "encrypted_type": crypto::encrypt_combined("web-website", &embed_key).unwrap(),
            "encrypted_content": crypto::encrypt_combined("{\"a\":1}", &embed_key).unwrap(),
        });
        let opened = open_embed(child, &keys, &master, &chat_key);
        assert_eq!(opened["type"], "web-website");
        assert_eq!(opened["content"], json!({"a": 1}));
    }
}
