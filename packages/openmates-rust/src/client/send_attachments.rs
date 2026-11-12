//! Composer attachments and caller PII mappings of one send turn: embeds the
//! shell already created or uploaded (images, PDFs, files, recordings, pasted
//! code/text, URL previews) become the message's markdown references, the
//! cleartext `embeds` the server caches for inference, and the client-encrypted
//! `encrypted_embeds` bundle it stores. Mirrors web `sendersChatMessages.ts`
//! (`EmbedForServer`, `EncryptedEmbedForDirectus`) and Apple
//! `ChatSendPipeline.encryptedEmbeds`; spec `client-core`, plan
//! `apple-client-core-migration`.
use super::embed_write::keys::{
    OsNonces, derive_embed_key, encrypt_text, hash_id, wrap_key, wrap_key_with_master,
};
use crate::crypto::master::MasterCapability;
use crate::error::{Error, Result};
use serde_json::{Value, json};
use zeroize::Zeroizing;

/// Most embeds one turn may carry.
pub const MAX_SEND_EMBEDS: usize = 64;
/// Longest single embed content, in UTF-8 bytes.
pub const MAX_SEND_EMBED_CONTENT_BYTES: usize = 8 * 1024 * 1024;
/// Largest combined embed content of one turn, in UTF-8 bytes.
pub const MAX_SEND_EMBEDS_TOTAL_BYTES: usize = 16 * 1024 * 1024;
/// Most caller PII mappings one turn may carry.
pub const MAX_SEND_PII_MAPPINGS: usize = 1024;

/// One embed the composer attaches to this turn.
///
/// The shell passes presentation data and opaque ids only: the core derives
/// the embed key from the chat key (`deriveEmbedKeyFromChatKey`), wraps it
/// with the chat key and the master key, and encrypts type, content and
/// preview. No key crosses the shell boundary. `content` is the plaintext the
/// server receives for inference (TOON or JSON, exactly as created by the
/// upload or embed preparation); it may carry the upload's file keys, as on
/// web, so it is zeroized on drop and never printed.
#[derive(Clone, Default, PartialEq, Eq)]
pub struct SendEmbed {
    /// Embed id (web: UUID); `[A-Za-z0-9_-]`, 1–128 characters.
    pub embed_id: String,
    /// Decrypted embed type, e.g. `image`, `pdf`, `code-code`.
    pub kind: String,
    /// Type in the message's markdown reference block (`referenceType`);
    /// `None` uses `kind`.
    pub reference_type: Option<String>,
    /// Embed status (`finished`, `processing`, …).
    pub status: String,
    /// Plaintext content of a new embed. `None` attaches an embed that is
    /// already stored for this account (reference only: no bundle, no
    /// cleartext copy).
    pub content: Option<Zeroizing<String>>,
    /// Optional plaintext preview.
    pub text_preview: Option<Zeroizing<String>>,
    /// Child embed ids of a composite embed.
    pub embed_ids: Option<Vec<String>>,
}

impl std::fmt::Debug for SendEmbed {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // Content and preview are private (and may hold upload keys).
        f.debug_struct("SendEmbed")
            .field("embed_id", &self.embed_id)
            .field("kind", &self.kind)
            .field("status", &self.status)
            .field("has_content", &self.content.is_some())
            .finish()
    }
}

/// A placeholder the shell already put into the text or an attachment (for
/// example a redacted document), stored with the message so it restores.
#[derive(Clone, Default, PartialEq, Eq)]
pub struct SendPiiMapping {
    /// The `[…]` token in the sent text.
    pub placeholder: String,
    /// The original value (personal data, zeroized, never printed).
    pub original: Zeroizing<String>,
    /// Category (`EMAIL`, `PHONE`, …); empty becomes `OTHER`.
    pub kind: String,
}

impl std::fmt::Debug for SendPiiMapping {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SendPiiMapping")
            .field("placeholder", &self.placeholder)
            .field("kind", &self.kind)
            .finish()
    }
}

impl SendPiiMapping {
    /// The mapping value `privacy::prepare` and the encrypted message store.
    pub(crate) fn to_value(&self) -> Value {
        let kind = if self.kind.is_empty() {
            "OTHER"
        } else {
            self.kind.as_str()
        };
        json!({"original": self.original.as_str(), "placeholder": self.placeholder, "type": kind})
    }
}

