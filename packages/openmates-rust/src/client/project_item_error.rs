//! Stable refusal codes of the Project item-link routes (shared core).
//!
//! The ordinary transport maps an HTTP refusal to a generic [`Error`]; the
//! P11 link routes (`items/adopt-embed`, `items/{id}/rename`, `DELETE
//! items/{id}`) need the server's own code to tell a path conflict from an
//! already linked embed. Only a code from the closed set below is kept, so no
//! raw error body ever leaves the transport. Contract:
//! `docs/plans/cloud-project-development/contracts/project-embed-adoption.md`.
use super::*;

/// Every link refusal code the client understands: the contract "Errors" list
/// plus the backend's extra codes (`project_item_not_found` for an unknown
/// link, `operation_payload_mismatch` for a reused operation id with another
/// body, `embed_key_ambiguous` for duplicate Project wrappers). Mirrors
/// `STABLE_ERROR_CODES` in `backend/core/api/app/routes/project_item_links.py`.
pub(crate) const PROJECT_ITEM_ERROR_CODES: &[&str] = &[
    "project_not_found",
    "forbidden",
    "embed_not_found",
    "embed_already_linked",
    "path_conflict",
    "invalid_request",
    "project_item_not_found",
    "operation_payload_mismatch",
    "embed_key_ambiguous",
    "project_context_required",
];

/// The closed-set `&'static` form of `code`, if the client knows it.
pub(crate) fn known_code(code: &str) -> Option<&'static str> {
    PROJECT_ITEM_ERROR_CODES
        .iter()
        .find(|known| **known == code)
        .copied()
}

/// The closed-set code of one refused Project route response, if its JSON body
/// names one as `detail`, `detail.code`, `code` or `error_code`. The link
/// routes put it in `detail` as a plain string (`HTTPException(detail=code)`).
pub(super) fn classify(path: &str, status: u16, body: &[u8]) -> Option<&'static str> {
    if (200..300).contains(&status) || !path.starts_with("/v1/projects/") {
        return None;
    }
    let value: Value = serde_json::from_slice(body).ok()?;
    [
        &value["detail"],
        &value["detail"]["code"],
        &value["code"],
        &value["error_code"],
    ]
    .into_iter()
    .filter_map(Value::as_str)
    .find_map(|code| known_code(&code.to_ascii_lowercase()))
}

impl Client {
    /// Forget the code of an earlier refused Project route request.
    pub(crate) fn clear_project_item_error(&mut self) {
        self.project_item_error = None;
    }

    /// The stable code of the last refused Project route response, consumed.
    pub(crate) fn take_project_item_error(&mut self) -> Option<&'static str> {
        self.project_item_error.take()
    }
}

#[cfg(test)]
#[path = "project_item_error_tests.rs"]
mod tests;
