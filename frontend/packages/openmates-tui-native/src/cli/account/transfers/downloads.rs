//! Authenticated binary downloads: invoice/credit-note PDFs (npm
//! `saveDownloadedDocument`) and the Team profile image (`teams
//! profile-image get`, written owner-only like npm's mode 0o600).
use super::{
    CliError, CliOutput, Invocation, basename, failed, first_of, handlers, ordered_json, output,
    path_segment, required, terminal_text,
};
use crate::client::Client;
use serde_json::Value;

const DOCUMENT_ACCEPT: &str = "application/pdf,application/octet-stream";
const IMAGE_ACCEPT: &str = "image/jpeg,image/png,application/octet-stream";

/// Node `fs` write failure text for the common cases.
fn write_error(path: &str, error: &std::io::Error) -> CliError {
    failed(match error.kind() {
        std::io::ErrorKind::NotFound => format!("ENOENT: no such file or directory, open '{path}'"),
        std::io::ErrorKind::PermissionDenied => format!("EACCES: permission denied, open '{path}'"),
        std::io::ErrorKind::IsADirectory => {
            format!("EISDIR: illegal operation on a directory, open '{path}'")
        }
        _ => format!("Could not write file '{path}'."),
    })
}

/// JavaScript `decodeURIComponent`; `None` is its `URIError`.
pub(super) fn decode_uri_component(text: &str) -> Option<String> {
    let bytes = text.as_bytes();
    let mut decoded = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            let pair = bytes.get(index + 1..index + 3)?;
            if !pair.iter().all(u8::is_ascii_hexdigit) {
                return None;
            }
            decoded.push(u8::from_str_radix(std::str::from_utf8(pair).ok()?, 16).ok()?);
            index += 3;
        } else {
            decoded.push(bytes[index]);
            index += 1;
        }
    }
    String::from_utf8(decoded).ok()
}

/// npm `filenameFromContentDisposition`.
pub(super) fn content_disposition_filename(
    header: Option<&str>,
) -> Result<Option<String>, CliError> {
    let Some(header) = header.filter(|header| !header.is_empty()) else {
        return Ok(None);
    };
    let pattern = |source: &str| {
        regex::Regex::new(source).map_err(|_| CliError::Client(crate::error::Error::Protocol))
    };
    if let Some(encoded) = pattern(r"(?i)filename\*=UTF-8''([^;]+)")?.captures(header) {
        return decode_uri_component(&encoded[1])
            .map(Some)
            .ok_or_else(|| failed("URI malformed"));
    }
    if let Some(quoted) = pattern(r#"(?i)filename="([^"]+)""#)?.captures(header) {
        return Ok(Some(quoted[1].to_owned()));
    }
    Ok(pattern(r"(?i)filename=([^;]+)")?
        .captures(header)
        .map(|plain| plain[1].trim().to_owned()))
}

/// Node `path.normalize` (POSIX).
fn normalize(path: &str) -> String {
    if path.is_empty() {
        return ".".into();
    }
    let absolute = path.starts_with('/');
    let trailing = path.ends_with('/');
    let mut parts: Vec<&str> = Vec::new();
    for segment in path.split('/') {
        match segment {
            "" | "." => {}
            ".." => {
                if parts.last().is_some_and(|last| *last != "..") {
                    parts.pop();
                } else if !absolute {
                    parts.push("..");
                }
            }
            segment => parts.push(segment),
        }
    }
    let mut normalized = parts.join("/");
    if normalized.is_empty() {
        return match (absolute, trailing) {
            (true, _) => "/".into(),
            (false, true) => "./".into(),
            (false, false) => ".".into(),
        };
    }
    if trailing {
        normalized.push('/');
    }
    if absolute {
        normalized.insert(0, '/');
    }
    normalized
}
/// Node `path.join(directory, name)` (POSIX).
pub(super) fn join(directory: &str, name: &str) -> String {
    let joined = [directory, name]
        .iter()
        .filter(|part| !part.is_empty())
        .copied()
        .collect::<Vec<_>>()
        .join("/");
    normalize(&joined)
}
/// npm `saveDownloadedDocument` target selection.
pub(super) fn document_path(output: Option<&str>, filename: &str) -> String {
    let target = output.unwrap_or(".");
    let name = basename(if filename.is_empty() {
        "document.pdf"
    } else {
        filename
    });
    if target.ends_with(".pdf") {
        target.to_owned()
    } else {
        join(target, name)
    }
}

