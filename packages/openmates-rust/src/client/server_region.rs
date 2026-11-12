//! Server region preference for AI turns (shared core; commit "server region
//! preference", `docs/architecture/ai/ai-model-selection.md`). The setting is
//! device-local, never an account field: the web keeps it in its user-profile
//! store (`server_region_preference`), a native shell in its own preferences.
//! Each turn carries it as `model_routing_restrictions.server_region_preference`
//! (server schema `ModelRoutingRestrictions`), which the server applies when it
//! resolves the model's server. `Eu` (the default) prefers EU-hosted servers;
//! `Global` takes each model's fastest server. Native sends set it through
//! `SendOptions::server_region`.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

/// Where a turn's model should preferably run.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ServerRegionPreference {
    /// Prefer EU-hosted servers (the default, also for unknown values).
    #[default]
    Eu,
    /// Fastest server of each model, worldwide.
    Global,
}

impl ServerRegionPreference {
    /// The wire value (`"eu"` or `"global"`).
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Eu => "eu",
            Self::Global => "global",
        }
    }

    /// A stored value: `"global"` is `Global`, anything else `Eu` (as the web
    /// reads its profile field).
    pub fn from_stored(value: &str) -> Self {
        if value == "global" {
            Self::Global
        } else {
            Self::Eu
        }
    }

    /// The turn's `model_routing_restrictions` object, or `None` for `Eu`,
    /// which is the server default (turns stay byte-identical to before).
    pub(crate) fn routing_restrictions(self) -> Option<Value> {
        match self {
            Self::Eu => None,
            Self::Global => Some(json!({"server_region_preference": self.as_str()})),
        }
    }
}

#[cfg(test)]
#[path = "server_region_tests.rs"]
mod tests;
