//! Test-only fixture for Swift and Rust tests of `ViewModelCore` without a
//! server: writes the encrypted core cache an earlier app run would have left
//! (synthetic chats and messages, real core encryption and cache format) and
//! returns the credential payload a `CredentialStore` double returns from
//! `load()`. Compiled only for tests and with the `test-support` feature, so
//! it never ships in a product build. Plan `apple-client-core-migration` (a4
//! lane 0). All content is synthetic (`example.org`-style placeholders).
use crate::CoreError;
use futures_util::future::BoxFuture;
use openmates_sdk::{
    Client,
    client::CredentialSnapshot,
    crypto::{Key, encrypt_bytes, encrypt_combined, random_key},
    error::Result,
    local_cache::{CacheEngine, CacheStore, FileByteStore, FixedContext, NoScope, OrderedBlocking},
    session::Session,
    shell_session::{CredentialPersistence, CredentialSave, ShellSession, session_cache_context},
};
use serde_json::{Value, json};
use std::{path::Path, sync::Arc};

/// Most chats one fixture writes (keeps a test cache small).
const MAX_CHATS: u32 = 500;
/// Most messages of the first chat.
const MAX_MESSAGES: u32 = 2_000;
/// Base of the synthetic server timestamps.
const BASE_TIME: i64 = 1_700_000_000;

/// Id of synthetic chat `index` (`00000000-0000-4000-8000-…`).
fn chat_id(index: u32) -> String {
    format!("00000000-0000-4000-8000-{:012x}", u64::from(index) + 1)
}

/// Id of synthetic message `index` of chat `chat` (client message id).
fn message_id(chat: u32, index: u32) -> String {
    format!(
        "{:08x}-0000-4000-9000-{:012x}",
        chat + 1,
        u64::from(index) + 1
    )
}

fn sealed(text: &str, key: &Key) -> std::result::Result<String, CoreError> {
    Ok(encrypt_combined(text, key)?)
}

/// One stored message row: even indexes are user messages, odd ones the
/// assistant reply to the message before (with model and category).
fn message_row(chat: u32, index: u32, key: &Key) -> std::result::Result<Value, CoreError> {
    let id = message_id(chat, index);
    let created_at = BASE_TIME + i64::from(index);
    if index % 2 == 0 {
        return Ok(json!({
            "id": id, "client_message_id": id, "chat_id": chat_id(chat),
            "role": "user", "created_at": created_at, "status": "synced",
            "encrypted_content": sealed(&format!("Synthetic question {}", index / 2 + 1), key)?,
        }));
    }
    Ok(json!({
        "id": id, "client_message_id": id, "chat_id": chat_id(chat),
        "role": "assistant", "created_at": created_at, "status": "synced",
        "user_message_id": message_id(chat, index - 1),
        "encrypted_content": sealed(&format!("Synthetic answer {}", index / 2 + 1), key)?,
        "encrypted_sender_name": sealed("Synthetic mate", key)?,
        "encrypted_category": sealed("general_knowledge", key)?,
        "encrypted_model_name": sealed("synthetic-model", key)?,
    }))
}

/// Chat row `index`; the first chat is the most recently edited one.
fn chat_row(
    index: u32,
    chats: u32,
    messages: u32,
    key: &Key,
    master: &Key,
) -> std::result::Result<Value, CoreError> {
    let edited = BASE_TIME + i64::from(chats - index) * 60;
    Ok(json!({
        "id": chat_id(index), "messages_v": messages, "created_at": BASE_TIME,
        "updated_at": edited, "last_edited_overall_timestamp": edited,
        "last_message_timestamp": edited,
        "encrypted_chat_key": encrypt_bytes(key.as_slice(), master)?,
        "encrypted_title": sealed(&format!("Synthetic chat {}", index + 1), key)?,
        "encrypted_icon": sealed("message-circle", key)?,
        "encrypted_category": sealed("general_knowledge", key)?,
    }))
}

