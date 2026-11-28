//! The stored content of an edited code embed for the Apple shell (spec
//! `feature.embed-user-edits`, assertion `edit.next-version`). The core
//! (`openmates_sdk::work::code_edit_content`) keeps every field of the embed's
//! content object, replaces `code`, `line_count`, `content_hash` and
//! `version_number` and encodes it as TOON, like web `CodeEmbedFullscreen`.
//! The shell hands over the current content object (JSON or TOON) and commits
//! the result with `commitEmbedEdit`; it never writes the stored form itself.
use crate::view_embeds::EmbedEditError;

/// The TOON string to save when `code` replaces the code of the embed whose
/// content object is `current_content` (JSON or TOON), as version
/// `version_number`.
///
/// # Errors
/// `Validation { invalid_head }` when `current_content` is not an object,
/// `version_number` is below 1, or the encoder refuses a field.
#[uniffi::export]
pub fn code_embed_edit_content(
    current_content: String,
    code: String,
    version_number: i64,
) -> Result<String, EmbedEditError> {
    let invalid = || EmbedEditError::Validation {
        code: "invalid_head".to_owned(),
    };
    let version = u64::try_from(version_number)
        .ok()
        .filter(|version| *version >= 1)
        .ok_or_else(invalid)?;
    openmates_sdk::work::code_edit_content(&current_content, &code, version)
        .map(|content| content.as_str().to_owned())
        .map_err(|_| invalid())
}