pub(super) async fn invoice(
    i: &Invocation,
    client: &mut Client,
    credit_note: bool,
) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["output"])?;
    let id = i
        .positionals
        .first()
        .filter(|id| !id.is_empty())
        .ok_or_else(|| failed("Missing invoice ID."))?;
    let suffix = if credit_note {
        "credit-note/download"
    } else {
        "download"
    };
    let path = format!(
        "/v1/payments/invoices/{}/{suffix}",
        path_segment(id, "invoice ID")?
    );
    let response = client.get_binary(&path, DOCUMENT_ACCEPT).await?;
    if !response.ok() {
        return Err(failed(format!(
            "Download failed (HTTP {})",
            response.status
        )));
    }
    let filename = match content_disposition_filename(response.content_disposition.as_deref())? {
        Some(filename) => filename,
        None if credit_note => format!("CreditNote_{id}.pdf"),
        None => format!("Invoice_{id}.pdf"),
    };
    let file_path = document_path(i.text("output"), &filename);
    if let Some(parent) = std::path::Path::new(&file_path)
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        std::fs::create_dir_all(parent).map_err(|error| write_error(&file_path, &error))?;
    }
    std::fs::write(&file_path, response.data.as_slice())
        .map_err(|error| write_error(&file_path, &error))?;
    if i.boolean("json") {
        let stdout = ordered_json(&[
            ("path", Value::String(file_path)),
            ("filename", Value::String(filename)),
        ])?;
        return Ok(output(stdout, String::new()));
    }
    let subject = if credit_note {
        "Credit note"
    } else {
        "Invoice"
    };
    Ok(output(
        format!(
            "\x1b[32m✓\x1b[0m {subject} saved to {}\n",
            terminal_text(&file_path)
        ),
        String::new(),
    ))
}

/// `writeFileSync(path, data, { mode: 0o600 })`: new files are owner-only;
/// an existing file is truncated and keeps its mode, like Node.
fn write_private(path: &str, data: &[u8]) -> std::io::Result<()> {
    use std::io::Write;
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
    options.open(path)?.write_all(data)
}

pub(super) async fn team_profile_image(
    i: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["output", "file", "team", "team-id"])?;
    let team = required(
        first_of(i, &["team", "team-id"], Some(0)),
        "--team <team-id>",
    )?;
    let destination = required(first_of(i, &["output", "file"], Some(1)), "--output <path>")?;
    let path = format!(
        "/v1/teams/{}/profile-image",
        path_segment(&team, "Team identifier")?
    );
    let image = client.get_binary(&path, IMAGE_ACCEPT).await?;
    if !image.ok() {
        return Err(failed(format!(
            "Team profile image download failed with HTTP {}",
            image.status
        )));
    }
    write_private(&destination, &image.data).map_err(|error| write_error(&destination, &error))?;
    if i.boolean("json") {
        let content_type = image
            .content_type
            .clone()
            .unwrap_or_else(|| "application/octet-stream".into());
        let stdout = ordered_json(&[
            ("output", Value::String(destination)),
            ("content_type", Value::String(content_type)),
            ("size_bytes", Value::from(image.data.len())),
        ])?;
        return Ok(output(stdout, String::new()));
    }
    Ok(output(
        format!(
            "Team profile image written: {}\n",
            terminal_text(&destination)
        ),
        String::new(),
    ))
}
