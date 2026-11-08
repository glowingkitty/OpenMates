//! Project search request contract shared by hosted and remote file executors: request
//! normalization, the `*` / `**` / `?` path-glob grammar and the credential-path guard.
//! Part of the shared core `web_projects` module (web Projects lane).
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `frontend/packages/ui/src/utils/projectSearchProtocol.ts`
//! (`normalizeProjectSearchRequest`, `matchesProjectSearchGlob`, `isProtectedProjectReadPath`);
//! proven by `hosted_files_ts_vectors.json`. Lengths and glob steps count UTF-16 units like JS.

use super::Fault;
use super::js::{self, len16};
use serde_json::{Map, Value};

const DEFAULT_MAX_RESULTS: f64 = 20.0;
const MAX_RESULTS: f64 = 100.0;
const MAX_QUERY_CHARS: usize = 2_000;
const MAX_GLOB_CHARS: usize = 512;
const MAX_PATH_CHARS: usize = 2_048;

/// A request the TS rule refuses with `ProjectSearchProtocolError(code)`.
pub(crate) type SearchRefusal = &'static str;

/// Code points `<= 0x1f` or `0x7f` (`hasControlCharacters`).
pub(crate) fn has_control(value: &str) -> bool {
    value
        .chars()
        .any(|c| (c as u32) <= 0x1f || c as u32 == 0x7f)
}

/// `normalizeProjectSearchRequest(args)`: the normalized request object, or the refusal
/// code in the TS check order (target, content option, mode, query, path, glob, limit).
///
/// # Errors
/// `Fault::Malformed` when `args` is `null`/absent (the TS rule hits a TypeError).
pub(crate) fn normalize(
    args: Option<&Value>,
) -> Result<Result<Map<String, Value>, SearchRefusal>, Fault> {
    let content = Value::from("content");
    let literal = Value::from("literal");
    let dot = Value::from(".");
    let no = Value::Bool(false);
    let default_max = Value::from(DEFAULT_MAX_RESULTS);
    let target = js::nullish_or(js::prop(args, "target")?, &content);
    let mode = js::nullish_or(js::prop(args, "mode")?, &literal);
    let query = js::prop(args, "query")?;
    let path = js::nullish_or(js::prop(args, "path")?, &dot);
    let glob = js::prop(args, "glob")?;
    let max_results = js::nullish_or(js::prop(args, "max_results")?, &default_max);
    let include_content = js::nullish_or(js::prop(args, "include_content")?, &no);

    let Some(target) = target.as_str().filter(|t| *t == "files" || *t == "content") else {
        return Ok(Err("invalid_search_target"));
    };
    let Some(include_content) = include_content.as_bool() else {
        return Ok(Err("invalid_search_content_option"));
    };
    if include_content && target != "files" {
        return Ok(Err("invalid_search_content_option"));
    }
    let Some(mode) = mode.as_str().filter(|m| *m == "literal" || *m == "regex") else {
        return Ok(Err("invalid_search_mode"));
    };
    let Some(query) = js::as_str(query)
        .filter(|q| !js::trim(q).is_empty() && len16(q) <= MAX_QUERY_CHARS && !has_control(q))
    else {
        return Ok(Err("invalid_search_query"));
    };
    let Some(path) = path.as_str() else {
        return Ok(Err("invalid_search_path"));
    };
    let Some(path) = normalize_path(path) else {
        return Ok(Err("invalid_search_path"));
    };
    if let Some(glob) = glob
        && !js::as_str(Some(glob)).is_some_and(glob_allowed)
    {
        return Ok(Err("invalid_search_glob"));
    }
    if !js::is_integer(Some(max_results)) {
        return Ok(Err("invalid_search_limit"));
    }
    let limit = max_results.as_f64().unwrap_or(f64::NAN);
    if !(1.0..=MAX_RESULTS).contains(&limit) {
        return Ok(Err("invalid_search_limit"));
    }

    let mut request = Map::new();
    request.insert("target".to_owned(), Value::from(target));
    request.insert("mode".to_owned(), Value::from(mode));
    request.insert("query".to_owned(), Value::from(query));
    request.insert("path".to_owned(), Value::from(path));
    if let Some(Value::String(glob)) = glob {
        request.insert("glob".to_owned(), Value::from(glob.as_str()));
    }
    request.insert("maxResults".to_owned(), js::number_value(limit));
    request.insert("includeContent".to_owned(), Value::Bool(include_content));
    Ok(Ok(request))
}

fn glob_allowed(glob: &str) -> bool {
    !(glob.is_empty()
        || len16(glob) > MAX_GLOB_CHARS
        || glob.starts_with('!')
        || has_control(glob)
        || glob.contains(['\\', '[', ']', '{', '}'])
        || glob.starts_with('/')
        || glob.split('/').any(|part| part == ".."))
}

