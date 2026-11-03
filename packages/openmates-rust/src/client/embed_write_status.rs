//! Embed status state machine, mirroring `embedStateMachine.ts` and
//! backend/shared/python_schemas/embed_status.py.
use serde_json::Value;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum EmbedStatus {
    Processing,
    Rendering,
    Finished,
    Error,
    Cancelled,
    NeedsRerender,
}
impl EmbedStatus {
    pub fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "processing" => Self::Processing,
            "rendering" => Self::Rendering,
            "finished" => Self::Finished,
            "error" => Self::Error,
            "cancelled" => Self::Cancelled,
            "needs_rerender" => Self::NeedsRerender,
            _ => return None,
        })
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Processing => "processing",
            Self::Rendering => "rendering",
            Self::Finished => "finished",
            Self::Error => "error",
            Self::Cancelled => "cancelled",
            Self::NeedsRerender => "needs_rerender",
        }
    }
    /// Allowed transitions; anything not listed is rejected.
    pub fn allows(self, target: Self) -> bool {
        use EmbedStatus::*;
        match self {
            Processing => matches!(target, Processing | Rendering | Finished | Error | Cancelled),
            Rendering => matches!(target, Rendering | Finished | Error | Cancelled),
            // Error: frontend-only decryption failure on a stored embed.
            Finished => matches!(target, Error | NeedsRerender),
            NeedsRerender => matches!(target, NeedsRerender | Rendering | Error | Cancelled),
            Error | Cancelled => false,
        }
    }
    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Finished | Self::Error | Self::Cancelled)
    }
    /// `normalizeEmbedStatus`: valid values pass, everything else (including
    /// the backend alias "completed", null and non-strings) is FINISHED.
    pub fn normalize(value: &Value) -> Self {
        value.as_str().and_then(Self::parse).unwrap_or(Self::Finished)
    }
}
/// `validateEmbedTransition(current, target)`: unknown statuses are invalid.
pub fn transition_allowed(current: &str, target: &str) -> bool {
    match (EmbedStatus::parse(current), EmbedStatus::parse(target)) {
        (Some(from), Some(to)) => from.allows(to),
        _ => false,
    }
}
/// `isTerminalStatus`.
pub fn is_terminal(status: &str) -> bool {
    EmbedStatus::parse(status).is_some_and(EmbedStatus::is_terminal)
}
