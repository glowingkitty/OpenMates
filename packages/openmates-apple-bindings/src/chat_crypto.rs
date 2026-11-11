//! Batched, stateless chat decryption for the Apple shell (plan
//! apple-client-core-migration A3a): one call unwraps a list of chat keys, one
//! decrypts the chat-list metadata of many chats, one decrypts a message window
//! of one chat. Bindings only marshal: every item goes through the core readers
//! `openmates_sdk::crypto::decrypt_bytes` (chat-key wrappers, as `client/sync.rs`)
//! and `ChatContentCipher` (chat content, as the TUI and the web Worker).
//! Spec: `specifications/architecture/client-core` (crypto in the core, typed errors).
use crate::CoreError;
use openmates_sdk::crypto::chat_key_policy::{ChatContentCipher, ChatContentOutcome};
use openmates_sdk::crypto::decrypt_bytes;
use std::sync::OnceLock;
use std::time::Duration;
use tokio::runtime::{Builder, Runtime};
use zeroize::Zeroizing;

/// AES-256 key length of master and chat keys.
const KEY_LEN: usize = 32;
/// Thread name of the decryption pool (diagnostics and the off-thread test).
pub(crate) const POOL_THREAD_NAME: &str = "openmates-crypto";
/// At most two decrypt batches run at once; further callers queue.
const POOL_THREADS: usize = 2;
/// Idle pool threads exit quickly so extensions do not keep them.
const POOL_KEEP_ALIVE: Duration = Duration::from_secs(5);

/// Why one item of a batch could not be decrypted. The other items of the
/// batch are unaffected.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum DecryptFailure {
    /// The item's key is not 32 bytes, or an unwrapped chat key is not 32 bytes.
    InvalidKey,
    /// Not decodable base64, too short, or the AES-GCM tag did not authenticate.
    Undecryptable,
    /// The "OM" header names another key's fingerprint and no attempt
    /// authenticated (the web answers this with candidate-key recovery).
    KeyMismatch,
}

/// Result for one encrypted field.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum FieldDecryptOutcome {
    /// The plaintext. Invalid UTF-8 is replaced like the web `TextDecoder`
    /// (same reader as `crypto::decrypt_combined`).
    Decrypted {
        /// Decrypted text; secret user content, never log it.
        value: String,
    },
    /// The field stays encrypted.
    Failed {
        /// Typed reason.
        reason: DecryptFailure,
    },
}

/// One chat-key wrapper to open with the master key (Format C: base64 of
/// IV || ciphertext || tag; the "OM"-framed form is accepted too).
#[derive(Clone, Debug, uniffi::Record)]
pub struct WrappedChatKeyRecord {
    /// Chat id, echoed in the result.
    pub chat_id: String,
    /// `encrypted_chat_key` exactly as stored by the server.
    pub encrypted_chat_key: String,
}

/// Result of unwrapping one chat key.
#[derive(uniffi::Enum)]
pub enum ChatKeyUnwrapOutcome {
    /// The raw 32-byte chat key; secret, keep it in memory only.
    Unwrapped {
        /// Raw AES-256 chat key.
        chat_key: Vec<u8>,
    },
    /// The wrapper could not be opened with the master key.
    Failed {
        /// Typed reason.
        reason: DecryptFailure,
    },
}

/// One entry of `batch_unwrap_chat_keys`, in input order.
#[derive(uniffi::Record)]
pub struct UnwrappedChatKeyRecord {
    /// Chat id from the input.
    pub chat_id: String,
    /// Key or typed failure.
    pub outcome: ChatKeyUnwrapOutcome,
}

/// Encrypted chat-list metadata of one chat with its raw chat key. Leave a
/// field `nil` to skip it (for example when a plaintext value is already known).
#[derive(uniffi::Record)]
pub struct EncryptedChatMetadataRecord {
    /// Chat id, echoed in the result.
    pub chat_id: String,
    /// Raw 32-byte chat key; secret, zeroized after use.
    pub chat_key: Vec<u8>,
    /// `encrypted_title`.
    pub encrypted_title: Option<String>,
    /// `encrypted_category`.
    pub encrypted_category: Option<String>,
    /// `encrypted_icon`.
    pub encrypted_icon: Option<String>,
    /// `encrypted_chat_summary`.
    pub encrypted_chat_summary: Option<String>,
    /// `encrypted_active_focus_id`.
    pub encrypted_active_focus_id: Option<String>,
}

/// Decrypted metadata of one chat. A field is `nil` exactly when its
/// ciphertext was `nil` in the input.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ChatMetadataRecord {
    /// Chat id from the input.
    pub chat_id: String,
    /// Title.
    pub title: Option<FieldDecryptOutcome>,
    /// Category.
    pub category: Option<FieldDecryptOutcome>,
    /// Icon name.
    pub icon: Option<FieldDecryptOutcome>,
    /// Chat summary.
    pub chat_summary: Option<FieldDecryptOutcome>,
    /// Active focus id.
    pub active_focus_id: Option<FieldDecryptOutcome>,
}

