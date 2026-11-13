//! Private message bookmarks (`messageBookmarks.ts`): navigation metadata
//! only, never message bodies, annotations or AI context.
//!
//! Account mode stores `{version: 1, chats: {chat_id: [message_id]}}` under
//! `message_bookmarks` inside the master-key encrypted account settings (the
//! same Format D blob posted to `/v1/settings/encrypted-account`). Every other
//! settings key is carried through as its original JSON text so no unrelated
//! value changes type or precision. Device mode stores a JSON array per chat in
//! localStorage; transient mode stays in adapter memory. The adapter owns the
//! HTTP post, the owner/epoch/ciphertext scope fences and the per-scope queue.
use super::js::{js_property_order, json_string, utf16_len};
use crate::crypto::master::MasterCapability;
use crate::{Error, Result};
use serde::de::{Deserializer, MapAccess, Visitor};
use serde_json::{Value, value::RawValue};
use std::fmt;

pub const SETTINGS_KEY: &str = "message_bookmarks";
pub const DEVICE_PREFIX: &str = "openmates:message-bookmarks:v1:";
pub const MAX_BOOKMARKS: usize = 10_000;
const UNAVAILABLE: Error = Error::Invalid("Bookmark settings unavailable");
const LIMIT: Error = Error::Invalid("Bookmark limit reached");
const IDENTITY: Error = Error::Invalid("Bookmark identity unavailable");

/// `identity()`: 1..=256 UTF-16 units, no code point below U+0020.
pub fn valid_identity(value: &str) -> bool {
    !value.is_empty() && utf16_len(value) <= 256 && value.chars().all(|c| c >= ' ')
}

/// One requested toggle. `legacy_ids` are earlier aliases of the same message.
pub struct BookmarkToggle<'a> {
    pub chat_id: &'a str,
    pub message_id: &'a str,
    pub legacy_ids: &'a [String],
}

impl BookmarkToggle<'_> {
    fn validate(&self) -> Result<()> {
        if !valid_identity(self.chat_id)
            || !valid_identity(self.message_id)
            || self.legacy_ids.len() > 2
            || !self.legacy_ids.iter().all(|id| valid_identity(id))
        {
            return Err(IDENTITY);
        }
        Ok(())
    }
    /// Remove every alias when any is saved, otherwise save the current id.
    fn apply(&self, ids: &mut Vec<String>) {
        let is_alias = |id: &String| id == self.message_id || self.legacy_ids.contains(id);
        if ids.iter().any(is_alias) {
            ids.retain(|id| !is_alias(id));
        } else {
            ids.push(self.message_id.to_owned());
        }
    }
}

/// Decoded account bookmarks in JavaScript `Map` order.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BookmarkIndex {
    chats: Vec<(String, Vec<String>)>,
}

impl BookmarkIndex {
    pub fn ids(&self, chat_id: &str) -> Vec<String> {
        self.chats
            .iter()
            .find(|(chat, _)| chat == chat_id)
            .map(|(_, ids)| ids.clone())
            .unwrap_or_default()
    }
    pub fn total(&self) -> usize {
        self.chats.iter().map(|(_, ids)| ids.len()).sum()
    }
    /// `{chat_id: [message_id]}` for the adapter's in-memory snapshot.
    pub fn to_json(&self) -> String {
        object_json(
            self.chats
                .iter()
                .map(|(chat, ids)| (chat.clone(), string_array(ids)))
                .collect(),
        )
    }
    fn set(&mut self, chat_id: &str, ids: Vec<String>) {
        if let Some(slot) = self.chats.iter_mut().find(|(chat, _)| chat == chat_id) {
            slot.1 = ids;
        } else {
            self.chats.push((chat_id.to_owned(), ids));
        }
    }
    fn delete(&mut self, chat_id: &str) {
        self.chats.retain(|(chat, _)| chat != chat_id);
    }
    fn settings_value(&self) -> String {
        format!("{{\"version\":1,\"chats\":{}}}", self.to_json())
    }
}

/// A plain JSON object kept as ordered (key, original JSON text) pairs. Also
/// used by `client::memory_documents` for the same encrypted account settings.
pub(crate) struct OrderedObject(Vec<(String, Box<RawValue>)>);

