//! Session-authenticated Code Run: one skill POST plus status polling.
//!
//! The logged-in CLI/TUI path has no [`crate::sdk::OpenMates`] API key, so it
//! cannot use the SDK's code resolver. This module gives the account session
//! the same contract: the `code/run` skill is posted once, then every result's
//! `status_path` under `/v1/code/run/` is polled (every second, at most 20
//! minutes) until it is `finished`, `failed`, `timeout` or `cancelled`, and
//! the terminal status is stored in the result as `final`. The E2B consent
//! refusal (403 `e2b_consent_required` / `e2b_consent_declined`) is mapped by
//! the transport and surfaces from the POST as a typed [`Error::Unavailable`].
use super::*;
use std::time::Duration;

const RUN_ROUTE: &str = "/v1/apps/code/skills/run";
const STATUS_PREFIX: &str = "/v1/code/run/";
const MAX_RESULTS: usize = 100;
const POLL_INTERVAL: Duration = Duration::from_secs(1);
const POLL_TIMEOUT: Duration = Duration::from_secs(1200);
const TERMINAL: [&str; 4] = ["finished", "failed", "timeout", "cancelled"];

impl Client {
    /// Run Code Run with the account session and wait for every result.
    ///
    /// `body` is the already built `{"requests": [...]}` skill input. The
    /// returned envelope is the POST response with each result extended by
    /// `final` (its terminal status). The original `admission` and the
    /// operation cancellation are rechecked before the billable POST and
    /// between polls; the POST is never repeated. A run still pending after
    /// 20 minutes fails with [`Error::Offline`], like the SDK resolver.
    pub async fn run_code_with_status(
        &mut self,
        body: Value,
        admission: &DirectAppSkillAdmission,
    ) -> Result<Value> {
        self.run_code_polled(body, admission, POLL_INTERVAL, POLL_TIMEOUT)
            .await
    }

    async fn run_code_polled(
        &mut self,
        body: Value,
        admission: &DirectAppSkillAdmission,
        interval: Duration,
        timeout: Duration,
    ) -> Result<Value> {
        admission.check(self)?;
        self.require_credentials()?;
        if self.team()?.is_some() {
            return Err(Error::Invalid("Switch to Personal to run App skills."));
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.verify_private_operation()?;
        let mut response = self.request(Method::POST, RUN_ROUTE, Some(body)).await?;
        admission.check(self)?;
        let wrapped = response.get("success").is_some();
        let paths = {
            let data = if wrapped { &response["data"] } else { &response };
            status_paths(data)?
        };
        let deadline = crate::platform::time::Instant::now() + timeout;
        for (index, path) in paths {
            let status = self.poll_code_status(&path, admission, interval, deadline).await?;
            let data = if wrapped { &mut response["data"] } else { &mut response };
            data["results"][index]["final"] = status;
        }
        admission.check(self)?;
        Ok(response)
    }

    async fn poll_code_status(
        &mut self,
        path: &str,
        admission: &DirectAppSkillAdmission,
        interval: Duration,
        deadline: crate::platform::time::Instant,
    ) -> Result<Value> {
        let cancel = self.operation_cancel.clone();
        loop {
            admission.check(self)?;
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            if crate::platform::time::Instant::now() >= deadline {
                return Err(Error::Offline);
            }
            match self.request(Method::GET, path, None).await {
                Ok(value) => {
                    let status = value["status"].as_str().ok_or(Error::Protocol)?;
                    if TERMINAL.contains(&status) {
                        return Ok(value);
                    }
                }
                Err(Error::Offline) => {}
                Err(error) => return Err(error),
            }
            tokio::select! {
                _ = cancel.cancelled() => return Err(Error::Cancelled),
                _ = crate::platform::time::sleep(interval) => {}
            }
        }
    }
}

/// Indexed, validated `status_path`s of a code run response; results without
/// one are kept as they are.
fn status_paths(data: &Value) -> Result<Vec<(usize, String)>> {
    let Some(results) = data["results"].as_array() else {
        return Ok(Vec::new());
    };
    if results.len() > MAX_RESULTS {
        return Err(Error::Protocol);
    }
    let mut paths = Vec::new();
    for (index, result) in results.iter().enumerate() {
        if let Some(path) = result["status_path"].as_str() {
            if !path.starts_with(STATUS_PREFIX) || path.contains("..") {
                return Err(Error::Protocol);
            }
            paths.push((index, path.to_owned()));
        }
    }
    Ok(paths)
}

#[cfg(test)]
#[path = "code_run_status_tests.rs"]
mod tests;