/// Encrypted fields of one message (all under the chat key). Leave a field
/// `nil` to skip it.
#[derive(Clone, Debug, uniffi::Record)]
pub struct EncryptedMessageRecord {
    /// Message id, echoed in the result.
    pub message_id: String,
    /// `encrypted_content`.
    pub encrypted_content: Option<String>,
    /// `encrypted_pii_mappings` (JSON text once decrypted).
    pub encrypted_pii_mappings: Option<String>,
    /// `encrypted_thinking_content`.
    pub encrypted_thinking_content: Option<String>,
    /// `encrypted_sender_name`.
    pub encrypted_sender_name: Option<String>,
    /// `encrypted_category`.
    pub encrypted_category: Option<String>,
    /// `encrypted_model_name`.
    pub encrypted_model_name: Option<String>,
}

/// Decrypted fields of one message. A field is `nil` exactly when its
/// ciphertext was `nil` in the input.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct MessageFieldsRecord {
    /// Message id from the input.
    pub message_id: String,
    /// Message content.
    pub content: Option<FieldDecryptOutcome>,
    /// PII mappings JSON text.
    pub pii_mappings: Option<FieldDecryptOutcome>,
    /// Thinking content.
    pub thinking_content: Option<FieldDecryptOutcome>,
    /// Sender name.
    pub sender_name: Option<FieldDecryptOutcome>,
    /// Category.
    pub category: Option<FieldDecryptOutcome>,
    /// Model name.
    pub model_name: Option<FieldDecryptOutcome>,
}

/// Copy caller key bytes into a zeroizing array and wipe the caller's vector.
fn take_key(bytes: Vec<u8>) -> Option<Zeroizing<[u8; KEY_LEN]>> {
    let bytes = Zeroizing::new(bytes);
    if bytes.len() != KEY_LEN {
        return None;
    }
    let mut key = Zeroizing::new([0u8; KEY_LEN]);
    key.copy_from_slice(&bytes);
    Some(key)
}

fn open_field(
    cipher: &ChatContentCipher,
    ciphertext: Option<String>,
) -> Option<FieldDecryptOutcome> {
    let ciphertext = ciphertext?;
    Some(match cipher.decrypt(&ciphertext) {
        ChatContentOutcome::Plaintext(bytes) => FieldDecryptOutcome::Decrypted {
            value: String::from_utf8_lossy(&bytes).into_owned(),
        },
        ChatContentOutcome::FingerprintMismatch(_) => FieldDecryptOutcome::Failed {
            reason: DecryptFailure::KeyMismatch,
        },
        ChatContentOutcome::Failed => FieldDecryptOutcome::Failed {
            reason: DecryptFailure::Undecryptable,
        },
    })
}

fn failed_field(ciphertext: Option<String>) -> Option<FieldDecryptOutcome> {
    ciphertext.map(|_| FieldDecryptOutcome::Failed {
        reason: DecryptFailure::InvalidKey,
    })
}

/// Synchronous body of `batch_unwrap_chat_keys`.
pub(crate) fn unwrap_chat_keys_now(
    master_key: Vec<u8>,
    wrapped: Vec<WrappedChatKeyRecord>,
) -> Result<Vec<UnwrappedChatKeyRecord>, CoreError> {
    let master = take_key(master_key).ok_or_else(|| CoreError::Invalid {
        message: "Master key must be 32 bytes.".to_owned(),
    })?;
    Ok(wrapped
        .into_iter()
        .map(|item| {
            let outcome = match decrypt_bytes(&item.encrypted_chat_key, &master) {
                Ok(raw) if raw.len() == KEY_LEN => ChatKeyUnwrapOutcome::Unwrapped {
                    chat_key: raw.to_vec(),
                },
                Ok(_) => ChatKeyUnwrapOutcome::Failed {
                    reason: DecryptFailure::InvalidKey,
                },
                Err(_) => ChatKeyUnwrapOutcome::Failed {
                    reason: DecryptFailure::Undecryptable,
                },
            };
            UnwrappedChatKeyRecord {
                chat_id: item.chat_id,
                outcome,
            }
        })
        .collect())
}

