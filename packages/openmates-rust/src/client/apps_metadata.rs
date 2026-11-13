//! Raw Apps metadata reads for the CLI's `--json` output.
//!
//! The npm CLI prints the backend's App and skill metadata responses unchanged for
//! `apps list|info|skill-info --json`. These reads return the same validated JSON so
//! the native CLI keeps that contract; `Client::app_detail` stays the typed `Item`
//! view used by human output and the TUI.
use super::*;

impl Client {
    /// `GET /v1/apps?include_unavailable=true`: every App with all production-stage
    /// skills, regardless of provider key availability (npm `listApps`).
    pub async fn apps_metadata_json(&mut self) -> Result<Value> {
        self.require_credentials()?;
        let response = self
            .request(Method::GET, "/v1/apps?include_unavailable=true", None)
            .await?;
        if !response.is_object() {
            return Err(Error::Protocol);
        }
        Ok(response)
    }

    /// `GET /v1/apps/{app}/metadata?include_unavailable=true` (npm `getApp`).
    pub async fn app_metadata_json(&mut self, app: &str) -> Result<Value> {
        self.require_credentials()?;
        if !super::identifier(app) {
            return Err(Error::Invalid("Invalid App ID."));
        }
        let response = self
            .request(
                Method::GET,
                &format!(
                    "/v1/apps/{}/metadata?include_unavailable=true",
                    segment(app)
                ),
                None,
            )
            .await?;
        if !response.is_object() {
            return Err(Error::Protocol);
        }
        Ok(response)
    }

    /// `GET /v1/apps/{app}/skills/{skill}` (npm `getSkillInfo`).
    pub async fn app_skill_metadata_json(&mut self, app: &str, skill: &str) -> Result<Value> {
        self.require_credentials()?;
        if !super::identifier(app) || !super::identifier(skill) {
            return Err(Error::Invalid("Invalid App skill."));
        }
        let response = self
            .request(
                Method::GET,
                &format!("/v1/apps/{}/skills/{}", segment(app), segment(skill)),
                None,
            )
            .await?;
        if !response.is_object() {
            return Err(Error::Protocol);
        }
        Ok(response)
    }
}
