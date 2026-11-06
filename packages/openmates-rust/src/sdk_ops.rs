//! Shared helpers for the explicit API-key operation facades (billing, settings,
//! reminders, notifications, connected accounts, finance). Credentials, retries
//! and cancellation stay in `OpenMates::task_request`; nothing here reads CLI state.
use crate::{Error, Result};

/// Raw file response (invoice PDFs, usage exports); body is never interpreted.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RawDownload {
    pub content_type: String,
    pub filename: Option<String>,
    pub data: Vec<u8>,
}
/// Percent-encode one URL path segment (`encodeURIComponent` / Python `quote(safe="")`).
pub(crate) fn segment(id: &str) -> Result<String> {
    if id.is_empty() || matches!(id, "." | "..") || id.chars().any(char::is_control) {
        return Err(Error::Invalid("Supply a nonempty identifier."));
    }
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut out = String::with_capacity(id.len());
    for byte in id.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.!~*'()".contains(&byte) {
            out.push(char::from(byte));
        } else {
            out.push('%');
            out.push(char::from(HEX[(byte >> 4) as usize]));
            out.push(char::from(HEX[(byte & 15) as usize]));
        }
    }
    Ok(out)
}
/// Append the supplied pairs as a form-encoded query; empty input leaves `path` as is.
pub(crate) fn with_query(path: &str, query: &[(&str, &str)]) -> String {
    if query.is_empty() {
        return path.to_owned();
    }
    let mut serializer = url::form_urlencoded::Serializer::new(String::new());
    for (key, value) in query {
        serializer.append_pair(key, value);
    }
    format!("{path}?{}", serializer.finish())
}
/// Destructive or money-moving operations need an explicit caller confirmation.
pub(crate) fn require_confirmed(confirmed: bool) -> Result<()> {
    if confirmed {
        Ok(())
    } else {
        Err(Error::Invalid(
            "This operation requires explicit confirmation (confirmed = true).",
        ))
    }
}
/// Same `filename=` extraction as the Python SDK, reduced to a bare file name.
pub(crate) fn filename(content_disposition: Option<&str>) -> Option<String> {
    let value = content_disposition?
        .split(';')
        .map(str::trim)
        .find_map(|part| part.strip_prefix("filename="))?
        .trim_matches('"');
    let name = value.rsplit(['/', '\\']).next().unwrap_or_default();
    (!name.is_empty() && name != "." && name != "..").then(|| name.to_owned())
}
