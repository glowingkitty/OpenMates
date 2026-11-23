//! `apply_changes`: the hosted Project job that syncs the files a cloud
//! terminal command changed (lockfile, generated code, formatter output) back
//! into the Project. One job carries up to [`MAX_CHANGES`] entries
//! (`create` / `update` / `delete`, full new text, `expected_base` = hash of
//! the snapshot content the command started from); each is applied through the
//! same encrypted write path as `create_file` / `update_file` / `delete_file`,
//! so revisions, history patches, receipts, key wrappers and CAS are identical.
//!
//! Wire contract: `arguments = {origin: "command", execution_id, changes:
//! [{path, kind, expected_base, content}]}`; the result is `{origin,
//! execution_id, results: [{path, kind, status: "applied"|"refused", reason?,
//! revision?, applied_diff?, created?, idempotent?}], applied, refused}`.
//!
//! Write policy: an `apply_and_show` Project applies the batch. An `always_ask`
//! Project has no single proposal the user could approve for a whole batch, so
//! the job is refused up front with `approval_required` (see `api.rs`); the
//! per-entry write approval model is not used. Entries apply in order and a
//! refused entry never stops later ones. Entry `i` runs under the operation id
//! `<job operation id>:<i>` (hashed when too long), so a retried job reuses the
//! same receipts; an entry whose file already holds the requested text is
//! reported as applied with `idempotent: true` and writes nothing.
use super::io::HostedIo;
use super::job::{HostedContext, assert_direct_path, direct};
use super::policy;
use super::*;

/// Most entries one job may carry.
pub(super) const MAX_CHANGES: usize = 20;

/// Operation id of entry `index`: deterministic, `[A-Za-z0-9._:-]{1,128}`.
pub(super) fn entry_operation_id(operation_id: &str, index: usize) -> String {
    if operation_id.len() + 4 <= 128 {
        format!("{operation_id}:{index}")
    } else {
        format!("ac-{}:{index}", &content_hash(operation_id)[..40])
    }
}

fn refused_entry(path: &str, kind: &str, reason: &str) -> Value {
    json!({"path": path, "kind": kind, "status": "refused", "reason": reason})
}

/// Apply every entry of an `apply_changes` job.
///
/// # Errors
/// `invalid_file_mutation` for a malformed job, `too_many_changes` above
/// [`MAX_CHANGES`], and core transport errors (the job is then retried under
/// the same entry operation ids). Per-entry refusals are results, not errors.
pub(super) async fn execute<I: HostedIo>(
    io: &mut I,
    ctx: &HostedContext<'_>,
    job: &HostedFileJob,
) -> HostedResult<Value> {
    let args = &job.arguments;
    let (Some("command"), Some(execution_id), Some(changes)) = (
        args["origin"].as_str(),
        args["execution_id"].as_str(),
        args["changes"].as_array(),
    ) else {
        return refused("invalid_file_mutation");
    };
    if changes.len() > MAX_CHANGES {
        return refused("too_many_changes");
    }
    let mut results = Vec::with_capacity(changes.len());
    for (index, change) in changes.iter().enumerate() {
        results.push(apply_one(io, ctx, job, index, change).await?);
    }
    let applied = results.iter().filter(|r| r["status"] == "applied").count();
    Ok(json!({"origin": "command", "execution_id": execution_id,
        "proposal_commitment": batch_commitment(ctx, job, execution_id, changes)?,
        "applied": applied, "refused": results.len() - applied, "results": results}))
}

/// The keyed commitment of the whole batch (the `proposal_commitment` of the
/// completed result): the shared proposal tuple with operation `apply_changes`,
/// the execution id as path and the ordered entries (path, kind,
/// `expected_base`, SHA-256 of the content) as content.
fn batch_commitment(
    ctx: &HostedContext<'_>,
    job: &HostedFileJob,
    execution_id: &str,
    changes: &[Value],
) -> HostedResult<String> {
    let entries: Vec<Value> = changes
        .iter()
        .map(|c| {
            json!({"path": c["path"], "kind": c["kind"], "expected_base": c["expected_base"],
                "content_hash": c["content"].as_str().map(content_hash)})
        })
        .collect();
    let wire = json!({"operation": "apply_changes", "operation_id": job.operation_id,
        "path": execution_id, "expected_base": null,
        "content": serde_json::to_string(&entries).map_err(Error::from)?, "patch": null});
    Ok(super::super::workflow_files::commitment(
        ctx.project_key,
        ctx.project_id,
        &job.chat_id,
        &wire,
    )?)
}

async fn apply_one<I: HostedIo>(
    io: &mut I,
    ctx: &HostedContext<'_>,
    job: &HostedFileJob,
    index: usize,
    change: &Value,
) -> HostedResult<Value> {
    let raw_path = change["path"].as_str().unwrap_or_default();
    let kind = change["kind"].as_str().unwrap_or_default();
    let operation = match kind {
        "create" => HostedFileOperation::CreateFile,
        "update" => HostedFileOperation::UpdateFile,
        "delete" => HostedFileOperation::DeleteFile,
        _ => return Ok(refused_entry(raw_path, kind, "invalid_file_mutation")),
    };
    match entry(io, ctx, job, index, change, operation).await {
        Ok(result) => Ok(result),
        Err(error @ (HostedFileError::Refused(_) | HostedFileError::Rejected(_)))
        | Err(error @ HostedFileError::Core(Error::Conflict)) => {
            Ok(refused_entry(raw_path, kind, error.code()))
        }
        Err(error) => Err(error),
    }
}

