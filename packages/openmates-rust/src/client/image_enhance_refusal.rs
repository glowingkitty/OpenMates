//! Typed refusals of `POST /v1/images/enhance` and `GET /v1/images/enhance/{id}`
//! (shared core; spec `feature.embed-user-edits`). The ordinary transport maps
//! an HTTP refusal to a generic error; Enhance needs the server's own code
//! (credits, Team, Project scope, version conflict). Only codes of the closed
//! set below are kept, so no raw error body leaves the transport (same rule as
//! `embed_user_revision_refusal`).
use super::ImageEnhanceError;
use serde_json::Value;

/// Every refusal code of the routes the client understands. Mirrors the
/// `HTTPException` details of `backend/core/api/app/routes/images_enhance.py`.
const CODES: &[&str] = &[
    "insufficient_credits",
    "team_enhance_unavailable",
    "project_context_required",
    "embed_version_conflict",
    "operation_id_conflict",
    "enhance_job_busy",
    "embed_version_malformed",
    "embed_file_index_malformed",
    "embed_not_found",
    "chat_not_found",
    "project_not_found",
    "embed_not_in_project",
    "enhance_not_found",
    "invalid_source_key",
    "invalid_source_nonce",
    "not_an_image",
    "source_not_owned",
    "invalid_operation_id",
    "rate_limited",
    "rate_limit_unavailable",
    "pricing_unavailable",
    "encryption_unavailable",
    "enhance_unavailable",
    "project_lookup_failed",
];

/// The closed-set refusal of one Enhance response.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ImageEnhanceRefusal {
    status: u16,
    code: &'static str,
    current_version: Option<i64>,
}

fn is_route(path: &str) -> bool {
    let path = path.split('?').next().unwrap_or(path);
    match path.strip_prefix("/v1/images/enhance") {
        Some("") => true,
        Some(rest) => rest
            .strip_prefix('/')
            .is_some_and(|id| !id.is_empty() && !id.contains('/')),
        None => false,
    }
}

/// Classify one refused response of the Enhance routes; `None` for success,
/// another path, or a body without a known code (a 402 or 429 without one is
/// still named by its status: the rate limiter answers with its own body).
pub(crate) fn classify(path: &str, status: u16, body: &[u8]) -> Option<ImageEnhanceRefusal> {
    if (200..300).contains(&status) || !is_route(path) {
        return None;
    }
    let value: Value = serde_json::from_slice(body).unwrap_or(Value::Null);
    let detail = &value["detail"];
    let named = detail.as_str().or_else(|| detail["code"].as_str());
    let code = match named.and_then(|named| CODES.iter().find(|known| **known == named)) {
        Some(code) => *code,
        None if status == 402 => "insufficient_credits",
        None if status == 429 => "rate_limited",
        None => return None,
    };
    Some(ImageEnhanceRefusal {
        status,
        code,
        current_version: detail["current_version"]
            .as_i64()
            .filter(|v| code == "embed_version_conflict" && *v >= 1),
    })
}

impl ImageEnhanceRefusal {
    /// The typed error of this refusal.
    pub(crate) fn into_error(self) -> ImageEnhanceError {
        match (self.status, self.code) {
            (_, "insufficient_credits") => ImageEnhanceError::InsufficientCredits,
            (_, "team_enhance_unavailable") => ImageEnhanceError::TeamUnavailable,
            (_, "project_context_required") => ImageEnhanceError::ProjectContextRequired,
            (_, "embed_version_conflict") => ImageEnhanceError::VersionConflict {
                current_version: self.current_version,
            },
            (_, "operation_id_conflict") => ImageEnhanceError::OperationConflict,
            (_, "enhance_job_busy") => ImageEnhanceError::Busy,
            (_, "rate_limited") => ImageEnhanceError::RateLimited,
            (404, code) => ImageEnhanceError::NotFound { code },
            (422, code) => ImageEnhanceError::InvalidSource { code },
            (_, code) => ImageEnhanceError::Unavailable { code },
        }
    }
}
