//! Public inputs, commands and configuration of the link state machine.
use super::{SocketId, TimerId};

/// Timing and retry limits. Defaults are the deployed TypeScript constants.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LinkConfig {
    pub max_attempts: u32,
    pub base_delay_ms: u64,
    pub max_delay_ms: u64,
    pub periodic_retry_ms: u64,
    pub ping_interval_ms: u64,
    pub pong_timeout_ms: u64,
    pub abnormal_auth_threshold: u32,
}
impl Default for LinkConfig {
    fn default() -> Self {
        Self {
            max_attempts: 10,
            base_delay_ms: 1_000,
            max_delay_ms: 5_000,
            periodic_retry_ms: 30_000,
            ping_interval_ms: 25_000,
            pong_timeout_ms: 10_000,
            abnormal_auth_threshold: 4,
        }
    }
}

/// Values of the TypeScript `WebSocketStatus` store.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LinkStatus {
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Error,
}
impl LinkStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Disconnected => "disconnected",
            Self::Connecting => "connecting",
            Self::Connected => "connected",
            Self::Reconnecting => "reconnecting",
            Self::Error => "error",
        }
    }
}

/// Why the adapter is asked to refresh the session (and its `ws_token`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RefreshReason {
    MissingToken,
    Reconnect,
    AbnormalClosures,
    AuthRelatedClose,
    PolicyClose,
}
impl RefreshReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::MissingToken => "missing WebSocket token",
            Self::Reconnect => "reconnect attempt",
            Self::AbnormalClosures => "repeated abnormal closures",
            Self::AuthRelatedClose => "auth-related close reason",
            Self::PolicyClose => "policy violation close",
        }
    }
}

/// Result of one session refresh, as the adapter observed it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RefreshOutcome {
    /// The session is valid; `has_token` reports whether a `ws_token` came back.
    Ready,
    /// The server confirmed the user is no longer signed in.
    SignedOut,
    /// The server refused the refresh with `session_principal_mismatch`.
    PrincipalMismatch,
    /// Network or server failure; the session state is unknown.
    Failed,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReAuthKind {
    TwoFactor,
    Passkey,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ResumeSource {
    VisibilityChange,
    PageShow,
}

/// `source` of a `native_client_lifecycle` frame.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LifecycleSource {
    Open,
    Heartbeat,
    VisibilityChange,
    Focus,
    Blur,
    PageHide,
    RecoveryRequiresForeground,
}
impl LifecycleSource {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Heartbeat => "heartbeat",
            Self::VisibilityChange => "visibilitychange",
            Self::Focus => "focus",
            Self::Blur => "blur",
            Self::PageHide => "pagehide",
            Self::RecoveryRequiresForeground => "recovery_requires_foreground",
        }
    }
}

/// Why a pending `connect()` was rejected.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Refusal {
    NotAuthenticated,
    LogoutInProgress,
    SessionEnded,
    Superseded,
    ManualDisconnect,
    SocketError,
    Closed(u16),
    MaxAttempts,
    AuthFailed,
    ReAuthRequired,
    OwnerMismatch,
}
impl Refusal {
    /// Rejection value of the TypeScript `connect()` promise where one exists.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::NotAuthenticated => "User not authenticated",
            Self::LogoutInProgress => "Logout in progress",
            Self::SessionEnded => "Session ended during connection attempt",
            Self::Superseded => "Connection attempt superseded",
            Self::ManualDisconnect => "Manual disconnect",
            Self::SocketError => "WebSocket error",
            Self::Closed(_) => "Connection closed, attempting reconnect.",
            Self::MaxAttempts => "Max reconnect attempts reached",
            Self::AuthFailed => "Authentication failed",
            Self::ReAuthRequired => "Re-authentication required",
            Self::OwnerMismatch => "session_principal_mismatch",
        }
    }
}

/// Events of the TypeScript service's `EventTarget`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LinkEvent {
    Open,
    Close(u16),
    Error,
    AuthError(Option<String>),
    ReAuthRequired(ReAuthKind),
    ConnectionFailedReconnect,
    Resuming,
    ServerRestarting,
}

/// Work for the adapter, executed in order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Command {
    /// Refresh the session; answer with [`Input::Refreshed`] carrying `refresh`.
    RefreshSession { refresh: u32, reason: RefreshReason },
    /// Open a new socket with the current `ws_token` and report its events.
    Open { socket: SocketId },
    /// Detach every listener of `socket`, then close it. The machine ignores
    /// all later events of a closed socket.
    Close { socket: SocketId, code: u16, reason: String },
    SendPing { socket: SocketId },
    SendLifecycle { socket: SocketId, foreground: bool, source: LifecycleSource },
    /// Call back with [`Input::Timer`] after `delay_ms`.
    Schedule { timer: TimerId, delay_ms: u64 },
    Status { status: LinkStatus, error: Option<String> },
    Emit(LinkEvent),
    /// Resolve (`Ok`) or reject every pending `connect()` promise.
    Settle(Result<(), Refusal>),
}

/// Classification of one inbound frame (see [`super::Router`]).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FrameKind<'a> {
    Pong,
    ServerRestarting,
    /// An `error` frame whose message is an authentication failure.
    AuthError(&'a str),
    Data,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Input<'a> {
    /// Auth store and logout flags. `has_token` reports a stored `ws_token`.
    Session { authenticated: bool, logging_out: bool, has_token: bool },
    Connect,
    /// User-initiated retry (offline banner).
    Retry,
    ForceReconnect(&'a str),
    Disconnect,
    Refreshed { refresh: u32, outcome: RefreshOutcome, has_token: bool },
    Opened(SocketId),
    Errored(SocketId),
    Closed { socket: SocketId, code: u16, reason: &'a str, was_clean: bool },
    Timer(TimerId),
    Online,
    NetworkChanged,
    Resumed(ResumeSource),
    Foreground { foreground: bool, source: LifecycleSource },
    /// Proof of life from a consumer (e.g. streaming chunks).
    DataActivity,
}