fn plain_id(value: &str, max: usize) -> bool {
    !value.is_empty()
        && value.len() <= max
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

fn plain_kind(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
}

/// Refuse malformed attachments and mappings before anything is shown or
/// sent. Ids and types are restricted because they are written verbatim into
/// the message's JSON reference block.
///
/// # Errors
/// `Invalid` for a bad or duplicate id, type or status, an empty or
/// oversized content, too many embeds, a reference-only embed in a volatile
/// chat, or a malformed PII mapping.
pub(crate) fn validate(
    embeds: &[SendEmbed],
    mappings: &[SendPiiMapping],
    volatile: bool,
) -> Result<()> {
    if embeds.len() > MAX_SEND_EMBEDS {
        return Err(Error::Invalid(
            "A message can carry at most 64 attachments.",
        ));
    }
    let mut seen = std::collections::HashSet::new();
    let mut total = 0usize;
    for embed in embeds {
        if !plain_id(&embed.embed_id, 128) || !seen.insert(embed.embed_id.as_str()) {
            return Err(Error::Invalid(
                "An attachment has an invalid or duplicate embed ID.",
            ));
        }
        if !plain_kind(&embed.kind)
            || embed
                .reference_type
                .as_deref()
                .is_some_and(|t| !plain_kind(t))
        {
            return Err(Error::Invalid("An attachment has an invalid embed type."));
        }
        if !plain_id(&embed.status, 32) {
            return Err(Error::Invalid("An attachment has an invalid status."));
        }
        if embed
            .embed_ids
            .as_ref()
            .is_some_and(|ids| ids.len() > 50 || ids.iter().any(|id| !plain_id(id, 128)))
        {
            return Err(Error::Invalid("An attachment has invalid child embed IDs."));
        }
        match &embed.content {
            Some(content) => {
                if content.is_empty() || content.len() > MAX_SEND_EMBED_CONTENT_BYTES {
                    return Err(Error::Invalid(
                        "An attachment has empty or oversized content.",
                    ));
                }
                total += content.len();
            }
            None if volatile => {
                return Err(Error::Invalid(
                    "A volatile chat cannot reference a stored attachment.",
                ));
            }
            None => {}
        }
        if embed
            .text_preview
            .as_ref()
            .is_some_and(|p| p.len() > 64 * 1024)
        {
            return Err(Error::Invalid("An attachment preview is too long."));
        }
    }
    if total > MAX_SEND_EMBEDS_TOTAL_BYTES {
        return Err(Error::Invalid(
            "The attachments of one message exceed 16 MB.",
        ));
    }
    if mappings.len() > MAX_SEND_PII_MAPPINGS {
        return Err(Error::Invalid("Too many personal data mappings."));
    }
    for mapping in mappings {
        if !crate::privacy::is_placeholder(&mapping.placeholder)
            || mapping.original.is_empty()
            || mapping.original.len() > crate::privacy::MAX_PII_EXCLUSION_BYTES
            || mapping.kind.len() > 64
        {
            return Err(Error::Invalid("A personal data mapping is malformed."));
        }
    }
    Ok(())
}

/// The markdown reference block of `embed` (web `extractEmbedReferences`
/// grammar, Apple `ComposerPendingEmbed.markdownReference`).
pub(crate) fn reference_block(embed: &SendEmbed) -> String {
    let kind = embed.reference_type.as_deref().unwrap_or(&embed.kind);
    format!(
        "```json\n{{\"type\": \"{kind}\", \"embed_id\": \"{}\"}}\n```",
        embed.embed_id
    )
}

/// `text` trimmed, with a reference block appended for each embed it does not
/// reference yet, separated by a blank line (Apple
/// `contentByAppendingComposerEmbedReferences`). Without embeds `text` is
/// returned unchanged. References are appended before privacy preparation:
/// `privacy::prepare` never cuts into reference blocks.
pub(crate) fn content_with_references(text: &str, embeds: &[SendEmbed]) -> String {
    if embeds.is_empty() {
        return text.to_owned();
    }
    let mut result = text.trim().to_owned();
    for embed in embeds {
        let quoted = format!("\"embed_id\": \"{}\"", embed.embed_id);
        let compact = format!("\"embed_id\":\"{}\"", embed.embed_id);
        if result.contains(&quoted) || result.contains(&compact) {
            continue;
        }
        if !result.is_empty() {
            result.push_str("\n\n");
        }
        result.push_str(&reference_block(embed));
    }
    result
}

/// The cleartext `embeds` of the inference request (`EmbedForServer`): the
/// server encrypts them with the user's vault key for its inference cache.
/// Reference-only embeds are omitted. Timestamps are Unix seconds.
pub(crate) fn cleartext_embeds(embeds: &[SendEmbed], created: u64) -> Vec<Value> {
    embeds
        .iter()
        .filter_map(|embed| {
            let content = embed.content.as_ref()?;
            let mut value = json!({"embed_id": embed.embed_id, "type": embed.kind,
                "status": embed.status, "content": content.as_str(),
                "createdAt": created, "updatedAt": created});
            if let Some(preview) = &embed.text_preview {
                value["text_preview"] = json!(preview.as_str());
            }
            if let Some(ids) = &embed.embed_ids {
                value["embed_ids"] = json!(ids);
            }
            Some(value)
        })
        .collect()
}

/// Identity of the message an encrypted bundle belongs to.
pub(crate) struct BundleScope<'a> {
    /// Chat id.
    pub(crate) chat_id: &'a str,
    /// The user message id (`client_message_id`).
    pub(crate) message_id: &'a str,
    /// The owner account id.
    pub(crate) user_id: &'a str,
    /// Unix seconds of the turn.
    pub(crate) created: u64,
}

