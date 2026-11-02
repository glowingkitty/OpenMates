//! Email notification settings (WebSocket request/ack), the notification
//! list and newsletter preferences, mirroring the npm client routes.
use super::Account;
use super::settings_ops::segment;
use crate::{Error, Result};
use reqwest::Method;
use serde_json::{Value, json};

impl Account<'_> {
    /// `email_notification_settings_get` snapshot without its `request_id`.
    pub async fn email_notification_settings(&mut self) -> Result<Value> {
        let mut snapshot = self
            .client
            .settings_request_exchange(
                "email_notification_settings_get",
                json!({}),
                "email_notification_settings_snapshot",
            )
            .await?;
        if let Some(object) = snapshot.as_object_mut() {
            object.remove("request_id");
        }
        Ok(snapshot)
    }
    /// `email_notification_settings` update; returns the server's ack payload.
    pub async fn update_email_notification_settings(&mut self, update: Value) -> Result<Value> {
        if !update.is_object() {
            return Err(Error::Invalid(
                "Email notification settings must be an object.",
            ));
        }
        self.client
            .settings_request_exchange(
                "email_notification_settings",
                update,
                "email_notification_settings_ack",
            )
            .await
    }
    pub async fn notifications(&mut self, limit: i64) -> Result<Value> {
        self.client.require_session()?;
        self.client
            .request(
                Method::GET,
                &format!("/v1/notifications?limit={limit}"),
                None,
            )
            .await
    }
    pub async fn newsletter_categories(&mut self) -> Result<Value> {
        self.client.require_session()?;
        self.client
            .request(Method::GET, "/v1/newsletter/categories", None)
            .await
    }
    pub async fn update_newsletter_categories(&mut self, categories: Value) -> Result<Value> {
        self.client.require_session()?;
        self.client
            .request(
                Method::PATCH,
                "/v1/newsletter/categories",
                Some(json!({"categories":categories})),
            )
            .await
    }
    pub async fn subscribe_newsletter(
        &mut self,
        email: &str,
        language: &str,
        darkmode: bool,
    ) -> Result<Value> {
        self.client
            .request(
                Method::POST,
                "/v1/newsletter/subscribe",
                Some(json!({"email":email,"language":language,"darkmode":darkmode})),
            )
            .await
    }
    pub async fn confirm_newsletter(&mut self, token: &str) -> Result<Value> {
        let token = segment(token, "Invalid newsletter token.")?;
        self.client
            .request(
                Method::GET,
                &format!("/v1/newsletter/confirm/{token}"),
                None,
            )
            .await
    }
    pub async fn unsubscribe_newsletter(&mut self, token: &str) -> Result<Value> {
        let token = segment(token, "Invalid newsletter token.")?;
        self.client
            .request(
                Method::GET,
                &format!("/v1/newsletter/unsubscribe/{token}"),
                None,
            )
            .await
    }
}

#[cfg(test)]
#[path = "notifications_tests.rs"]
mod tests;
