//! API-key assistant-response feedback (npm `client.feedback`). The rating gate
//! is shared with the CLI and reports; the server owns persistence.
use crate::{Error, OpenMates, Result};
use serde_json::{Value, json};

pub const ASSISTANT_FEEDBACK_THANKS: &str = "Thanks for the feedback!";
pub const ASSISTANT_FEEDBACK_REPORT_TITLE: &str = "Assistant response quality bad:";

/// npm `AssistantFeedbackDecision`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AssistantFeedbackDecision {
    pub rating: u8,
    pub action: &'static str,
    pub message: &'static str,
    pub report_title: Option<&'static str>,
}

/// npm `buildAssistantFeedbackDecision`: integer 1-5; 1-3 propose an issue report.
pub fn build_assistant_feedback_decision(rating: i64) -> Result<AssistantFeedbackDecision> {
    if !(1..=5).contains(&rating) {
        return Err(Error::Invalid("Rating must be an integer from 1 to 5."));
    }
    let (action, report_title) = if rating <= 3 {
        ("report_issue", Some(ASSISTANT_FEEDBACK_REPORT_TITLE))
    } else {
        ("thanks", None)
    };
    Ok(AssistantFeedbackDecision {
        rating: rating as u8,
        action,
        message: ASSISTANT_FEEDBACK_THANKS,
        report_title,
    })
}

pub struct Feedback<'a> {
    client: &'a OpenMates,
}
impl<'a> Feedback<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    /// Like npm, the rating is forwarded unchanged; the server validates it.
    pub async fn assistant_response(&self, rating: i64) -> Result<Value> {
        self.client
            .post(
                "/v1/sdk/feedback/assistant-response",
                json!({"rating": rating}),
            )
            .await
    }
}
impl OpenMates {
    pub fn feedback(&self) -> Feedback<'_> {
        Feedback::new(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ApiKey, ClientOptions, SdkCredentials, SdkOptions};
    #[test]
    fn decision_matches_npm_vectors() {
        for rating in 1..=3 {
            let d = build_assistant_feedback_decision(rating).unwrap();
            assert_eq!(
                (d.action, d.report_title),
                ("report_issue", Some("Assistant response quality bad:"))
            );
        }
        for rating in 4..=5 {
            let d = build_assistant_feedback_decision(rating).unwrap();
            assert_eq!(
                (d.action, d.report_title, d.message),
                ("thanks", None, "Thanks for the feedback!")
            );
        }
        for rating in [0, 6, -1, i64::MAX] {
            assert!(matches!(
                build_assistant_feedback_decision(rating),
                Err(Error::Invalid(_))
            ));
        }
    }
    #[tokio::test]
    async fn anonymous_never_posts() {
        let anon = OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials: SdkCredentials::Anonymous {
                anonymous_id: "synthetic-feedback-anon".into(),
            },
            device_id: "synthetic-feedback-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap();
        assert_eq!(
            anon.feedback().assistant_response(5).await,
            Err(Error::Authentication)
        );
        let _ = ApiKey::new("sk-api-feedbackOwnerA.localSetupSuffix").unwrap();
    }
}
