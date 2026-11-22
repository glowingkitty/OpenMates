//! Answers `project_sandbox_key_request` for the hosted Project sandbox.
//!
//! The server asks the user's devices to hand the Project key to a sandbox
//! (contracts: `docs/plans/hosted-project-sandbox/contracts.md` section 1).
//! The core resolves the key itself, seals it to the sandbox public key and
//! returns only the finished frame; the key never reaches a shell in plaintext.
use super::*;
use crate::crypto::Key;
use crate::work::sandbox_key::{
    CODE_EXPIRED, CODE_INVALID, SandboxKeyRequest, project_sandbox_key_decline_frame,
    project_sandbox_key_grant_frame,
};

/// What this device knows about the requested Project key.
pub(super) enum KeyLookup {
    Key(Key),
    /// The key is not on this device; another device may still answer.
    NoKey,
    /// The chat is not a chat of that Project.
    Invalid,
}

/// The frame answering `request`: a sealed grant, or a decline.
///
/// # Errors
/// Frame construction failures that are not a decline reason.
pub(super) fn answer_frame(
    request: &SandboxKeyRequest,
    now: i64,
    lookup: KeyLookup,
) -> Result<Value> {
    let key = match lookup {
        KeyLookup::Key(key) => key,
        KeyLookup::NoKey => return project_sandbox_key_decline_frame(request, "no_key"),
        KeyLookup::Invalid => return project_sandbox_key_decline_frame(request, "invalid"),
    };
    match project_sandbox_key_grant_frame(request, &key[..], now) {
        Err(Error::Invalid(CODE_EXPIRED)) => project_sandbox_key_decline_frame(request, "expired"),
        Err(Error::Invalid(CODE_INVALID)) => project_sandbox_key_decline_frame(request, "invalid"),
        other => other,
    }
}

impl Client {
    /// Answer one `project_sandbox_key_request` payload with the WS frame
    /// (`{event, payload}`) the shell must send on its main socket: a
    /// `project_sandbox_key_grant` sealed to the sandbox, or a
    /// `project_sandbox_key_decline` (`no_key` when this device lacks the key,
    /// `expired`, `invalid`). The chat must be focused on the Project.
    ///
    /// # Errors
    /// A malformed request (no ids to answer), cancellation, and transport
    /// failures; the shell then sends nothing and another device may answer.
    pub async fn answer_project_sandbox_key_request(
        &mut self,
        event: &Value,
        now: i64,
    ) -> Result<Value> {
        let request: SandboxKeyRequest =
            serde_json::from_value(event.clone()).map_err(|_| Error::Invalid(CODE_INVALID))?;
        if request.expires_at <= now {
            return project_sandbox_key_decline_frame(&request, "expired");
        }
        let lookup = self.sandbox_key_lookup(&request).await?;
        answer_frame(&request, now, lookup)
    }

    async fn sandbox_key_lookup(&mut self, request: &SandboxKeyRequest) -> Result<KeyLookup> {
        self.require_credentials()?;
        let focus = match self.projects().active_focus(&request.chat_id).await {
            Ok(focus) => focus,
            Err(Error::Invalid(_) | Error::Forbidden) => return Ok(KeyLookup::Invalid),
            Err(error) => return Err(error),
        };
        if focus["project_id"].as_str() != Some(request.project_id.as_str()) {
            return Ok(KeyLookup::Invalid);
        }
        let filters = crate::work::ProjectFilters {
            personal: focus["team_id"].as_str().is_none(),
            team_id: focus["team_id"].as_str().map(str::to_owned),
            include_archived: None,
        };
        match self
            .projects()
            .with_filters(filters)
            .project_key_for_command(&request.project_id)
            .await
        {
            Ok(key) => Ok(KeyLookup::Key(key)),
            Err(Error::Forbidden | Error::Crypto) => Ok(KeyLookup::NoKey),
            Err(error) => Err(error),
        }
    }
}

#[cfg(test)]
#[path = "project_sandbox_key_tests.rs"]
mod tests;