/// The `encrypted_embeds` bundle (`EncryptedEmbedForDirectus`) the server
/// stores atomically with the message. Per embed: key =
/// HKDF(chat key, embed id) so every device derives the same key; type,
/// content and preview are AES-GCM under that key without AAD
/// (`encryptWithEmbedKey`); `embed_keys` holds exactly the master wrapper
/// (`hashed_chat_id` null) then the chat wrapper, as
/// `_store_client_encrypted_embeds` requires. Reference-only embeds are
/// omitted (their head already exists).
///
/// # Errors
/// `Crypto` when a key cannot be derived or wrapped; the master capability's
/// errors (for example a signed-out or replaced master).
pub(crate) async fn encrypted_bundle(
    embeds: &[SendEmbed],
    scope: &BundleScope<'_>,
    chat_key: &[u8; 32],
    master: &MasterCapability,
) -> Result<Vec<Value>> {
    let (chat_hash, message_hash, user_hash) = (
        hash_id(scope.chat_id),
        hash_id(scope.message_id),
        hash_id(scope.user_id),
    );
    let mut nonces = OsNonces;
    let mut bundle = Vec::new();
    for embed in embeds {
        let Some(content) = &embed.content else {
            continue;
        };
        let key = derive_embed_key(chat_key, &embed.embed_id)?;
        let embed_hash = hash_id(&embed.embed_id);
        let wrapped_master = wrap_key_with_master(&key, master).await?;
        let wrapped_chat = wrap_key(&key, chat_key, &mut nonces)?;
        let mut entry = json!({
            "embed_id": embed.embed_id,
            "encrypted_type": encrypt_text(&embed.kind, &key, None, &mut nonces)?,
            "encrypted_content": encrypt_text(content, &key, None, &mut nonces)?,
            "status": embed.status,
            "hashed_chat_id": chat_hash,
            "hashed_message_id": message_hash,
            "hashed_user_id": user_hash,
            "created_at": scope.created,
            "updated_at": scope.created,
            "embed_keys": [
                {"hashed_embed_id": embed_hash, "key_type": "master", "hashed_chat_id": null,
                 "encrypted_embed_key": wrapped_master, "hashed_user_id": user_hash,
                 "created_at": scope.created},
                {"hashed_embed_id": embed_hash, "key_type": "chat", "hashed_chat_id": chat_hash,
                 "encrypted_embed_key": wrapped_chat, "hashed_user_id": user_hash,
                 "created_at": scope.created},
            ],
        });
        if let Some(preview) = &embed.text_preview {
            entry["encrypted_text_preview"] =
                json!(encrypt_text(preview, &key, None, &mut nonces)?);
        }
        if let Some(ids) = &embed.embed_ids {
            entry["embed_ids"] = json!(ids);
        }
        bundle.push(entry);
    }
    Ok(bundle)
}

/// The privacy preparation of a turn's `text` (already carrying attachment
/// references): with detection, the history `existing` mappings plus the
/// shell's own mappings, honouring the user's exclusions; without detection,
/// the text unchanged plus only the shell's mappings (which still have to be
/// stored so its placeholders restore).
///
/// # Errors
/// `Invalid` from `privacy::prepare_excluding` (conflicting mappings, limits).
pub(crate) fn prepare_turn_privacy(
    text: &str,
    memories: &[Value],
    existing: &[Value],
    options: &super::SendOptions,
) -> Result<crate::privacy::PreparedPrivacy> {
    let caller = super::plaintext::Plain::new(
        options
            .pii_mappings
            .iter()
            .map(SendPiiMapping::to_value)
            .collect::<Vec<Value>>(),
    );
    if !options.pii_detection {
        return Ok(crate::privacy::PreparedPrivacy {
            text: text.into(),
            mappings: caller.into_inner(),
        });
    }
    if caller.is_empty() {
        return crate::privacy::prepare_excluding(
            text,
            memories,
            existing,
            &options.pii_exclusions,
        );
    }
    let mut combined = super::plaintext::Plain::new(existing.to_vec());
    combined.extend(caller.into_inner());
    crate::privacy::prepare_excluding(text, memories, &combined, &options.pii_exclusions)
}

#[cfg(test)]
#[path = "send_attachments_tests.rs"]
mod tests;
