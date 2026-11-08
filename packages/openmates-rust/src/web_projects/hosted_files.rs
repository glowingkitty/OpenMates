//! Hosted Project file job decisions for the shared Rust core Worker `chatState` unit:
//! metadata path normalization (`projectHostedPaths`) and the list / search shaping
//! (`projectHostedList`, `projectHostedSearchPlan`) after the page marked each file hidden.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `frontend/packages/ui/src/services/projectState/projectFilePolicy.ts`. File content,
//! the Git-ignore matcher, YAML and project-key hashing stay on the page; only paths, hidden
//! flags and job arguments arrive here. Refusals are data: `{fileError}` / `{searchError}`.

use super::js::{self, len16};
use super::search_request::{self, has_control};
use super::{Fault, Outcome};
use serde_json::{Map, Value, json};

const MAX_PATH_CHARS: usize = 4_096;
const MAX_LIST_ENTRIES: usize = 500;

/// `normalizeHostedProjectPath`: the validated path, or `invalid_path` / `protected_path`.
pub(crate) fn normalize_hosted_path(value: Option<&Value>) -> Result<String, &'static str> {
    let Some(text) = js::as_str(value) else {
        return Err("invalid_path");
    };
    let bytes = text.as_bytes();
    // `/^[a-z]:/i`: a drive-letter prefix is never Project-relative.
    let drive = bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':';
    if text.is_empty()
        || len16(text) > MAX_PATH_CHARS
        || text.contains('\\')
        || has_control(text)
        || text.starts_with('/')
        || drive
    {
        return Err("invalid_path");
    }
    let parts: Vec<&str> = text.split('/').collect();
    if parts
        .iter()
        .any(|part| part.is_empty() || *part == "." || *part == "..")
    {
        return Err("invalid_path");
    }
    if parts.contains(&".git") || search_request::is_protected_read_path(text) {
        return Err("protected_path");
    }
    Ok(text.to_owned())
}

fn file_error(code: &str) -> Value {
    json!({ "fileError": code })
}

/// The `{path, hidden}` rows of a list/search input.
fn marked_files(input: &Value) -> Result<Vec<(&str, bool)>, Fault> {
    js::req_array(input.get("files"), "files")?
        .iter()
        .map(|file| {
            let path = js::req_str(file.get("path"), "files.path")?;
            let hidden = file
                .get("hidden")
                .and_then(Value::as_bool)
                .ok_or_else(|| Fault::Malformed("bad_field:files.hidden".to_owned()))?;
            Ok((path, hidden))
        })
        .collect()
}

/// `projectHostedPaths`: one `{path}` or `{code}` per listed metadata path, in order.
pub(super) fn paths(input: &Value) -> Outcome {
    let results: Vec<Value> = js::req_array(input.get("paths"), "paths")?
        .iter()
        .map(|value| match normalize_hosted_path(Some(value)) {
            Ok(path) => json!({ "path": path }),
            Err(code) => json!({ "code": code }),
        })
        .collect();
    Ok(json!({ "results": results }))
}

/// `projectHostedList`: visible files under the requested directory, at most 500.
pub(super) fn list(input: &Value) -> Outcome {
    let requested = input.get("path");
    let prefix = if requested.is_none() || js::is_str(requested, ".") || js::is_str(requested, "") {
        String::new()
    } else {
        match normalize_hosted_path(requested) {
            Ok(path) => format!("{path}/"),
            Err(code) => return Ok(file_error(code)),
        }
    };
    let matched: Vec<&str> = marked_files(input)?
        .into_iter()
        .filter(|(path, hidden)| path.starts_with(prefix.as_str()) && !hidden)
        .map(|(path, _)| path)
        .collect();
    let entries: Vec<Value> = matched
        .iter()
        .take(MAX_LIST_ENTRIES)
        .map(|path| json!({ "path": path, "kind": "file" }))
        .collect();
    Ok(json!({ "entries": entries, "truncated": matched.len() > MAX_LIST_ENTRIES }))
}

/// `projectHostedSearchPlan`: the normalized request, candidate indices in listing order
/// (the page sorts them with `localeCompare` for content searches) and the hidden count.
pub(super) fn search_plan(input: &Value) -> Outcome {
    let search: Map<String, Value> = match search_request::normalize(input.get("args"))? {
        Ok(search) => search,
        Err(code) => return Ok(json!({ "searchError": code })),
    };
    if js::is_str(search.get("mode"), "regex") {
        return Ok(file_error("regex_search_unavailable"));
    }
    let search_path = search.get("path");
    let prefix = if js::is_str(search_path, ".") {
        String::new()
    } else {
        match normalize_hosted_path(search_path) {
            Ok(path) => path,
            Err(code) => return Ok(file_error(code)),
        }
    };
    let mut excluded = input
        .get("excluded")
        .and_then(Value::as_f64)
        .ok_or_else(|| Fault::Malformed("bad_field:excluded".to_owned()))?;
    let glob = search.get("glob").and_then(Value::as_str);
    let mut candidates = Vec::new();
    for (index, (path, hidden)) in marked_files(input)?.into_iter().enumerate() {
        if hidden {
            excluded += 1.0;
            continue;
        }
        let under = prefix.is_empty()
            || path == prefix
            || path
                .strip_prefix(prefix.as_str())
                .is_some_and(|rest| rest.starts_with('/'));
        if under && search_request::glob_matches(path, glob) {
            candidates.push(Value::from(index));
        }
    }
    Ok(
        json!({ "search": search, "candidates": candidates, "excluded": js::number_value(excluded) }),
    )
}