impl<'de> serde::Deserialize<'de> for OrderedObject {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        struct Pairs;
        impl<'de> Visitor<'de> for Pairs {
            type Value = OrderedObject;
            fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
                formatter.write_str("a JSON object")
            }
            fn visit_map<A: MapAccess<'de>>(
                self,
                mut map: A,
            ) -> std::result::Result<OrderedObject, A::Error> {
                let mut pairs = Vec::new();
                while let Some((key, value)) = map.next_entry::<String, Box<RawValue>>()? {
                    pairs.push((key, value));
                }
                Ok(OrderedObject(js_property_order(pairs)))
            }
        }
        deserializer.deserialize_map(Pairs)
    }
}

impl OrderedObject {
    /// An empty object (no account settings yet).
    pub(crate) fn empty() -> Self {
        Self(Vec::new())
    }
    /// Parse a JSON object; anything else is the bookmark "unavailable" error.
    pub(crate) fn parse(json: &str) -> Result<Self> {
        serde_json::from_str(json).map_err(|_| UNAVAILABLE)
    }
    /// Original JSON text of `key`, if present.
    pub(crate) fn get(&self, key: &str) -> Option<&RawValue> {
        self.0
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_ref())
    }
    /// Replace (in place) or append `key` with already serialized JSON.
    pub(crate) fn set(&mut self, key: &str, json: String) -> Result<()> {
        let raw = RawValue::from_string(json).map_err(|_| Error::Protocol)?;
        if let Some(slot) = self.0.iter_mut().find(|(k, _)| k == key) {
            slot.1 = raw;
        } else {
            self.0.push((key.to_owned(), raw));
        }
        Ok(())
    }
    /// `JSON.stringify` of the object in JavaScript property order.
    pub(crate) fn to_json(&self) -> String {
        object_json(
            self.0
                .iter()
                .map(|(k, v)| (k.clone(), v.get().to_owned()))
                .collect(),
        )
    }
}

fn object_json(pairs: Vec<(String, String)>) -> String {
    let body: Vec<String> = js_property_order(pairs)
        .into_iter()
        .map(|(k, v)| format!("{}:{v}", json_string(&k)))
        .collect();
    format!("{{{}}}", body.join(","))
}

fn string_array(ids: &[String]) -> String {
    serde_json::to_string(ids).expect("string array serialization is infallible")
}

/// `[...new Set(ids)]` after validating every element as an identity.
fn identity_set(values: &[Value]) -> Option<Vec<String>> {
    let mut ids: Vec<String> = Vec::with_capacity(values.len());
    for value in values {
        let id = value.as_str().filter(|id| valid_identity(id))?;
        if !ids.iter().any(|existing| existing == id) {
            ids.push(id.to_owned());
        }
    }
    Some(ids)
}

/// `decode(value[SETTINGS_KEY])`.
fn decode(value: Option<&RawValue>) -> Result<BookmarkIndex> {
    let Some(raw) = value else {
        return Ok(BookmarkIndex::default());
    };
    let record = OrderedObject::parse(raw.get())?;
    let version: Value = record
        .get("version")
        .map(|v| serde_json::from_str(v.get()))
        .transpose()?
        .unwrap_or(Value::Null);
    if version.as_f64() != Some(1.0) {
        return Err(UNAVAILABLE);
    }
    let chats = OrderedObject::parse(record.get("chats").ok_or(UNAVAILABLE)?.get())?;
    let mut index = BookmarkIndex::default();
    let mut count = 0usize;
    for (chat, ids) in chats.0 {
        let ids: Value = serde_json::from_str(ids.get())?;
        let ids = ids
            .as_array()
            .filter(|_| valid_identity(&chat))
            .ok_or(UNAVAILABLE)?;
        count += ids.len();
        let ids = identity_set(ids).ok_or(UNAVAILABLE)?;
        if count > MAX_BOOKMARKS {
            return Err(UNAVAILABLE);
        }
        index.chats.push((chat, ids));
    }
    Ok(index)
}

