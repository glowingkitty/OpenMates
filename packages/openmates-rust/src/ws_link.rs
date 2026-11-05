//! One shared WebSocket link for the web client: connection/reconnect state
//! machine, inbound handler routing and delayed connection feedback.
//!
//! Sans-IO by design, like [`crate::web_auth`]. The platform adapter owns the
//! physical socket, timers, `JSON.parse` of payloads and the JS handler
//! functions; it feeds every observation in (with the current monotonic time
//! in milliseconds) and executes the returned commands verbatim. That keeps
//! every rule here deterministic and testable with a fake clock and socket.
//!
//! Behaviour follows the deployed TypeScript `websocketService.ts`,
//! `connectionFeedbackStore.ts` and the store contracts of
//! `websocketStatusStore.ts`/`networkStatusStore.ts`. Deliberate differences
//! are documented on [`LinkMachine`]; each one is a fail-closed or faster
//! recovery case, never a looser one.
//!
//! Owner consistency (`architecture.session-owner-consistency`): every
//! reconnect refreshes the session (and with it the `ws_token`) before the
//! socket opens, so a dual-principal server never sees a stale query token
//! next to a fresh cookie. A refresh that the server refuses with
//! `session_principal_mismatch` ends the link in a terminal owner-mismatch
//! state that no automatic event (online, resume, timer) can leave.
mod envelope;
mod feedback;
mod machine;
mod machine_types;
mod router;

pub use envelope::{Envelope, EnvelopeError, PayloadSource, auth_error_message};
pub use feedback::{
    ConnectionFeedback, Feedback, FeedbackCommand, FeedbackInputs, FeedbackReason,
    FeedbackState, FeedbackTimer, FeedbackTimerKind,
};
pub use machine::LinkMachine;
pub use machine_types::{
    Command, FrameKind, Input, LifecycleSource, LinkConfig, LinkEvent, LinkStatus, ReAuthKind,
    RefreshOutcome, RefreshReason, Refusal, ResumeSource,
};
pub use router::{Family, HandlerId, INTERN_CAP, Lane, Registered, Route, RouteAction, Router};

/// Identity of one physical socket the adapter opened for an [`Command::Open`].
/// Events of any other socket are stale and ignored.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct SocketId(pub u32);

/// Link timers. The adapter never cancels timers: a fired timer that is no
/// longer armed is ignored, so there is no cancel command to lose.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum TimerKind {
    Backoff,
    Periodic,
    Ping,
    Pong,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct TimerId {
    pub kind: TimerKind,
    pub seq: u32,
}

#[cfg(test)]
mod envelope_tests;
#[cfg(test)]
mod feedback_tests;
#[cfg(test)]
mod machine_harness;
#[cfg(test)]
mod machine_tests;
#[cfg(test)]
mod router_tests;
