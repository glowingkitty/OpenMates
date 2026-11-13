//! Response deadline of one saved turn (shared core, used by `receive_turn`).
//! `response_timeout_ms` is an idle limit: every received frame restarts it, so a
//! long coding turn that keeps streaming tool and embed events never ends as
//! Offline, while a silent server still does. An absolute cap of one day bounds
//! the whole turn. Spec: `feature.projects` (agentic coding turns).
use std::time::Duration;

use crate::platform::time::Instant;

/// Absolute upper bound of one turn, whatever traffic keeps it alive.
pub(in crate::client) const TURN_MAX_DURATION: Duration = Duration::from_secs(86_400);

/// Idle deadline restarted by received frames, bounded by [`TURN_MAX_DURATION`].
#[derive(Debug, Clone, Copy)]
pub(in crate::client) struct TurnDeadline {
    idle: Duration,
    cap: Instant,
    next: Instant,
}

impl TurnDeadline {
    /// Starts the deadline at `now` with the given idle limit.
    pub(in crate::client) fn start(now: Instant, idle: Duration) -> Self {
        let cap = now + TURN_MAX_DURATION;
        Self {
            idle,
            cap,
            next: (now + idle).min(cap),
        }
    }

    /// Restarts the idle limit after a frame was received at `now`.
    pub(in crate::client) fn on_frame(&mut self, now: Instant) {
        self.next = (now + self.idle).min(self.cap);
    }

    /// The instant at which the wait ends as Offline.
    pub(in crate::client) fn at(&self) -> Instant {
        self.next
    }
}

#[cfg(test)]
#[path = "turn_deadline_tests.rs"]
mod tests;