/// `normalizeSearchPath`: `None` where the TS rule refuses with `invalid_search_path`.
fn normalize_path(value: &str) -> Option<String> {
    if value.is_empty()
        || len16(value) > MAX_PATH_CHARS
        || has_control(value)
        || value.contains('\\')
        || value.starts_with('/')
    {
        return None;
    }
    let parts: Vec<&str> = value.split('/').collect();
    if parts.contains(&"..") {
        return None;
    }
    let normalized = parts
        .into_iter()
        .filter(|part| !part.is_empty() && *part != ".")
        .collect::<Vec<_>>()
        .join("/");
    Some(if normalized.is_empty() {
        ".".to_owned()
    } else {
        normalized
    })
}

/// `matchesProjectSearchGlob(path, glob)`: `*` and `?` stop at `/`, `**` crosses it and
/// `**/` also matches zero directories. An absent or empty glob matches everything.
/// Memoized recursion like the TS rule; depth is bounded by `path + glob` UTF-16 units
/// (at most 4096 + 512 for validated inputs).
pub(crate) fn glob_matches(path: &str, glob: Option<&str>) -> bool {
    let Some(glob) = glob.filter(|g| !g.is_empty()) else {
        return true;
    };
    let path: Vec<u16> = path.encode_utf16().collect();
    let glob: Vec<u16> = glob.encode_utf16().collect();
    let mut walk = GlobWalk {
        memo: vec![0; (path.len() + 1) * (glob.len() + 1)],
        width: glob.len() + 1,
        path,
        glob,
    };
    walk.visit(0, 0)
}

const STAR: u16 = b'*' as u16;
const SLASH: u16 = b'/' as u16;
const QUESTION: u16 = b'?' as u16;

struct GlobWalk {
    path: Vec<u16>,
    glob: Vec<u16>,
    /// 0 = not visited, 1 = no match, 2 = match (the TS `memo` map).
    memo: Vec<u8>,
    width: usize,
}

impl GlobWalk {
    fn starts_at(&self, index: usize, pattern: &[u16]) -> bool {
        self.glob.get(index..index + pattern.len()) == Some(pattern)
    }

    fn visit(&mut self, p: usize, g: usize) -> bool {
        let slot = p * self.width + g;
        if self.memo[slot] != 0 {
            return self.memo[slot] == 2;
        }
        let more = p < self.path.len();
        let matched = if g == self.glob.len() {
            p == self.path.len()
        } else if self.starts_at(g, &[STAR, STAR, SLASH]) {
            let mut matched = self.visit(p, g + 3);
            let mut index = p;
            while !matched && index < self.path.len() {
                if self.path[index] == SLASH {
                    matched = self.visit(index + 1, g + 3);
                }
                index += 1;
            }
            matched
        } else if self.starts_at(g, &[STAR, STAR]) {
            self.visit(p, g + 2) || (more && self.visit(p + 1, g))
        } else if self.glob[g] == STAR {
            self.visit(p, g + 1) || (more && self.path[p] != SLASH && self.visit(p + 1, g))
        } else if self.glob[g] == QUESTION {
            more && self.path[p] != SLASH && self.visit(p + 1, g + 1)
        } else {
            more && self.path[p] == self.glob[g] && self.visit(p + 1, g + 1)
        };
        self.memo[slot] = if matched { 2 } else { 1 };
        matched
    }
}

const PROTECTED_NAMES: &[&str] = &[
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".pgpass",
    ".my.cnf",
    ".git-credentials",
    "credentials",
    "credentials.json",
    "application_default_credentials.json",
    "id_rsa",
    "id_ed25519",
    "id_dsa",
    "id_ecdsa",
];
const PROTECTED_EXTENSIONS: &[&str] = &[
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".keystore",
    ".kdbx",
    ".credentials",
];

/// `isProtectedProjectReadPath`: credential files and directories (case-insensitive,
/// `\` read as `/`) that no Project executor lists, searches or reads.
pub(crate) fn is_protected_read_path(value: &str) -> bool {
    let slashed = value.replace('\\', "/");
    let normalized = slashed
        .strip_prefix("./")
        .unwrap_or(&slashed)
        .to_lowercase();
    let parts: Vec<&str> = normalized
        .split('/')
        .filter(|part| !part.is_empty())
        .collect();
    let name = parts.last().copied().unwrap_or("");
    if name == ".env" || name.starts_with(".env.") {
        return true;
    }
    if parts
        .iter()
        .any(|part| matches!(*part, ".ssh" | ".aws" | ".gnupg"))
    {
        return true;
    }
    if normalized == ".config/gcloud"
        || normalized.ends_with("/.config/gcloud")
        || normalized.contains(".config/gcloud/")
    {
        return true;
    }
    PROTECTED_NAMES.contains(&name)
        || PROTECTED_EXTENSIONS
            .iter()
            .any(|extension| name.ends_with(extension))
}