/// Synchronous body of `batch_decrypt_chat_metadata`.
pub(crate) fn decrypt_chat_metadata_now(
    chats: Vec<EncryptedChatMetadataRecord>,
) -> Vec<ChatMetadataRecord> {
    chats
        .into_iter()
        .map(|chat| match take_key(chat.chat_key) {
            Some(key) => {
                let cipher = ChatContentCipher::new(&key);
                ChatMetadataRecord {
                    chat_id: chat.chat_id,
                    title: open_field(&cipher, chat.encrypted_title),
                    category: open_field(&cipher, chat.encrypted_category),
                    icon: open_field(&cipher, chat.encrypted_icon),
                    chat_summary: open_field(&cipher, chat.encrypted_chat_summary),
                    active_focus_id: open_field(&cipher, chat.encrypted_active_focus_id),
                }
            }
            None => ChatMetadataRecord {
                chat_id: chat.chat_id,
                title: failed_field(chat.encrypted_title),
                category: failed_field(chat.encrypted_category),
                icon: failed_field(chat.encrypted_icon),
                chat_summary: failed_field(chat.encrypted_chat_summary),
                active_focus_id: failed_field(chat.encrypted_active_focus_id),
            },
        })
        .collect()
}

/// Synchronous body of `batch_decrypt_messages`.
pub(crate) fn decrypt_messages_now(
    chat_key: Vec<u8>,
    messages: Vec<EncryptedMessageRecord>,
) -> Result<Vec<MessageFieldsRecord>, CoreError> {
    let key = take_key(chat_key).ok_or_else(|| CoreError::Invalid {
        message: "Chat key must be 32 bytes.".to_owned(),
    })?;
    // One key schedule for the whole window.
    let cipher = ChatContentCipher::new(&key);
    Ok(messages
        .into_iter()
        .map(|message| MessageFieldsRecord {
            message_id: message.message_id,
            content: open_field(&cipher, message.encrypted_content),
            pii_mappings: open_field(&cipher, message.encrypted_pii_mappings),
            thinking_content: open_field(&cipher, message.encrypted_thinking_content),
            sender_name: open_field(&cipher, message.encrypted_sender_name),
            category: open_field(&cipher, message.encrypted_category),
            model_name: open_field(&cipher, message.encrypted_model_name),
        })
        .collect())
}

/// Process-wide blocking pool for CPU-bound decryption. A runtime without
/// drivers is used only for its blocking pool: its threads start on first use
/// and exit after `POOL_KEEP_ALIVE` idle, and its join handles can be awaited
/// from any executor (UniFFI polls from the Swift side).
static POOL: OnceLock<Option<Runtime>> = OnceLock::new();

/// Run `work` on the decryption pool, never on the caller's thread. Dropping
/// the awaiting future does not stop a started batch; its result is discarded.
pub(crate) async fn on_pool<T, F>(work: F) -> Result<T, CoreError>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, CoreError> + Send + 'static,
{
    let pool = POOL
        .get_or_init(|| {
            Builder::new_current_thread()
                .thread_name(POOL_THREAD_NAME)
                .max_blocking_threads(POOL_THREADS)
                .thread_keep_alive(POOL_KEEP_ALIVE)
                .build()
                .ok()
        })
        .as_ref()
        .ok_or_else(|| CoreError::internal("decryption pool could not start"))?;
    match pool.spawn_blocking(work).await {
        Ok(result) => result,
        Err(_) => Err(CoreError::internal("decryption task panicked")),
    }
}

/// Unwrap many chat keys with the master key in one call (startup bulk load).
/// Returns one entry per input, in input order; a bad wrapper fails only its
/// own entry. Runs on the decryption pool. The master key and the caller's
/// key copies are zeroized; the returned key bytes are owned by Swift.
///
/// # Errors
/// `Invalid` when `master_key` is not 32 bytes; `Internal` if the pool fails.
#[uniffi::export]
pub async fn batch_unwrap_chat_keys(
    master_key: Vec<u8>,
    wrapped: Vec<WrappedChatKeyRecord>,
) -> Result<Vec<UnwrappedChatKeyRecord>, CoreError> {
    on_pool(move || unwrap_chat_keys_now(master_key, wrapped)).await
}

/// Decrypt the chat-list metadata (title, category, icon, summary, active
/// focus) of many chats in one call, each with its own chat key. One entry per
/// input, in input order; a bad key or field fails only that item or field.
/// Runs on the decryption pool; chat keys are zeroized after use.
///
/// # Errors
/// `Internal` only if the pool fails.
#[uniffi::export]
pub async fn batch_decrypt_chat_metadata(
    chats: Vec<EncryptedChatMetadataRecord>,
) -> Result<Vec<ChatMetadataRecord>, CoreError> {
    on_pool(move || Ok(decrypt_chat_metadata_now(chats))).await
}

/// Decrypt a window of messages of one chat in one call (chat open). One
/// entry per input, in input order; a bad field fails only that field. Runs
/// on the decryption pool; the chat key is zeroized after use.
///
/// # Errors
/// `Invalid` when `chat_key` is not 32 bytes; `Internal` if the pool fails.
#[uniffi::export]
pub async fn batch_decrypt_messages(
    chat_key: Vec<u8>,
    messages: Vec<EncryptedMessageRecord>,
) -> Result<Vec<MessageFieldsRecord>, CoreError> {
    on_pool(move || decrypt_messages_now(chat_key, messages)).await
}
