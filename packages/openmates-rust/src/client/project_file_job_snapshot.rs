//! Read-only `snapshot` Project file job: the plaintext hosted text files of
//! a Project with their revisions, for a server that runs browser tests in a
//! sandbox but holds no keys. Part of the shared client core job executor
//! (`project_file_jobs`); the client decrypts, the server only receives the
//! bounded result. No TS original; contract `project-file-jobs`.
use crate::work::{HostedFileError, HostedResult};
use serde_json::{json, Value};

/// Most files of one snapshot.
pub(super) const SNAPSHOT_MAX_FILES: usize = 200;
/// Most bytes of `code` over all files of one snapshot.
pub(super) const SNAPSHOT_MAX_BYTES: usize = 400_000;
/// Longest accepted `prefix` argument.
const SNAPSHOT_PREFIX_MAX_CHARS: usize = 512;

/// The optional path prefix of a `snapshot` job.
///
/// # Errors
/// `invalid_snapshot_arguments` unless `arguments` is `{}` or exactly
/// `{prefix}` with a relative string (at most 512 characters, no leading `/`,
/// no `..` segment).
pub(super) fn snapshot_prefix(arguments: &Value) -> HostedResult<Option<String>> {
    let invalid = || HostedFileError::Refused("invalid_snapshot_arguments");
    let object = arguments.as_object().ok_or_else(invalid)?;
    if object.keys().any(|key| key != "prefix") {
        return Err(invalid());
    }
    let Some(prefix) = object.get("prefix") else {
        return Ok(None);
    };
    let prefix = prefix.as_str().ok_or_else(invalid)?;
    if prefix.chars().count() > SNAPSHOT_PREFIX_MAX_CHARS
        || prefix.starts_with('/')
        || prefix.split('/').any(|segment| segment == "..")
    {
        return Err(invalid());
    }
    Ok(Some(prefix.to_owned()))
}

/// Where a snapshot reads from: the real Project or an in-memory fixture.
pub(super) trait SnapshotSource {
    /// Folder-qualified paths of the visible hosted files.
    async fn paths(&mut self) -> HostedResult<Vec<String>>;
    /// Decrypted text and revision of `path`; `None` for a binary or
    /// non-text file, which a snapshot skips.
    async fn read(&mut self, path: &str) -> HostedResult<Option<(String, Value)>>;
}

/// The result body of a snapshot: files under `prefix` sorted by path, at most
/// [`SNAPSHOT_MAX_FILES`] files and [`SNAPSHOT_MAX_BYTES`] bytes of code. Once
/// a limit would be exceeded no further file is added and `truncated` is set.
///
/// # Errors
/// Whatever the source's listing or reading refuses with.
pub(super) async fn build_snapshot<S: SnapshotSource>(
    source: &mut S,
    prefix: Option<&str>,
) -> HostedResult<Value> {
    let mut paths: Vec<String> = source
        .paths()
        .await?
        .into_iter()
        .filter(|path| prefix.is_none_or(|prefix| path.starts_with(prefix)))
        .collect();
    paths.sort();
    paths.dedup();
    let (mut files, mut bytes, mut truncated) = (Vec::new(), 0usize, false);
    for path in paths {
        let Some((code, revision)) = source.read(&path).await? else {
            continue;
        };
        if files.len() >= SNAPSHOT_MAX_FILES || bytes + code.len() > SNAPSHOT_MAX_BYTES {
            truncated = true;
            break;
        }
        bytes += code.len();
        files.push(json!({"path": path, "code": code, "revision": revision}));
    }
    Ok(json!({"files": files, "truncated": truncated, "source_id": null}))
}
