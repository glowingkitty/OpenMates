//! API-key Learning Mode status/enable/disable/collaborative (npm `client.learningMode`).
//! The passcode is only forwarded in the request body and never stored or logged.
use crate::{OpenMates, Result};
use serde_json::{Value, json};

/// API-key Learning Mode facade over the `/v1/sdk/learning-mode` routes.
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
    /// Enable Learning Mode. `collaborative_build: None` omits the field so the
    /// backend default applies (on, except forced off for `under_10`).
    pub async fn enable(
        &self,
        age_group: &str,
        passcode: &str,
        collaborative_build: Option<bool>,
    ) -> Result<Value> {
        self.client
            .post(
                "/v1/sdk/learning-mode/enable",
                enable_body(age_group, passcode, collaborative_build),
            )
            .await
    }
    /// Turn collaborative build on or off. Enabling requires the passcode;
    /// disabling does not, so `passcode: None` omits the field.
    pub async fn collaborative(&self, enabled: bool, passcode: Option<&str>) -> Result<Value> {
        self.client
            .post(
                "/v1/sdk/learning-mode/collaborative",
                collaborative_body(enabled, passcode),
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
fn enable_body(age_group: &str, passcode: &str, collaborative_build: Option<bool>) -> Value {
    let mut body = json!({"age_group": age_group, "passcode": passcode});
    if let Some(value) = collaborative_build {
        body["collaborative_build"] = json!(value);
    }
    body
}
fn collaborative_body(enabled: bool, passcode: Option<&str>) -> Value {
    let mut body = json!({"enabled": enabled});
    if let Some(value) = passcode {
        body["passcode"] = json!(value);
    }
    body
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
            enable_body("teen", "1234", None),
            json!({"age_group":"teen","passcode":"1234"})
        );
        assert_eq!(
            enable_body("teen", "1234", Some(false)),
            json!({"age_group":"teen","passcode":"1234","collaborative_build":false})
        );
        assert_eq!(
            collaborative_body(true, Some("1234")),
            json!({"enabled":true,"passcode":"1234"})
        );
        assert_eq!(collaborative_body(false, None), json!({"enabled":false}));
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
        assert_eq!(
            anon.learning_mode().collaborative(false, None).await,
            Err(Error::Authentication)
        );
    }
}