async fn entry<I: HostedIo>(
    io: &mut I,
    ctx: &HostedContext<'_>,
    job: &HostedFileJob,
    index: usize,
    change: &Value,
    operation: HostedFileOperation,
) -> HostedResult<Value> {
    let kind = change["kind"].as_str().unwrap_or_default();
    // Earlier entries changed the Project, so the links and policy are reread.
    let listed = io.list_files().await?;
    let loaded = policy::load(io, ctx.private_paths, listed).await?;
    let path = normalize_path(&change["path"])?;
    let operation_id = entry_operation_id(&job.operation_id, index);
    let entry_job = HostedFileJob {
        operation_id: operation_id.clone(),
        chat_id: job.chat_id.clone(),
        operation,
        arguments: json!({"path": path}),
    };
    assert_direct_path(&loaded.policy, ctx, &entry_job, &path)?;
    let content = match change["content"].as_str() {
        Some(text) if text.len() > MAX_TEXT_BYTES => return refused("file_too_large"),
        other => other,
    };
    let mut mutation = HostedFileMutation {
        operation,
        operation_id,
        path: path.clone(),
        expected_base: None,
        content: None,
        patch: None,
        new_path: None,
    };
    let found: Vec<&HostedFile> = loaded.files.iter().filter(|f| f.path == path).collect();
    match operation {
        HostedFileOperation::CreateFile => {
            let text = content.ok_or(HostedFileError::Refused("invalid_file_mutation"))?;
            if let Some(file) = found.first().filter(|_| found.len() == 1) {
                let head = io.read_head(&file.embed_id).await?;
                if head.text().is_ok_and(|current| current == text) {
                    return Ok(applied_noop(&path, kind, &head));
                }
            }
            mutation.content = Some(text.to_owned());
        }
        HostedFileOperation::UpdateFile => {
            let text = content.ok_or(HostedFileError::Refused("invalid_file_mutation"))?;
            let base = change["expected_base"]
                .as_str()
                .ok_or(HostedFileError::Refused("invalid_file_mutation"))?;
            let [file] = found.as_slice() else {
                return refused(if found.is_empty() {
                    "file_not_found"
                } else {
                    "ambiguous_file_path"
                });
            };
            let head = io.read_head(&file.embed_id).await?;
            let current = head.text()?;
            if current == text {
                return Ok(applied_noop(&path, kind, &head));
            }
            if content_hash(current) != base {
                return refused("stale_base");
            }
            mutation.expected_base = Some(base.to_owned());
            mutation.patch = Some(replacement_patch(&path, current, text));
        }
        _ => {}
    }
    let result = direct(
        io,
        ctx,
        &entry_job,
        Some(&mutation),
        &loaded.files,
        &loaded.policy,
    )
    .await?;
    let mut out = json!({"path": path, "kind": kind, "status": "applied"});
    for field in ["revision", "applied_diff", "created"] {
        if let Some(value) = result.get(field).filter(|v| !v.is_null()) {
            out[field] = value.clone();
        }
    }
    Ok(out)
}

/// An entry whose file already holds the requested text (a retried job).
fn applied_noop(path: &str, kind: &str, head: &HostedHead) -> Value {
    json!({"path": path, "kind": kind, "status": "applied",
        "revision": head.revision, "idempotent": true})
}

/// The applied entries of a completed `apply_changes` result as display
/// mutations for the shell's local diff cards, each with whether it created the
/// file. A create carries the new text, an update the applied diff and a delete
/// only its path. Refused and idempotent entries (nothing written) are skipped.
/// The cards stay on the device; nothing here is sent to the server.
pub(crate) fn applied_change_mutations(
    job: &HostedFileJob,
    result: &Value,
) -> Vec<(HostedFileMutation, bool)> {
    let (Some(changes), Some(rows)) = (
        job.arguments["changes"].as_array(),
        result["results"].as_array(),
    ) else {
        return Vec::new();
    };
    // `execute` answers one row per change, in job order.
    changes
        .iter()
        .zip(rows)
        .enumerate()
        .filter(|(_, (_, row))| row["status"] == "applied" && row["idempotent"] != true)
        .filter_map(|(index, (change, row))| {
            let (operation, content, patch) = match row["kind"].as_str()? {
                "create" => (
                    HostedFileOperation::CreateFile,
                    change["content"].as_str().map(str::to_owned),
                    None,
                ),
                "update" => (
                    HostedFileOperation::UpdateFile,
                    None,
                    row["applied_diff"].as_str().map(str::to_owned),
                ),
                "delete" => (HostedFileOperation::DeleteFile, None, None),
                _ => return None,
            };
            let mutation = HostedFileMutation {
                operation,
                operation_id: entry_operation_id(&job.operation_id, index),
                path: row["path"].as_str()?.to_owned(),
                expected_base: change["expected_base"].as_str().map(str::to_owned),
                content,
                patch,
                new_path: None,
            };
            Some((
                mutation,
                row["created"] == true || operation == HostedFileOperation::CreateFile,
            ))
        })
        .collect()
}
