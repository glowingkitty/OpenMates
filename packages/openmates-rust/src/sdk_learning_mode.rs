//! API-key Learning Mode status/enable/disable (npm `client.learningMode`).
//! The passcode is only forwarded in the request body and never stored or logged.
use crate::{OpenMates, Result};
use serde_json::{Value, json};

pub struct LearningMode<'a> {
    client: &'a OpenMates,
}
impl<'a> LearningMode<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    pub async fn status(&self) -> Result<Value> {
        self.client.get("/v1/sdk/learning-mode").await
    }
    pub async fn enable(&self, age_group: &str, passcode: &str) -> Result<Value> {
        self.client
            .post(
                "/v1/sdk/learning-mode/enable",
                enable_body(age_group, passcode),
            )
            .await
    }
    pub async fn disable(&self, passcode: &str) -> Result<Value> {
        self.client
            .post(
                "/v1/sdk/learning-mode/disable",
                json!({"passcode": passcode}),
            )
            .await
    }
}
fn enable_body(age_group: &str, passcode: &str) -> Value {
    json!({"age_group": age_group, "passcode": passcode})
}
impl OpenMates {
    pub fn learning_mode(&self) -> LearningMode<'_> {
        LearningMode::new(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ClientOptions, Error, SdkCredentials, SdkOptions};
    #[test]
    fn body_uses_snake_case_wire_names() {
        assert_eq!(
            enable_body("teen", "1234"),
            json!({"age_group":"teen","passcode":"1234"})
        );
    }
    #[tokio::test]
    async fn anonymous_is_refused_before_transport() {
        let anon = OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials: SdkCredentials::Anonymous {
                anonymous_id: "synthetic-learning-anon".into(),
            },
            device_id: "synthetic-learning-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap();
        assert_eq!(
            anon.learning_mode().status().await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anon.learning_mode().disable("0000").await,
            Err(Error::Authentication)
        );
    }
}
