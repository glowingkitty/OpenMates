//! Account Learning Mode (TS CLI `getLearningModeStatus`,
//! `activateLearningMode`, `deactivateLearningMode`).
//!
//! The server owns the passcode check and lockout; the client only forwards
//! the passcode in the request body and never stores or logs it.
use crate::client::*;

/// The age groups the server accepts, in the TS CLI order.
pub const LEARNING_MODE_AGE_GROUPS: &[&str] = &["under_10", "10_12", "13_15", "16_18", "adult"];

/// A failed Learning Mode request with the HTTP status when the server
/// answered, so callers can keep the installed CLI wording.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LearningModeError {
    pub source: Error,
    pub http_status: Option<u16>,
}

impl From<Error> for LearningModeError {
    fn from(source: Error) -> Self {
        Self {
            source,
            http_status: None,
        }
    }
}

/// Validate a Learning Mode age group exactly as the TS CLI does.
pub fn learning_mode_age_group(value: Option<&str>) -> std::result::Result<&str, &'static str> {
    value
        .filter(|group| LEARNING_MODE_AGE_GROUPS.contains(group))
        .ok_or("Provide --age-group as one of: under_10, 10_12, 13_15, 16_18, adult.")
}

impl Client {
    async fn learning_mode_request(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
    ) -> std::result::Result<Value, LearningModeError> {
        self.require_session()?;
        let mut http_status = None;
        let result = self
            .request_task_headers_observed(method, path, body, None, None, None, &mut http_status)
            .await;
        let value = result.map_err(|source| LearningModeError {
            source,
            http_status,
        })?;
        if value.is_object() {
            Ok(value)
        } else {
            Err(Error::Protocol.into())
        }
    }

    /// GET `/v1/learning-mode`; the status object is returned as the server sent it.
    pub async fn learning_mode_status(&mut self) -> std::result::Result<Value, LearningModeError> {
        self.learning_mode_request(Method::GET, "/v1/learning-mode", None)
            .await
    }

    /// POST `/v1/learning-mode/activate` with the age group and passcode.
    pub async fn activate_learning_mode(
        &mut self,
        age_group: &str,
        passcode: &str,
    ) -> std::result::Result<Value, LearningModeError> {
        let body = json!({"age_group": age_group, "passcode": passcode});
        self.learning_mode_request(Method::POST, "/v1/learning-mode/activate", Some(body))
            .await
    }

    /// POST `/v1/learning-mode/deactivate` with the passcode.
    pub async fn deactivate_learning_mode(
        &mut self,
        passcode: &str,
    ) -> std::result::Result<Value, LearningModeError> {
        let body = json!({"passcode": passcode});
        self.learning_mode_request(Method::POST, "/v1/learning-mode/deactivate", Some(body))
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn age_groups_match_the_installed_cli() {
        for group in ["under_10", "10_12", "13_15", "16_18", "adult"] {
            assert_eq!(learning_mode_age_group(Some(group)), Ok(group));
        }
        let message = "Provide --age-group as one of: under_10, 10_12, 13_15, 16_18, adult.";
        assert_eq!(learning_mode_age_group(Some("child")), Err(message));
        assert_eq!(learning_mode_age_group(None), Err(message));
    }
}
