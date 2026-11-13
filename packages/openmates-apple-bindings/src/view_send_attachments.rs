//! Records of a turn's composer attachments, un-redacted PII values and
//! shell-made PII mappings for `sendWithOptions`, mapped onto
//! `openmates_sdk::client::{SendEmbed, SendPiiMapping}` and
//! `openmates_sdk::privacy::PiiExclusions`. Swift passes presentation data and
//! opaque embed ids only; the core derives, wraps and encrypts every embed key.
//! Bindings only marshal; validation lives in the core. Plan
//! `apple-client-core-migration`; spec `client-core`.
use crate::view_record_details::PiiMappingRecord;
use openmates_sdk::client::{SendEmbed, SendPiiMapping};
use openmates_sdk::privacy::PiiExclusions;
use zeroize::Zeroizing;

/// One embed the composer attaches to the turn (an upload, a recording, a
/// pasted code or text block, a URL preview, or an embed already stored).
#[derive(Clone, PartialEq, Eq, uniffi::Record)]
pub struct SendEmbedRecord {
    /// The embed id (for an upload: the upload's `embedId`).
    pub embed_id: String,
    /// The embed type (`image`, `pdf`, `code-code`, `audio-recording`, …).
    pub embed_type: String,
    /// The type in the message's reference block; nil uses `embedType`.
    #[uniffi(default = None)]
    pub reference_type: Option<String>,
    /// `finished` or `processing` (an upload still being processed).
    #[uniffi(default = "finished")]
    pub status: String,
    /// The plaintext content of a new embed, as prepared by the composer.
    /// Nil attaches an embed that is already stored (reference only).
    #[uniffi(default = None)]
    pub content: Option<String>,
    /// Optional preview text.
    #[uniffi(default = None)]
    pub text_preview: Option<String>,
    /// Child embed ids of a composite embed.
    #[uniffi(default = None)]
    pub child_embed_ids: Option<Vec<String>>,
}

impl std::fmt::Debug for SendEmbedRecord {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // Content may carry upload file keys; it is never printed.
        f.debug_struct("SendEmbedRecord")
            .field("embed_id", &self.embed_id)
            .field("embed_type", &self.embed_type)
            .field("has_content", &self.content.is_some())
            .finish()
    }
}

impl From<SendEmbedRecord> for SendEmbed {
    fn from(record: SendEmbedRecord) -> Self {
        Self {
            embed_id: record.embed_id,
            kind: record.embed_type,
            reference_type: record.reference_type,
            status: record.status,
            content: record.content.map(Zeroizing::new),
            text_preview: record.text_preview.map(Zeroizing::new),
            embed_ids: record.child_embed_ids,
        }
    }
}

/// A placeholder Swift already wrote into the text or an attachment
/// (`PiiMappingRecord`, the same record message metadata returns), stored
/// encrypted with the message; an empty `kind` becomes `OTHER`.
pub(crate) fn pii_mapping(record: PiiMappingRecord) -> SendPiiMapping {
    SendPiiMapping {
        placeholder: record.placeholder,
        original: Zeroizing::new(record.original),
        kind: record.kind,
    }
}

/// The exclusions of a turn from `SendOptionsRecord`.
pub(crate) fn exclusions(originals: Vec<String>, placeholders: Vec<String>) -> PiiExclusions {
    PiiExclusions {
        originals: originals.into_iter().map(Zeroizing::new).collect(),
        placeholders,
    }
}
