//! Delayed, transient connection feedback (port of `connectionFeedbackStore.ts`).
//! Independent of chat UI-readiness flags; timers follow the same no-cancel
//! rule as the link: a fired timer that is no longer armed is ignored.
use super::LinkStatus;

const RECONNECT_DELAY_MS: u64 = 3_000;
const AUTH_STUCK_DELAY_MS: u64 = 12_000;
const SYNC_DELAY_MS: u64 = 600;
const RESUME_GRACE_MS: u64 = 10_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FeedbackState {
    Idle,
    Offline,
    Reconnecting,
    Syncing,
}
impl FeedbackState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Offline => "offline",
            Self::Reconnecting => "reconnecting",
            Self::Syncing => "syncing",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FeedbackReason {
    Offline,
    Reconnecting,
    ServerUpdating,
}
impl FeedbackReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Offline => "offline",
            Self::Reconnecting => "reconnecting",
            Self::ServerUpdating => "server_updating",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Feedback {
    pub state: FeedbackState,
    pub reason: FeedbackReason,
}
const IDLE: Feedback = Feedback { state: FeedbackState::Idle, reason: FeedbackReason::Reconnecting };

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FeedbackInputs {
    pub online: bool,
    pub authenticated: bool,
    pub checking_auth: bool,
    pub status: LinkStatus,
    pub syncing: bool,
}
const INITIAL: FeedbackInputs = FeedbackInputs {
    online: true,
    authenticated: false,
    checking_auth: false,
    status: LinkStatus::Disconnected,
    syncing: false,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum FeedbackTimerKind {
    Reconnect,
    Sync,
    Auth,
    Resume,
}
impl FeedbackTimerKind {
    pub fn code(self) -> u32 {
        match self {
            Self::Reconnect => 0,
            Self::Sync => 1,
            Self::Auth => 2,
            Self::Resume => 3,
        }
    }
    pub fn from_code(code: u32) -> Option<Self> {
        [Self::Reconnect, Self::Sync, Self::Auth, Self::Resume].into_iter().find(|kind| kind.code() == code)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct FeedbackTimer {
    pub kind: FeedbackTimerKind,
    pub seq: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FeedbackCommand {
    Schedule { timer: FeedbackTimer, delay_ms: u64 },
    /// Publish only on change.
    Publish(Feedback),
}

pub struct ConnectionFeedback {
    inputs: FeedbackInputs,
    disconnected: bool,
    auth_stuck: bool,
    syncing: bool,
    resumed: bool,
    server_updating: bool,
    armed: [Option<u32>; 4],
    seq: u32,
    published: Feedback,
}

impl Default for ConnectionFeedback {
    fn default() -> Self {
        Self {
            inputs: INITIAL,
            disconnected: false,
            auth_stuck: false,
            syncing: false,
            resumed: false,
            server_updating: false,
            armed: [None; 4],
            seq: 0,
            published: IDLE,
        }
    }
}

impl ConnectionFeedback {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn current(&self) -> Feedback {
        self.published
    }

    pub fn update(&mut self, next: FeedbackInputs, out: &mut Vec<FeedbackCommand>) {
        self.inputs = next;
        let connected = next.status == LinkStatus::Connected;
        if !next.authenticated || connected {
            self.disarm(FeedbackTimerKind::Reconnect);
            self.disconnected = false;
            if connected {
                self.disarm(FeedbackTimerKind::Resume);
                self.resumed = false;
                self.server_updating = false;
            }
        } else if next.online && !self.resumed && !self.disconnected && !self.is_armed(FeedbackTimerKind::Reconnect) {
            self.arm(FeedbackTimerKind::Reconnect, RECONNECT_DELAY_MS, out);
        }

        if next.online && next.checking_auth {
            if !self.auth_stuck && !self.is_armed(FeedbackTimerKind::Auth) {
                self.arm(FeedbackTimerKind::Auth, AUTH_STUCK_DELAY_MS, out);
            }
        } else {
            self.disarm(FeedbackTimerKind::Auth);
            self.auth_stuck = false;
        }

        if next.online && next.authenticated && connected && next.syncing {
            if !self.syncing && !self.is_armed(FeedbackTimerKind::Sync) {
                self.arm(FeedbackTimerKind::Sync, SYNC_DELAY_MS, out);
            }
        } else {
            self.disarm(FeedbackTimerKind::Sync);
            self.syncing = false;
        }
        self.publish(out);
    }

    pub fn timer(&mut self, timer: FeedbackTimer, out: &mut Vec<FeedbackCommand>) {
        if self.armed[timer.kind.code() as usize] != Some(timer.seq) {
            return;
        }
        self.disarm(timer.kind);
        match timer.kind {
            FeedbackTimerKind::Reconnect => self.disconnected = true,
            FeedbackTimerKind::Auth => self.auth_stuck = true,
            FeedbackTimerKind::Sync => self.syncing = true,
            FeedbackTimerKind::Resume => {
                self.resumed = false;
                self.disconnected = self.inputs.authenticated && self.inputs.status != LinkStatus::Connected;
            }
        }
        self.publish(out);
    }

    /// Page resume: suppress reconnect feedback for a grace period.
    pub fn resume(&mut self, out: &mut Vec<FeedbackCommand>) {
        self.disarm(FeedbackTimerKind::Reconnect);
        self.resumed = true;
        self.disconnected = false;
        self.arm(FeedbackTimerKind::Resume, RESUME_GRACE_MS, out);
        self.publish(out);
    }

    pub fn server_updating(&mut self, out: &mut Vec<FeedbackCommand>) {
        self.server_updating = true;
        self.publish(out);
    }

    pub fn reset(&mut self, out: &mut Vec<FeedbackCommand>) {
        let seq = self.seq;
        let published = self.published;
        *self = Self { seq, published, ..Self::default() };
        self.publish(out);
    }

    fn is_armed(&self, kind: FeedbackTimerKind) -> bool {
        self.armed[kind.code() as usize].is_some()
    }

    fn disarm(&mut self, kind: FeedbackTimerKind) {
        self.armed[kind.code() as usize] = None;
    }

    fn arm(&mut self, kind: FeedbackTimerKind, delay_ms: u64, out: &mut Vec<FeedbackCommand>) {
        self.seq = self.seq.wrapping_add(1);
        self.armed[kind.code() as usize] = Some(self.seq);
        out.push(FeedbackCommand::Schedule { timer: FeedbackTimer { kind, seq: self.seq }, delay_ms });
    }

    fn publish(&mut self, out: &mut Vec<FeedbackCommand>) {
        let inputs = self.inputs;
        let reconnecting = inputs.authenticated && (self.disconnected || self.auth_stuck);
        let state = if !inputs.online {
            FeedbackState::Offline
        } else if !inputs.authenticated {
            FeedbackState::Idle
        } else if reconnecting {
            FeedbackState::Reconnecting
        } else if self.syncing {
            FeedbackState::Syncing
        } else {
            FeedbackState::Idle
        };
        let reason = if !inputs.online {
            FeedbackReason::Offline
        } else if self.server_updating {
            FeedbackReason::ServerUpdating
        } else {
            FeedbackReason::Reconnecting
        };
        let next = Feedback { state, reason };
        if next != self.published {
            self.published = next;
            out.push(FeedbackCommand::Publish(next));
        }
    }
}
