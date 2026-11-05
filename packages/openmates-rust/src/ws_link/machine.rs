//! Connection and reconnect state machine of the shared web WebSocket link.
use super::machine_types::*;
use super::{SocketId, TimerId, TimerKind};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum AfterRefresh {
    Open,
    AbnormalCheck(u16),
    PolicyRetry,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Terminal {
    AuthFailed,
    ReAuth,
    OwnerMismatch,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    Idle,
    Refreshing { refresh: u32, then: AfterRefresh },
    Opening(SocketId),
    Open(SocketId),
    Backoff,
    Periodic,
    Terminal(Terminal),
}

#[derive(Default)]
struct Timers {
    backoff: Option<TimerId>,
    periodic: Option<TimerId>,
    ping: Option<TimerId>,
    pong: Option<TimerId>,
}

/// The link state machine.
///
/// Deliberate differences from `websocketService.ts`:
/// - A 1008 close without a 2FA/passkey reason refreshes the session once and
///   reconnects with the fresh `ws_token` (the dual-principal server closes a
///   stale query token with 1008); a second 1008 before a healthy pong, or a
///   failed refresh, is the TypeScript terminal `authError`.
/// - A refresh refused with `session_principal_mismatch` is terminal and only a
///   sign-out leaves it; online/resume/periodic events never reopen the socket.
/// - Auth failure and re-auth states are sticky against automatic events
///   (TypeScript reopened on `online`); explicit connect/retry leave them.
/// - A pong timeout detaches the dead socket and reconnects at once instead of
///   waiting for the browser's close handshake on a dead connection.
/// - A resume liveness ping arms the pong timeout.
/// - Every attempt except the first one after sign-in refreshes the session
///   (TypeScript skipped it for attempts with a reset counter), and a token
///   refreshed after abnormal closures is used instead of refreshed twice.
/// - Periodic retry runs only after the backoff budget is exhausted, not
///   interleaved with a new backoff cycle.
pub struct LinkMachine {
    config: LinkConfig,
    phase: Phase,
    authenticated: bool,
    logging_out: bool,
    has_token: bool,
    token_fresh: bool,
    foreground: bool,
    ever_connected: bool,
    pending: bool,
    policy_retry_used: bool,
    attempts: u32,
    abnormal: u32,
    last_activity_ms: u64,
    socket_seq: u32,
    refresh_seq: u32,
    timer_seq: u32,
    timers: Timers,
    status: LinkStatus,
    error: Option<String>,
}

impl Default for LinkMachine {
    fn default() -> Self {
        Self::new(LinkConfig::default())
    }
}

impl LinkMachine {
    pub fn new(config: LinkConfig) -> Self {
        Self {
            config,
            phase: Phase::Idle,
            authenticated: false,
            logging_out: false,
            has_token: false,
            token_fresh: false,
            foreground: false,
            ever_connected: false,
            pending: false,
            policy_retry_used: false,
            attempts: 0,
            abnormal: 0,
            last_activity_ms: 0,
            socket_seq: 0,
            refresh_seq: 0,
            timer_seq: 0,
            timers: Timers::default(),
            status: LinkStatus::Disconnected,
            error: None,
        }
    }

    pub fn status(&self) -> LinkStatus {
        self.status
    }
    pub fn error(&self) -> Option<&str> {
        self.error.as_deref()
    }
    pub fn attempts(&self) -> u32 {
        self.attempts
    }
    /// The open socket, if any (TypeScript `isConnected()`).
    pub fn open_socket(&self) -> Option<SocketId> {
        match self.phase {
            Phase::Open(socket) => Some(socket),
            _ => None,
        }
    }
    /// True while a connection attempt (refresh or opening socket) is pending.
    pub fn attempt_pending(&self) -> bool {
        matches!(self.phase, Phase::Opening(_)) || matches!(self.phase, Phase::Refreshing { then: AfterRefresh::Open, .. })
    }
    /// True once the server refused this session's owner.
    pub fn owner_mismatch(&self) -> bool {
        self.phase == Phase::Terminal(Terminal::OwnerMismatch)
    }

    /// Observe one inbound frame. Returns whether it belongs to the open socket
    /// and may be dispatched to handlers.
    pub fn frame(&mut self, now_ms: u64, socket: SocketId, kind: FrameKind<'_>, out: &mut Vec<Command>) -> bool {
        if self.open_socket() != Some(socket) {
            return false;
        }
        self.last_activity_ms = now_ms;
        match kind {
            FrameKind::Data => true,
            FrameKind::Pong => {
                self.timers.pong = None;
                self.policy_retry_used = false;
                true
            }
            FrameKind::ServerRestarting => {
                out.push(Command::Emit(LinkEvent::ServerRestarting));
                true
            }
            FrameKind::AuthError(message) => {
                let message = (!message.is_empty()).then(|| message.to_owned());
                let shown = message.clone().unwrap_or_else(|| "Authentication failed. Please log in again.".into());
                self.close_current(1008, "Authentication failed", out);
                self.terminal(Terminal::AuthFailed, out);
                self.set_error(shown, out);
                out.push(Command::Emit(LinkEvent::AuthError(Some(message.unwrap_or_else(|| "Authentication failed".into())))));
                false
            }
        }
    }

    pub fn handle(&mut self, now_ms: u64, input: Input<'_>, out: &mut Vec<Command>) {
        match input {
            Input::Session { authenticated, logging_out, has_token } => {
                self.session(authenticated, logging_out, has_token, out)
            }
            Input::Connect => self.connect(out),
            Input::Retry => {
                if self.open_socket().is_some() || !self.authenticated || self.attempt_pending() || self.owner_mismatch() {
                    return;
                }
                self.leave_waiting();
                self.attempts = 0;
                self.set_status(LinkStatus::Reconnecting, out);
                self.start_attempt(out);
            }
            Input::ForceReconnect(reason) => {
                if !self.authenticated || self.owner_mismatch() {
                    return;
                }
                let reason: String = reason.chars().take(120).collect();
                self.close_current(1000, &reason, out);
                self.stop_timers();
                self.settle(Err(Refusal::Superseded), out);
                self.phase = Phase::Idle;
                self.attempts = 0;
                self.set_status(LinkStatus::Reconnecting, out);
                self.start_attempt(out);
            }
            Input::Disconnect => self.disconnect(out),
            Input::Refreshed { refresh, outcome, has_token } => self.refreshed(refresh, outcome, has_token, out),
            Input::Opened(socket) => self.opened(now_ms, socket, out),
            Input::Errored(socket) => {
                if matches!(self.phase, Phase::Opening(s) | Phase::Open(s) if s == socket) {
                    out.push(Command::Emit(LinkEvent::Error));
                    self.settle(Err(Refusal::SocketError), out);
                }
            }
            Input::Closed { socket, code, reason, was_clean } => {
                if matches!(self.phase, Phase::Opening(s) | Phase::Open(s) if s == socket) {
                    self.closed(code, reason, was_clean, out);
                }
            }
            Input::Timer(timer) => self.timer(now_ms, timer, out),
            Input::Online => self.network_restored(out),
            Input::NetworkChanged => {
                if self.ever_connected || self.authenticated {
                    self.network_restored(out);
                }
            }
            Input::Resumed(_) => {
                if !self.authenticated {
                    return;
                }
                out.push(Command::Emit(LinkEvent::Resuming));
                if let Some(socket) = self.open_socket() {
                    out.push(Command::SendPing { socket });
                    if self.timers.pong.is_none() {
                        self.arm(TimerKind::Pong, self.config.pong_timeout_ms, out);
                    }
                } else {
                    self.network_restored(out);
                }
            }
            Input::Foreground { foreground, source } => {
                self.foreground = foreground;
                if let Some(socket) = self.open_socket() {
                    out.push(Command::SendLifecycle { socket, foreground, source });
                }
            }
            Input::DataActivity => {
                self.last_activity_ms = now_ms;
                self.timers.pong = None;
            }
        }
    }

    fn session(&mut self, authenticated: bool, logging_out: bool, has_token: bool, out: &mut Vec<Command>) {
        let rising = authenticated && !self.authenticated;
        self.authenticated = authenticated;
        self.logging_out = logging_out;
        self.has_token = has_token;
        if rising {
            // The token stored with a fresh sign-in is trusted for one open.
            self.token_fresh = has_token;
        }
        if !authenticated {
            let active = self.open_socket().is_some() || self.attempt_pending() || !matches!(self.phase, Phase::Idle);
            if active {
                self.disconnect(out);
            }
            return;
        }
        if rising && matches!(self.phase, Phase::Terminal(Terminal::AuthFailed | Terminal::ReAuth)) {
            self.phase = Phase::Idle;
        }
        if self.phase == Phase::Idle {
            self.start_attempt(out);
        }
    }

    fn connect(&mut self, out: &mut Vec<Command>) {
        if self.open_socket().is_some() {
            out.push(Command::Settle(Ok(())));
            return;
        }
        match self.phase {
            Phase::Terminal(Terminal::OwnerMismatch) => {
                out.push(Command::Settle(Err(Refusal::OwnerMismatch)));
                return;
            }
            // The running attempt settles this caller too.
            Phase::Opening(_) | Phase::Refreshing { .. } => {
                self.pending = true;
                return;
            }
            _ => {}
        }
        self.leave_waiting();
        self.start_attempt(out);
    }

    fn disconnect(&mut self, out: &mut Vec<Command>) {
        self.close_current(1000, "Client initiated disconnect", out);
        self.stop_timers();
        self.settle(Err(Refusal::ManualDisconnect), out);
        if !self.owner_mismatch() || !self.authenticated {
            self.phase = Phase::Idle;
        }
        self.attempts = 0;
        self.abnormal = 0;
        self.set_status(LinkStatus::Disconnected, out);
    }

    /// Backoff, periodic and terminal auth phases become idle before an
    /// explicit attempt. The owner-mismatch terminal is never left here.
    fn leave_waiting(&mut self) {
        self.timers.backoff = None;
        self.timers.periodic = None;
        if matches!(self.phase, Phase::Backoff | Phase::Periodic | Phase::Terminal(Terminal::AuthFailed | Terminal::ReAuth)) {
            self.phase = Phase::Idle;
        }
    }

    fn network_restored(&mut self, out: &mut Vec<Command>) {
        if !self.authenticated || self.open_socket().is_some() || self.attempt_pending() {
            return;
        }
        if !matches!(self.phase, Phase::Idle | Phase::Backoff | Phase::Periodic) {
            return;
        }
        self.leave_waiting();
        self.attempts = 0;
        self.start_attempt(out);
    }

    fn start_attempt(&mut self, out: &mut Vec<Command>) {
        self.pending = true;
        if !self.authenticated || self.logging_out {
            self.phase = Phase::Idle;
            self.set_status(LinkStatus::Disconnected, out);
            let refusal = if self.authenticated { Refusal::LogoutInProgress } else { Refusal::NotAuthenticated };
            self.settle(Err(refusal), out);
            return;
        }
        let reconnecting = self.attempts > 0;
        self.set_status(if reconnecting { LinkStatus::Reconnecting } else { LinkStatus::Connecting }, out);
        if !self.has_token || !self.token_fresh {
            let reason = if self.has_token { RefreshReason::Reconnect } else { RefreshReason::MissingToken };
            self.refresh(reason, AfterRefresh::Open, out);
        } else {
            self.open_new_socket(out);
        }
    }

    fn refresh(&mut self, reason: RefreshReason, then: AfterRefresh, out: &mut Vec<Command>) {
        self.refresh_seq = self.refresh_seq.wrapping_add(1);
        self.phase = Phase::Refreshing { refresh: self.refresh_seq, then };
        out.push(Command::RefreshSession { refresh: self.refresh_seq, reason });
    }

    fn open_new_socket(&mut self, out: &mut Vec<Command>) {
        self.socket_seq = self.socket_seq.wrapping_add(1);
        let socket = SocketId(self.socket_seq);
        self.token_fresh = false;
        self.phase = Phase::Opening(socket);
        out.push(Command::Open { socket });
    }

    fn refreshed(&mut self, refresh: u32, outcome: RefreshOutcome, has_token: bool, out: &mut Vec<Command>) {
        let Phase::Refreshing { refresh: expected, then } = self.phase else { return };
        if refresh != expected {
            return;
        }
        if outcome == RefreshOutcome::PrincipalMismatch {
            self.owner_mismatch_terminal(out);
            return;
        }
        self.has_token = has_token;
        let valid = outcome == RefreshOutcome::Ready && has_token;
        self.token_fresh = valid;
        match then {
            AfterRefresh::Open => {
                if outcome == RefreshOutcome::SignedOut || !self.authenticated || self.logging_out {
                    self.phase = Phase::Idle;
                    self.set_status(LinkStatus::Disconnected, out);
                    self.settle(Err(Refusal::SessionEnded), out);
                    return;
                }
                // TypeScript opens with whatever token the refresh left behind.
                self.open_new_socket(out);
            }
            AfterRefresh::AbnormalCheck(code) => {
                if !valid {
                    self.auth_failed("Authentication failed. Please log in again.", "Session expired or invalid token", out);
                    return;
                }
                self.abnormal = 0;
                self.attempts = 0;
                self.schedule_reconnect(code, out);
            }
            AfterRefresh::PolicyRetry => {
                if !valid {
                    self.auth_failed("Connection closed due to policy violation.", "policy_violation", out);
                    return;
                }
                self.set_status(LinkStatus::Reconnecting, out);
                self.open_new_socket(out);
            }
        }
    }

    fn opened(&mut self, now_ms: u64, socket: SocketId, out: &mut Vec<Command>) {
        if self.phase != Phase::Opening(socket) {
            out.push(Command::Close { socket, code: 1000, reason: "Superseded by new connection attempt".into() });
            return;
        }
        self.phase = Phase::Open(socket);
        self.ever_connected = true;
        self.attempts = 0;
        self.abnormal = 0;
        self.last_activity_ms = now_ms;
        self.timers.periodic = None;
        self.timers.backoff = None;
        out.push(Command::Emit(LinkEvent::Open));
        self.set_status(LinkStatus::Connected, out);
        out.push(Command::SendLifecycle { socket, foreground: self.foreground, source: LifecycleSource::Open });
        self.arm(TimerKind::Ping, self.config.ping_interval_ms, out);
        self.settle(Ok(()), out);
    }

    fn closed(&mut self, code: u16, reason: &str, was_clean: bool, out: &mut Vec<Command>) {
        self.phase = Phase::Idle;
        self.timers.ping = None;
        self.timers.pong = None;
        if !matches!(self.status, LinkStatus::Disconnected | LinkStatus::Error) {
            out.push(Command::Emit(LinkEvent::Close(code)));
        }
        if code == 1008 {
            self.abnormal = 0;
            let kind = if reason.contains("2FA required") {
                Some(ReAuthKind::TwoFactor)
            } else if reason.contains("Passkey required") {
                Some(ReAuthKind::Passkey)
            } else {
                None
            };
            let shown = if reason.is_empty() { "Connection closed due to policy violation." } else { reason };
            if let Some(kind) = kind {
                self.terminal(Terminal::ReAuth, out);
                self.set_error(shown.to_owned(), out);
                out.push(Command::Emit(LinkEvent::ReAuthRequired(kind)));
                self.settle(Err(Refusal::ReAuthRequired), out);
            } else if self.authenticated && !self.policy_retry_used {
                self.policy_retry_used = true;
                self.set_status(LinkStatus::Reconnecting, out);
                self.refresh(RefreshReason::PolicyClose, AfterRefresh::PolicyRetry, out);
            } else {
                self.auth_failed(shown, "policy_violation", out);
            }
            return;
        }
        if code == 1006 && !was_clean {
            self.abnormal += 1;
            let lowered = reason.to_lowercase();
            let auth_related = ["forbidden", "403", "invalid", "expired", "token", "unauthorized"]
                .iter()
                .any(|needle| lowered.contains(needle));
            if self.abnormal >= self.config.abnormal_auth_threshold || auth_related {
                let reason = if auth_related { RefreshReason::AuthRelatedClose } else { RefreshReason::AbnormalClosures };
                self.refresh(reason, AfterRefresh::AbnormalCheck(code), out);
                return;
            }
        } else {
            self.abnormal = 0;
        }
        self.schedule_reconnect(code, out);
    }

    fn schedule_reconnect(&mut self, code: u16, out: &mut Vec<Command>) {
        if self.authenticated && self.attempts < self.config.max_attempts {
            self.set_status(LinkStatus::Reconnecting, out);
            self.attempts += 1;
            let shift = (self.attempts - 1).min(32);
            let delay = self.config.base_delay_ms.saturating_mul(1u64 << shift).min(self.config.max_delay_ms);
            self.phase = Phase::Backoff;
            self.arm(TimerKind::Backoff, delay, out);
            self.settle(Err(Refusal::Closed(code)), out);
        } else if self.authenticated {
            self.set_error("Max reconnect attempts reached. Will keep retrying.".into(), out);
            out.push(Command::Emit(LinkEvent::ConnectionFailedReconnect));
            self.phase = Phase::Periodic;
            self.arm(TimerKind::Periodic, self.config.periodic_retry_ms, out);
            self.settle(Err(Refusal::MaxAttempts), out);
        } else {
            self.phase = Phase::Idle;
            self.set_status(LinkStatus::Disconnected, out);
            self.settle(Err(Refusal::SessionEnded), out);
        }
    }

    fn timer(&mut self, now_ms: u64, timer: TimerId, out: &mut Vec<Command>) {
        let slot = match timer.kind {
            TimerKind::Backoff => &mut self.timers.backoff,
            TimerKind::Periodic => &mut self.timers.periodic,
            TimerKind::Ping => &mut self.timers.ping,
            TimerKind::Pong => &mut self.timers.pong,
        };
        if *slot != Some(timer) {
            return;
        }
        *slot = None;
        match timer.kind {
            TimerKind::Backoff => {
                if self.phase == Phase::Backoff {
                    self.phase = Phase::Idle;
                    self.start_attempt(out);
                }
            }
            TimerKind::Periodic => {
                if self.phase == Phase::Periodic && self.authenticated {
                    self.phase = Phase::Idle;
                    self.attempts = 0;
                    self.start_attempt(out);
                }
            }
            TimerKind::Ping => {
                let Some(socket) = self.open_socket() else { return };
                out.push(Command::SendLifecycle { socket, foreground: self.foreground, source: LifecycleSource::Heartbeat });
                out.push(Command::SendPing { socket });
                self.arm(TimerKind::Pong, self.config.pong_timeout_ms, out);
                self.arm(TimerKind::Ping, self.config.ping_interval_ms, out);
            }
            TimerKind::Pong => {
                if self.open_socket().is_none() || now_ms.saturating_sub(self.last_activity_ms) < self.config.pong_timeout_ms {
                    return;
                }
                self.close_current(1000, "Pong timeout - client initiated close", out);
                self.closed(1000, "Pong timeout - client initiated close", true, out);
            }
        }
    }

    fn arm(&mut self, kind: TimerKind, delay_ms: u64, out: &mut Vec<Command>) {
        self.timer_seq = self.timer_seq.wrapping_add(1);
        let timer = TimerId { kind, seq: self.timer_seq };
        let slot = match kind {
            TimerKind::Backoff => &mut self.timers.backoff,
            TimerKind::Periodic => &mut self.timers.periodic,
            TimerKind::Ping => &mut self.timers.ping,
            TimerKind::Pong => &mut self.timers.pong,
        };
        *slot = Some(timer);
        out.push(Command::Schedule { timer, delay_ms });
    }

    fn stop_timers(&mut self) {
        self.timers = Timers::default();
    }

    /// Detach and close the current socket; its later events are ignored.
    fn close_current(&mut self, code: u16, reason: &str, out: &mut Vec<Command>) {
        if let Phase::Opening(socket) | Phase::Open(socket) = self.phase {
            out.push(Command::Close { socket, code, reason: reason.to_owned() });
            self.phase = Phase::Idle;
        }
        self.timers.ping = None;
        self.timers.pong = None;
    }

    fn terminal(&mut self, terminal: Terminal, out: &mut Vec<Command>) {
        self.close_current(1000, "Client initiated disconnect", out);
        self.stop_timers();
        self.abnormal = 0;
        self.phase = Phase::Terminal(terminal);
    }

    fn auth_failed(&mut self, status_error: &str, reason: &str, out: &mut Vec<Command>) {
        self.terminal(Terminal::AuthFailed, out);
        self.set_error(status_error.to_owned(), out);
        out.push(Command::Emit(LinkEvent::AuthError(Some(reason.to_owned()))));
        self.settle(Err(Refusal::AuthFailed), out);
    }

    fn owner_mismatch_terminal(&mut self, out: &mut Vec<Command>) {
        self.terminal(Terminal::OwnerMismatch, out);
        self.set_error(Refusal::OwnerMismatch.as_str().to_owned(), out);
        out.push(Command::Emit(LinkEvent::AuthError(Some(Refusal::OwnerMismatch.as_str().to_owned()))));
        self.settle(Err(Refusal::OwnerMismatch), out);
    }

    fn settle(&mut self, result: Result<(), Refusal>, out: &mut Vec<Command>) {
        if std::mem::take(&mut self.pending) {
            out.push(Command::Settle(result));
        }
    }

    fn set_status(&mut self, status: LinkStatus, out: &mut Vec<Command>) {
        if self.status == status && self.error.is_none() {
            return;
        }
        self.status = status;
        self.error = None;
        out.push(Command::Status { status, error: None });
    }

    fn set_error(&mut self, error: String, out: &mut Vec<Command>) {
        self.status = LinkStatus::Error;
        self.error = Some(error.clone());
        out.push(Command::Status { status: LinkStatus::Error, error: Some(error) });
    }
}
