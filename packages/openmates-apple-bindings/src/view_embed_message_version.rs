//! Message-scoped embed versions for the Apple shell
//! (`images-generate.revision.message-shows-its-version`): which version of an
//! image embed each chat message shows, from the `pinned_embeds` of the
//! chat's `app_skill_use` parents plus the user-made versions. The core
//! (`client::embed_write::pinned::versions_by_message_with_provenance`)
//! owns the rule; this module only marshals. Mirrors web
//! `embedVersionForMessage` (`messageEmbedVersion.ts`).

use crate::CoreError;
use openmates_sdk::client::embed_write::pinned::{
    MessageParents, parse_version_provenance, versions_by_message_with_provenance,
};

/// The decrypted `app_skill_use` parent contents of one message, in chat order.
#[derive(Debug, Clone, uniffi::Record)]
pub struct MessageParentsRecord {
    /// Message id.
    pub message_id: String,
    /// Decrypted parent contents (TOON or JSON); empty for a message without skill use.
    pub parent_contents: Vec<String>,
}

/// The version of the embed one message shows.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct MessageEmbedVersionRecord {
    /// Message id.
    pub message_id: String,
    /// Version the message shows.
    pub version: i64,
    /// True when this message's own parent pins the embed.
    pub pinned_here: bool,
}

/// Resolve the version of `embed_id` each of `messages` (chat order, up to and
/// including the asking message) shows. `versions_page_json` is the
/// `GET /v1/embeds/{id}/versions` page (`{"versions": [...]}`) when the head
/// version is above 1, else `None`. The caller reads its own message's entry.
///
/// # Errors
/// `CoreError` for a malformed parent pin or versions page.
#[uniffi::export]
pub fn embed_versions_by_message(
    messages: Vec<MessageParentsRecord>,
    embed_id: String,
    versions_page_json: Option<String>,
) -> Result<Vec<MessageEmbedVersionRecord>, CoreError> {
    let provenance = match versions_page_json {
        None => Vec::new(),
        Some(json) => {
            let page: serde_json::Value =
                serde_json::from_str(&json).map_err(|_| CoreError::Invalid {
                    message: "versions page is not valid JSON".to_owned(),
                })?;
            parse_version_provenance(&page)?
        }
    };
    let parents: Vec<MessageParents> = messages
        .into_iter()
        .map(|m| MessageParents {
            message_id: m.message_id,
            parent_contents: m.parent_contents,
        })
        .collect();
    Ok(
        versions_by_message_with_provenance(&parents, &embed_id, &provenance)?
            .into_iter()
            .map(|v| MessageEmbedVersionRecord {
                message_id: v.message_id,
                version: v.version,
                pinned_here: v.pinned_here,
            })
            .collect(),
    )
}

#[cfg(test)]
#[path = "view_embed_message_version_tests.rs"]
mod tests;