/// The ciphertext snapshot of `chats` chats: the first holds `messages`
/// messages, every other one message.
fn snapshot(chats: u32, messages: u32, master: &Key) -> std::result::Result<Value, CoreError> {
    let (mut rows, mut history) = (serde_json::Map::new(), serde_json::Map::new());
    for chat in 0..chats {
        let key = random_key();
        let count = if chat == 0 { messages } else { 1 };
        rows.insert(chat_id(chat), chat_row(chat, chats, count, &key, master)?);
        let messages = (0..count)
            .map(|index| message_row(chat, index, &key))
            .collect::<std::result::Result<Vec<_>, _>>()?;
        history.insert(chat_id(chat), Value::Array(messages));
    }
    Ok(json!({"chats": rows, "wrappers": [], "history": history,
        "embeds": {}, "embed_keys": [], "team_wrapped_key": null}))
}

/// Credentials that are already "stored" (the payload this fixture returns).
struct Seeded(Session);

impl CredentialPersistence for Seeded {
    fn load(&self, _generation: u64) -> BoxFuture<'_, Result<Option<Session>>> {
        Box::pin(async { Ok(Some(self.0.clone())) })
    }
    fn store(&self, _: CredentialSnapshot, _: u64) -> BoxFuture<'_, Result<CredentialSave>> {
        Box::pin(async { Ok(CredentialSave::Saved) })
    }
    fn revoke(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async { Ok(()) })
    }
    fn clear(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async { Ok(()) })
    }
}

/// Write an encrypted core cache of `chat_count` synthetic chats into
/// `cache_directory_name` inside `cache_container` (the same pair passed to
/// `ViewModelCore` in `CoreConfig`) and return the credential payload of its
/// synthetic account. A `CredentialStore` double returns that payload from
/// `load()`; `start` then emits `Session(Restored)` and `ChatList(Cached)`
/// with every chat (newest first: "Synthetic chat 1" holds
/// `message_count` messages, alternating user and assistant, every other
/// chat one message) before it tries the network. The account exists on no
/// server: admission fails (`Offline` for an unreachable `api_url`), and
/// chat windows come from the cache only. Blocks the calling thread; never
/// call it from an async context.
///
/// # Errors
/// `Invalid` for zero chats, more than 500 chats, more than 2000 messages,
/// or a bad cache path; cache write and encryption errors.
#[uniffi::export]
pub fn test_support_seed_cached_account(
    api_url: String,
    cache_container: String,
    cache_directory_name: String,
    chat_count: u32,
    message_count: u32,
) -> std::result::Result<Vec<u8>, CoreError> {
    if chat_count == 0 || chat_count > MAX_CHATS || message_count > MAX_MESSAGES {
        return Err(CoreError::Invalid {
            message: "Seed 1 to 500 chats and at most 2000 messages.".to_owned(),
        });
    }
    let session = Session {
        api_url,
        session_id: "synthetic-fixture-session".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: random_key(),
        hashed_email: "synthetic-fixture-owner".into(),
        user_email_salt: "synthetic-fixture-salt".into(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let snapshot = snapshot(chat_count, message_count, &session.master_key)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|_| CoreError::Io)?;
    runtime.block_on(async {
        let bytes = FileByteStore::open_in(Path::new(&cache_container), &cache_directory_name)
            .map_err(|_| CoreError::Invalid {
                message: "The cache container or directory name is not usable.".to_owned(),
            })?;
        let cache = CacheStore::new(
            Arc::new(CacheEngine::new(bytes)),
            Arc::new(FixedContext(session_cache_context(&session)?)),
            Arc::new(NoScope),
            OrderedBlocking::new(),
        );
        // The client validates its origin with the HTTP client, which needs
        // the runtime's reactor.
        let mut client = Client::new(&session.api_url, Some(session.clone()))?;
        client.restore_ciphertext_snapshot(&snapshot)?;
        ShellSession::new(cache)
            .persist(&mut client, &Seeded(session.clone()))
            .await?;
        Ok::<_, CoreError>(())
    })?;
    serde_json::to_vec(&session).map_err(|_| CoreError::Protocol)
}
