//! Exact legacy settings/reminders read. No skill execution or local decryption.
use super::Account;
mod ordered;
use crate::Error;
pub use ordered::SettingsReadResponse;
use serde_json::Value;
use std::{fmt, future::Future, time::Duration};

const RETRY_DELAY: Duration = Duration::from_millis(61_000);

/// Fixed settings-route failure. HTTP status text matches settingsGet; transport,
/// original cancellation and owner/header failures retain their typed Core error.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SettingsReadError {
    cause: Error,
    http_status: Option<u16>,
}
impl SettingsReadError {
    pub fn core_error(&self) -> Error {
        self.cause
    }
    pub fn http_status(&self) -> Option<u16> {
        self.http_status
    }
}
impl From<Error> for SettingsReadError {
    fn from(cause: Error) -> Self {
        Self {
            cause,
            http_status: None,
        }
    }
}
impl fmt::Display for SettingsReadError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.http_status {
            Some(status) => write!(f, "Settings GET failed with HTTP {status}"),
            None if matches!(
                self.cause,
                Error::Unavailable {
                    code: "settings_json_unsupported",
                    ..
                }
            ) =>
            {
                f.write_str(
                    "The settings response exceeds the supported JSON limits or representation.",
                )
            }
            None => fmt::Display::fmt(&self.cause, f),
        }
    }
}
impl std::error::Error for SettingsReadError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.cause)
    }
}
impl Account<'_> {
    /// Same GET /v1/settings/reminders and complete response as settingsGet("reminders").
    /// No query/defaults, filtering, chat-context inheritance, decrypt or fallback skill.
    /// A 429 retries once after the original 61 seconds; waiting is cancellable.
    pub async fn reminders(&mut self) -> std::result::Result<Value, SettingsReadError> {
        self.reminders_ordered()
            .await
            .map(SettingsReadResponse::into_value)
    }
    /// Same read with reusable root ordering and wiping response ownership.
    pub async fn reminders_ordered(
        &mut self,
    ) -> std::result::Result<SettingsReadResponse, SettingsReadError> {
        self.reminders_ordered_with_wait(crate::platform::time::sleep)
            .await
    }
    #[cfg(all(test, not(target_arch = "wasm32")))]
    async fn reminders_with_wait<W, F>(
        &mut self,
        wait: W,
    ) -> std::result::Result<Value, SettingsReadError>
    where
        W: FnMut(Duration) -> F,
        F: Future<Output = ()>,
    {
        self.reminders_ordered_with_wait(wait)
            .await
            .map(SettingsReadResponse::into_value)
    }
    async fn reminders_ordered_with_wait<W, F>(
        &mut self,
        mut wait: W,
    ) -> std::result::Result<SettingsReadResponse, SettingsReadError>
    where
        W: FnMut(Duration) -> F,
        F: Future<Output = ()>,
    {
        let original = self.client.begin_settings_reminders_read()?;
        let mut http_status = None;
        let mut result = self
            .client
            .request_settings_reminders(&mut http_status)
            .await;
        // Only the actual completed HTTP 429 path mints this status. Cookie,
        // owner, body-limit, transport and cancellation failures never do so.
        if result.is_err() && http_status == Some(429) {
            original.check(self.client)?;
            tokio::select! { biased;
                _ = original.cancelled() => return Err(Error::Cancelled.into()),
                _ = wait(RETRY_DELAY) => {},
            }
            original.check(self.client)?;
            http_status = None;
            result = self
                .client
                .request_settings_reminders(&mut http_status)
                .await;
        }
        original.check_after_response(self.client, &result)?;
        result.map_err(|cause| SettingsReadError { cause, http_status })
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "settings_read_tests.rs"]
mod tests;
