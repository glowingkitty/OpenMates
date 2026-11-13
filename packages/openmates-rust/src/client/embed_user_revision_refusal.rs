//! Typed refusals of `POST /v1/embeds/{embed_id}/user-revisions` (shared core;
//! spec `feature.embed-user-edits`). The ordinary transport maps an HTTP refusal
//! to a generic error; this commit needs the server's own code (version
//! conflict with the current head, `base_snapshot_required`, Project context).
//! Only codes from the closed set of the route's `STABLE_ERROR_CODES` and its
//! own 400s are kept, so no raw error body leaves the transport (same rule as
//! `project_item_error`).
use super::UserRevisionError;
use serde_json::Value;

/// Every refusal code of the route the client understands. Mirrors
/// `STABLE_ERROR_CODES` plus the route-level 400s in
/// `backend/core/api/app/routes/embed_user_revisions.py`.
const CODES: &[&str] = &[
    "embed_version_conflict",
    "base_snapshot_required",
    "project_context_required",
    "invalid_request",
    "invalid_scope",
    "invalid_action",
    "invalid_operation_id",
    "invalid_embed_id",
    "invalid_chat_id",
    "invalid_project_id",
    "invalid_team_id",
    "invalid_expected_revision",
    "invalid_content_hash",
    "invalid_ciphertext",
    "invalid_status",
    "invalid_timestamp",
    "invalid_history_rows",
    "invalid_restored_from",
    "invalid_file_source",
    "invalid_file_reference",
    "file_source_required",
    "unsupported_file_source",
    "invalid_s3_file_keys",
    "invalid_actor",
    "media_index_required",
    "invalid_media_index",
    "media_index_mismatch",
    "chat_access_denied",
    "project_access_denied",
    "project_item_access_denied",
    "embed_access_denied",
    "embed_type_not_editable",
    "foreign_file_key",
    "enhance_result_not_found",
    "embed_not_found",
    "operation_payload_mismatch",
    "immutable_history_mismatch",
    "restore_source_missing",
    "enhance_result_not_ready",
    "enhance_result_expired",
    "enhance_version_mismatch",
    "enhance_scope_mismatch",
    "invalid_current_revision",
];

/// The closed-set refusal of one user-revision response: the server's code and,
/// for a version conflict, the head the server holds.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct UserRevisionRefusal {
    status: u16,
    code: &'static str,
    current_revision: Option<i64>,
    current_content_hash: Option<String>,
}

fn is_route(path: &str) -> bool {
    let path = path.split('?').next().unwrap_or(path);
    path.strip_prefix("/v1/embeds/")
        .and_then(|rest| rest.strip_suffix("/user-revisions"))
        .is_some_and(|id| !id.is_empty() && !id.contains('/'))
}

fn hex64(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// Classify one refused response of the route; `None` for success, another
/// path, or a body without a known code.
pub(crate) fn classify(path: &str, status: u16, body: &[u8]) -> Option<UserRevisionRefusal> {
    if (200..300).contains(&status) || !is_route(path) {
        return None;
    }
    let value: Value = serde_json::from_slice(body).ok()?;
    let detail = &value["detail"];
    let named = detail.as_str().or_else(|| detail["code"].as_str())?;
    let code = CODES.iter().find(|known| **known == named).copied()?;
    let conflict = code == "embed_version_conflict";
    Some(UserRevisionRefusal {
        status,
        code,
        current_revision: detail["current_revision"]
            .as_i64()
            .filter(|v| conflict && *v >= 1),
        current_content_hash: detail["current_content_hash"]
            .as_str()
            .filter(|hash| conflict && hex64(hash))
            .map(str::to_owned),
    })
}

impl UserRevisionRefusal {
    /// The typed error of this refusal.
    pub(crate) fn into_error(self) -> UserRevisionError {
        match (self.status, self.code) {
            (_, "embed_version_conflict") => UserRevisionError::VersionConflict {
                current_revision: self.current_revision,
                current_content_hash: self.current_content_hash,
            },
            (_, "base_snapshot_required") => UserRevisionError::BaseSnapshotRequired,
            (_, "project_context_required") => UserRevisionError::ProjectContextRequired,
            (403, code) => UserRevisionError::AccessDenied { code },
            (400 | 422, code) => UserRevisionError::Validation { code },
            (_, code) => UserRevisionError::Refused { code },
        }
    }
}
