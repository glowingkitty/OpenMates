//! Rename and delete of a hosted Project file link (shared core, P11).
//!
//! A rename moves the `project_items` link to a new path: the item id is
//! re-derived for that path, the display name and metadata are re-encrypted
//! with the Project key, and the embed with its revision history is kept. A
//! delete removes the link only, so a commit restore can relink the file.
//! Contract: `docs/plans/cloud-project-development/contracts/project-embed-adoption.md`.
use super::io::HostedIo;
use super::job::{HostedContext, assert_direct_path, seal};
use super::policy::PathPolicy;
use super::*;

/// The link a rename/delete addresses: its normalized path and the listed file.
pub(super) struct Move<'a> {
    pub(super) path: &'a str,
    pub(super) found: Option<&'a HostedFile>,
}

/// The link metadata after a rename. `path` (and a legacy `file_path` /
/// `filename`) become `new_path`; a file of an adopted application keeps its
/// `application_path` relative to the application folder while it stays in
/// that folder, and loses the application fields when it leaves it.
pub(super) fn renamed_metadata(old_path: &str, new_path: &str, metadata: &Value) -> Value {
    let mut next = match metadata {
        Value::Object(map) => map.clone(),
        _ => serde_json::Map::new(),
    };
    next.insert("path".into(), json!(new_path));
    for legacy in ["file_path", "filename"] {
        if next.contains_key(legacy) {
            next.insert(legacy.into(), json!(new_path));
        }
    }
    if !next.contains_key("source") {
        next.insert("source".into(), json!(HOSTED_SOURCE));
    }
    let folder = next
        .get("application_path")
        .and_then(Value::as_str)
        .and_then(|relative| old_path.strip_suffix(relative))
        .and_then(|prefix| prefix.strip_suffix('/'))
        .map(str::to_owned);
    if let Some(folder) = folder {
        match new_path.strip_prefix(&format!("{folder}/")) {
            Some(relative) if !relative.is_empty() => {
                next.insert("application_path".into(), json!(relative));
            }
            _ => {
                next.remove("application_path");
                next.remove("application_embed_id");
            }
        }
    }
    Value::Object(next)
}

/// Run one rename or delete job against the listed links.
///
/// # Errors
/// `file_not_found`, `path_conflict` (the target path is linked), the path
/// policy refusals for both paths, the server's link code (`path_conflict`,
/// `forbidden`, …) as [`HostedFileError::Rejected`] and core errors.
pub(super) async fn execute<I: HostedIo>(
    io: &mut I,
    ctx: &HostedContext<'_>,
    job: &HostedFileJob,
    mutation: &HostedFileMutation,
    target: Move<'_>,
    files: &[HostedFile],
    policy: &PathPolicy,
) -> HostedResult<Value> {
    mutation.validate()?;
    let Some(file) = target.found else {
        return refused("file_not_found");
    };
    // The listing always names the link row; a missing id is a protocol fault,
    // never a guessed path-derived id that could address another link.
    let item_id = file
        .item_id
        .clone()
        .ok_or(HostedFileError::Core(Error::Protocol))?;
    let path = target.path;
    match job.operation {
        HostedFileOperation::RenameFile => {
            let requested = mutation
                .new_path
                .as_deref()
                .ok_or(HostedFileError::Refused("invalid_file_mutation"))?;
            let new_path = normalize_path(&json!(requested))?;
            assert_direct_path(policy, ctx, job, &new_path)?;
            if new_path == path {
                return refused("invalid_file_mutation");
            }
            if files.iter().any(|f| f.path == new_path) {
                return refused("path_conflict");
            }
            let new_item =
                hosted_file_identity(ctx.project_key, &new_path, HostedIdentityKind::Item)?;
            let metadata =
                serde_json::to_string(&renamed_metadata(path, &new_path, &file.metadata))
                    .map_err(Error::from)?;
            let body = json!({
                "operation_id": job.operation_id,
                "new_project_item_id": new_item,
                "encrypted_display_name": seal(&new_path, ctx.project_key)?,
                "encrypted_metadata": seal(&metadata, ctx.project_key)?,
            });
            io.rename_link(&item_id, body).await?;
            // Contract "Job payloads": rename results name the new and the
            // previous item id so the server can record the move.
            Ok(
                json!({"path": new_path, "previous_path": path, "operation_id": job.operation_id,
                "embed_id": file.embed_id, "project_item_id": new_item,
                "previous_project_item_id": item_id, "renamed": true}),
            )
        }
        HostedFileOperation::DeleteFile => {
            io.delete_link(&item_id, json!({"operation_id": job.operation_id}))
                .await?;
            Ok(json!({"path": path, "operation_id": job.operation_id,
                "embed_id": file.embed_id, "project_item_id": item_id, "deleted": true}))
        }
        _ => refused("invalid_file_mutation"),
    }
}
