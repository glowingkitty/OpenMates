//! spec: sdk.client.thin-platform-boundary
//! Inbound embed event admission (port of `isEmbedEventAdmitted` in
//! `embedStateMachine.ts`): whether an `embed_update` / `send_embed_data` event
//! may be applied to a stored embed. The page keeps the reads, logging and writes.
use super::status::{normalize_status, validate_transition};

/// Stored and incoming facts of one inbound embed event.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct EmbedEventFacts<'a> {
    /// Status stored for the embed.
    pub current_status: &'a str,
    /// Status carried by the event (`None` when absent or not a string).
    pub incoming_status: Option<&'a str>,
    /// Stored version number, when numeric.
    pub current_version: Option<f64>,
    /// Version number of the event, when numeric.
    pub incoming_version: Option<f64>,
    /// `send_embed_data`: a newer version or finished refresh bypasses the transition check.
    pub version_exempt: bool,
}

/// True when the event may be applied (mirrors the TS decision exactly).
pub fn is_embed_event_admitted(facts: &EmbedEventFacts<'_>) -> bool {
    let incoming = normalize_status(facts.incoming_status);
    if facts.version_exempt {
        let newer = facts
            .incoming_version
            .is_some_and(|v| v > facts.current_version.unwrap_or(0.0));
        let finalized_refresh = facts.current_status == incoming && incoming == "finished";
        if newer || finalized_refresh {
            return true;
        }
    }
    validate_transition(facts.current_status, incoming)
}
