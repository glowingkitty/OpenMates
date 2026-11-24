//! Code adapter: the file text is `Y.Text` `content`. Edits are applied as the minimal
//! UTF-16 range replacement (Yjs offsets count UTF-16 code units), so a concurrent edit
//! elsewhere in the file survives.

use super::LiveError;
use yrs::{Doc, GetString, Text, Transact};

const ROOT: &str = "content";

/// Writes `text` into an empty replica (hydration).
pub(crate) fn from_text(doc: &Doc, text: &str) {
    let content = doc.get_or_insert_text(ROOT);
    let mut txn = doc.transact_mut();
    content.insert(&mut txn, 0, text);
}

/// The file text.
pub(crate) fn to_text(doc: &Doc) -> String {
    let content = doc.get_or_insert_text(ROOT);
    content.get_string(&doc.transact())
}

/// Replaces the whole file text with `new`, touching only the differing middle range.
pub(crate) fn set_text(doc: &Doc, new: &str) {
    let old: Vec<u16> = to_text(doc).encode_utf16().collect();
    let new: Vec<u16> = new.encode_utf16().collect();
    let (start, remove, insert) = minimal_range(&old, &new);
    if remove == 0 && insert.is_empty() {
        return;
    }
    let content = doc.get_or_insert_text(ROOT);
    let mut txn = doc.transact_mut();
    if remove > 0 {
        content.remove_range(&mut txn, start, remove);
    }
    if !insert.is_empty() {
        content.insert(&mut txn, start, &insert);
    }
}

/// Replaces lines `start..end` (0-based, end exclusive) with `replacement` (lines joined by
/// `\n`, no trailing newline needed) and applies it as a minimal range edit.
///
/// # Errors
/// [`LiveError::InvalidText`] when the line range is outside the file.
pub(crate) fn replace_lines(
    doc: &Doc,
    start: usize,
    end: usize,
    replacement: &str,
) -> Result<(), LiveError> {
    let text = to_text(doc);
    let mut lines: Vec<&str> = text.split('\n').collect();
    if start > end || end > lines.len() {
        return Err(LiveError::InvalidText("line range outside the file"));
    }
    let new_lines: Vec<&str> = if replacement.is_empty() {
        Vec::new()
    } else {
        replacement.split('\n').collect()
    };
    lines.splice(start..end, new_lines);
    set_text(doc, &lines.join("\n"));
    Ok(())
}

/// `(utf16 start, utf16 units to remove, text to insert)` turning `old` into `new`.
fn minimal_range(old: &[u16], new: &[u16]) -> (u32, u32, String) {
    let mut prefix = old.iter().zip(new).take_while(|(a, b)| a == b).count();
    // Never split a surrogate pair.
    if prefix > 0 && (0xD800..0xDC00).contains(&old[prefix - 1]) {
        prefix -= 1;
    }
    let max_suffix = old.len().min(new.len()) - prefix;
    let mut suffix = old
        .iter()
        .rev()
        .zip(new.iter().rev())
        .take(max_suffix)
        .take_while(|(a, b)| a == b)
        .count();
    if suffix > 0 && (0xDC00..0xE000).contains(&old[old.len() - suffix]) {
        suffix -= 1;
    }
    let remove = (old.len() - prefix - suffix) as u32;
    let insert = String::from_utf16_lossy(&new[prefix..new.len() - suffix]);
    (prefix as u32, remove, insert)
}