fn settings(plaintext: Option<&str>) -> Result<OrderedObject> {
    plaintext.map_or(Ok(OrderedObject(Vec::new())), OrderedObject::parse)
}

/// Decode bookmarks from decrypted account settings (`None` = no settings).
pub fn decode_account_settings(plaintext: Option<&str>) -> Result<BookmarkIndex> {
    decode(settings(plaintext)?.get(SETTINGS_KEY))
}

/// Toggle against decrypted settings; returns the new settings plaintext.
pub fn toggle_account_plaintext(
    plaintext: Option<&str>,
    toggle: &BookmarkToggle<'_>,
) -> Result<(String, BookmarkIndex)> {
    toggle.validate()?;
    let mut value = settings(plaintext)?;
    let mut index = decode(value.get(SETTINGS_KEY))?;
    let mut ids = index.ids(toggle.chat_id);
    toggle.apply(&mut ids);
    if ids.is_empty() {
        index.delete(toggle.chat_id);
    } else {
        index.set(toggle.chat_id, ids);
    }
    if index.total() > MAX_BOOKMARKS {
        return Err(LIMIT);
    }
    value.set(SETTINGS_KEY, index.settings_value())?;
    Ok((value.to_json(), index))
}

async fn decrypt_settings(
    master: &MasterCapability,
    ciphertext: Option<&str>,
) -> Result<Option<String>> {
    match ciphertext.filter(|c| !c.is_empty()) {
        None => Ok(None),
        Some(ciphertext) => match master.decrypt_text(ciphertext).await {
            Ok(plaintext) => Ok(Some(plaintext)),
            Err(Error::Crypto) => Err(UNAVAILABLE),
            Err(other) => Err(other),
        },
    }
}

/// Load account bookmarks from the current `encrypted_settings`.
pub async fn read_account_bookmarks(
    master: &MasterCapability,
    ciphertext: Option<&str>,
) -> Result<BookmarkIndex> {
    decode_account_settings(decrypt_settings(master, ciphertext).await?.as_deref())
}

pub struct AccountBookmarkWrite {
    /// New `encrypted_settings` to post; the adapter publishes it only after
    /// the server accepted it and the owner/epoch/ciphertext scope still holds.
    pub encrypted_settings: String,
    pub index: BookmarkIndex,
}

pub async fn toggle_account_bookmark(
    master: &MasterCapability,
    ciphertext: Option<&str>,
    toggle: &BookmarkToggle<'_>,
) -> Result<AccountBookmarkWrite> {
    toggle.validate()?;
    let plaintext = zeroize::Zeroizing::new(decrypt_settings(master, ciphertext).await?);
    let (next, index) = toggle_account_plaintext(plaintext.as_deref(), toggle)?;
    let next = zeroize::Zeroizing::new(next);
    let encrypted_settings = master.encrypt_server_bytes(next.as_bytes()).await?;
    Ok(AccountBookmarkWrite {
        encrypted_settings,
        index,
    })
}

/// Device-mode localStorage value for one chat (`None`/empty = no entry).
pub fn decode_device_bookmarks(raw: Option<&str>) -> Result<Vec<String>> {
    let Some(raw) = raw.filter(|raw| !raw.is_empty()) else {
        return Ok(Vec::new());
    };
    let value: Value = serde_json::from_str(raw).map_err(|_| UNAVAILABLE)?;
    let values = value
        .as_array()
        .filter(|values| values.len() <= MAX_BOOKMARKS)
        .ok_or(UNAVAILABLE)?;
    identity_set(values).ok_or(UNAVAILABLE)
}

pub fn encode_device_bookmarks(ids: &[String]) -> String {
    string_array(ids)
}

/// Device/transient toggle over the chat's current ids.
pub fn toggle_local_bookmark(
    mut ids: Vec<String>,
    toggle: &BookmarkToggle<'_>,
) -> Result<Vec<String>> {
    toggle.validate()?;
    toggle.apply(&mut ids);
    if ids.len() > MAX_BOOKMARKS {
        return Err(LIMIT);
    }
    Ok(ids)
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "bookmarks_tests.rs"]
mod tests;
