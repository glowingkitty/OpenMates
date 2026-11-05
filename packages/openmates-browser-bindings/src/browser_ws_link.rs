//! Shared WebSocket link exports. Policy lives in `openmates_sdk::ws_link`;
//! this file only converts between JS values and the sans-IO core.
//!
//! Control inputs (session, socket open/close, timers, online, resume) return
//! a JSON array of commands. The per-frame hot path returns one `u32` route
//! code and copies nothing: the adapter interns each message type once
//! (`intern`) and then calls `frame_id` with the id; `error` frames carry
//! their message through `frame`. When a frame also produced link commands,
//! `code & FRAME_COMMANDS` is set and the adapter reads them with `drain()`.
//! Handler order is owned here; the adapter mirrors `handlers(type)` after
//! every registration change instead of receiving ids per frame.
use openmates_sdk::ws_link::{
    Command, ConnectionFeedback, Family, FeedbackCommand, FeedbackInputs, FeedbackTimer,
    FeedbackTimerKind, Input, Lane, LifecycleSource, LinkEvent, LinkMachine, LinkStatus,
    ReAuthKind, RefreshOutcome, Registered, ResumeSource, RouteAction, Router, SocketId, TimerId,
    TimerKind,
};
use serde_json::{Value, json};
use wasm_bindgen::prelude::*;

const DISPATCH: u32 = 0;
const DISPATCH_SERIALIZED: u32 = 1;
const BUFFER: u32 = 2;
const BUFFER_EVICT_OLDEST: u32 = 3;
const IGNORE: u32 = 4;
const UNHANDLED: u32 = 5;
const STALE: u32 = 6;
/// `frame_id` with an id `intern` never issued: an adapter bug.
const UNKNOWN_TYPE_ID: u32 = 7;
const FRAME_COMMANDS: u32 = 0x10;
/// `intern` answer once the table is full; the adapter then passes strings.
const NOT_INTERNED: u32 = u32::MAX;

fn invalid() -> JsValue {
    JsValue::from_str("protocol")
}

fn timer_kind(code: u32) -> Option<TimerKind> {
    [TimerKind::Backoff, TimerKind::Periodic, TimerKind::Ping, TimerKind::Pong].get(code as usize).copied()
}
fn timer_code(kind: TimerKind) -> u32 {
    match kind {
        TimerKind::Backoff => 0,
        TimerKind::Periodic => 1,
        TimerKind::Ping => 2,
        TimerKind::Pong => 3,
    }
}
fn lifecycle_source(code: u32) -> Option<LifecycleSource> {
    use LifecycleSource::*;
    [Open, Heartbeat, VisibilityChange, Focus, Blur, PageHide, RecoveryRequiresForeground].get(code as usize).copied()
}
fn status_of(name: &str) -> Option<LinkStatus> {
    use LinkStatus::*;
    [Disconnected, Connecting, Connected, Reconnecting, Error].into_iter().find(|status| status.as_str() == name)
}

fn action_code(action: RouteAction) -> u32 {
    match action {
        RouteAction::Dispatch(Lane::Serialized) => DISPATCH_SERIALIZED,
        RouteAction::Dispatch(Lane::Concurrent) => DISPATCH,
        RouteAction::Buffer { evict_oldest: true } => BUFFER_EVICT_OLDEST,
        RouteAction::Buffer { evict_oldest: false } => BUFFER,
        RouteAction::Ignore => IGNORE,
        RouteAction::Unhandled => UNHANDLED,
    }
}

fn event_json(event: &LinkEvent) -> Value {
    match event {
        LinkEvent::Open => json!({"op": "emit", "event": "open"}),
        LinkEvent::Close(code) => json!({"op": "emit", "event": "close", "code": code}),
        LinkEvent::Error => json!({"op": "emit", "event": "error"}),
        LinkEvent::AuthError(reason) => json!({"op": "emit", "event": "authError", "reason": reason}),
        LinkEvent::ReAuthRequired(kind) => json!({"op": "emit", "event": "reAuthRequired",
            "type": match kind { ReAuthKind::TwoFactor => "2fa", ReAuthKind::Passkey => "passkey" }}),
        LinkEvent::ConnectionFailedReconnect => json!({"op": "emit", "event": "connection_failed_reconnect"}),
        LinkEvent::Resuming => json!({"op": "emit", "event": "resuming"}),
        LinkEvent::ServerRestarting => json!({"op": "emit", "event": "serverRestarting"}),
    }
}

fn command_json(command: &Command) -> Value {
    match command {
        Command::RefreshSession { refresh, reason } => json!({"op": "refresh", "refresh": refresh, "reason": reason.as_str()}),
        Command::Open { socket } => json!({"op": "open", "socket": socket.0}),
        Command::Close { socket, code, reason } => json!({"op": "close", "socket": socket.0, "code": code, "reason": reason}),
        Command::SendPing { socket } => json!({"op": "ping", "socket": socket.0}),
        Command::SendLifecycle { socket, foreground, source } => {
            json!({"op": "lifecycle", "socket": socket.0, "foreground": foreground, "source": source.as_str()})
        }
        Command::Schedule { timer, delay_ms } => {
            json!({"op": "schedule", "timer": timer_code(timer.kind), "seq": timer.seq, "delay": delay_ms})
        }
        Command::Status { status, error } => json!({"op": "status", "status": status.as_str(), "error": error}),
        Command::Emit(event) => event_json(event),
        Command::Settle(Ok(())) => json!({"op": "settle", "ok": true}),
        Command::Settle(Err(refusal)) => json!({"op": "settle", "ok": false, "reason": refusal.as_str()}),
    }
}

fn commands_json(commands: &mut Vec<Command>) -> String {
    let values: Vec<Value> = commands.drain(..).map(|command| command_json(&command)).collect();
    Value::Array(values).to_string()
}

/// One link per realm: state machine plus router for the single socket.
#[wasm_bindgen]
pub struct BrowserWsLink {
    machine: LinkMachine,
    router: Router,
    out: Vec<Command>,
}

#[wasm_bindgen]
impl BrowserWsLink {
    #[wasm_bindgen(constructor)]
    pub fn new() -> BrowserWsLink {
        BrowserWsLink { machine: LinkMachine::default(), router: Router::new(), out: Vec::new() }
    }

    fn run(&mut self, now: f64, input: Input<'_>) -> String {
        self.machine.handle(now as u64, input, &mut self.out);
        commands_json(&mut self.out)
    }

    pub fn session(&mut self, now: f64, authenticated: bool, logging_out: bool, has_token: bool) -> String {
        self.run(now, Input::Session { authenticated, logging_out, has_token })
    }
    pub fn connect(&mut self, now: f64) -> String {
        self.run(now, Input::Connect)
    }
    pub fn retry(&mut self, now: f64) -> String {
        self.run(now, Input::Retry)
    }
    pub fn force_reconnect(&mut self, now: f64, reason: &str) -> String {
        self.run(now, Input::ForceReconnect(reason))
    }
    pub fn disconnect(&mut self, now: f64) -> String {
        self.run(now, Input::Disconnect)
    }
    /// `outcome`: 0 ready, 1 signed out, 2 principal mismatch, 3 failed.
    pub fn refreshed(&mut self, now: f64, refresh: u32, outcome: u32, has_token: bool) -> Result<String, JsValue> {
        let outcome = [RefreshOutcome::Ready, RefreshOutcome::SignedOut, RefreshOutcome::PrincipalMismatch, RefreshOutcome::Failed]
            .get(outcome as usize)
            .copied()
            .ok_or_else(invalid)?;
        Ok(self.run(now, Input::Refreshed { refresh, outcome, has_token }))
    }
    pub fn opened(&mut self, now: f64, socket: u32) -> String {
        self.run(now, Input::Opened(SocketId(socket)))
    }
    pub fn errored(&mut self, now: f64, socket: u32) -> String {
        self.run(now, Input::Errored(SocketId(socket)))
    }
    pub fn closed(&mut self, now: f64, socket: u32, code: u16, reason: &str, was_clean: bool) -> String {
        self.run(now, Input::Closed { socket: SocketId(socket), code, reason, was_clean })
    }
    pub fn timer(&mut self, now: f64, kind: u32, seq: u32) -> Result<String, JsValue> {
        let kind = timer_kind(kind).ok_or_else(invalid)?;
        Ok(self.run(now, Input::Timer(TimerId { kind, seq })))
    }
    pub fn online(&mut self, now: f64) -> String {
        self.run(now, Input::Online)
    }
    pub fn network_changed(&mut self, now: f64) -> String {
        self.run(now, Input::NetworkChanged)
    }
    /// `source`: 0 visibilitychange, 1 pageshow (persisted).
    pub fn resumed(&mut self, now: f64, source: u32) -> Result<String, JsValue> {
        let source = [ResumeSource::VisibilityChange, ResumeSource::PageShow].get(source as usize).copied().ok_or_else(invalid)?;
        Ok(self.run(now, Input::Resumed(source)))
    }
    /// `source`: 0 open, 1 heartbeat, 2 visibilitychange, 3 focus, 4 blur,
    /// 5 pagehide, 6 recovery_requires_foreground.
    pub fn foreground(&mut self, now: f64, foreground: bool, source: u32) -> Result<String, JsValue> {
        let source = lifecycle_source(source).ok_or_else(invalid)?;
        Ok(self.run(now, Input::Foreground { foreground, source }))
    }
    pub fn data_activity(&mut self, now: f64) {
        self.machine.handle(now as u64, Input::DataActivity, &mut self.out);
    }

    /// Stable id for a message type, or `u32::MAX` once the table is full.
    pub fn intern(&mut self, message_type: &str) -> u32 {
        self.router.intern(message_type).unwrap_or(NOT_INTERNED)
    }

    /// Hot path for a frame whose type was interned and carries no error message.
    pub fn frame_id(&mut self, now: f64, socket: u32, type_id: u32) -> u32 {
        self.route_interned(now, socket, type_id, None)
    }

    /// `error` frame with an interned type: only the message crosses into wasm.
    pub fn frame_id_message(&mut self, now: f64, socket: u32, type_id: u32, error_message: &str) -> u32 {
        self.route_interned(now, socket, type_id, Some(error_message))
    }

    fn route_interned(&mut self, now: f64, socket: u32, type_id: u32, error_message: Option<&str>) -> u32 {
        let Some(message_type) = self.router.type_name(type_id) else { return UNKNOWN_TYPE_ID };
        let kind = Router::classify(message_type, error_message);
        let admitted = self.machine.frame(now as u64, SocketId(socket), kind, &mut self.out);
        let flag = if self.out.is_empty() { 0 } else { FRAME_COMMANDS };
        if !admitted {
            return STALE | flag;
        }
        match self.router.route_id(type_id) {
            Some(action) => action_code(action) | flag,
            None => UNKNOWN_TYPE_ID,
        }
    }

    /// Frame path for types beyond the intern table.
    pub fn frame(&mut self, now: f64, socket: u32, message_type: &str, error_message: Option<String>) -> u32 {
        self.route_frame(now, socket, message_type, error_message.as_deref())
    }

    fn route_frame(&mut self, now: f64, socket: u32, message_type: &str, error_message: Option<&str>) -> u32 {
        let kind = Router::classify(message_type, error_message);
        let admitted = self.machine.frame(now as u64, SocketId(socket), kind, &mut self.out);
        let flag = if self.out.is_empty() { 0 } else { FRAME_COMMANDS };
        if !admitted {
            return STALE | flag;
        }
        let action = action_code(self.router.route(message_type).action());
        action | flag
    }

    /// Handler ids of one type in dispatch order (refresh after `on`/`off`/`clear`).
    pub fn handlers(&self, message_type: &str) -> Vec<u32> {
        self.router.handlers(message_type).to_vec()
    }
    /// Commands produced by the last `frame()`.
    pub fn drain(&mut self) -> String {
        commands_json(&mut self.out)
    }

    /// Returns -1 for a duplicate, else the number of buffered payloads to replay.
    pub fn on(&mut self, message_type: &str, handler: u32) -> i32 {
        match self.router.on(message_type, handler) {
            Registered::Duplicate => -1,
            Registered::Added { replay } => replay as i32,
        }
    }
    pub fn off(&mut self, message_type: &str, handler: u32) -> bool {
        self.router.off(message_type, handler)
    }
    pub fn clear(&mut self, message_type: &str) -> bool {
        self.router.clear(message_type)
    }
    pub fn clear_all(&mut self) -> u32 {
        self.router.clear_all()
    }
    /// `family`: 0 app settings, 1 webhooks, 2 connected accounts, 3 highlights.
    pub fn declare_family(&mut self, family: u32) -> Result<(), JsValue> {
        self.router.declare(Family::from_code(family).ok_or_else(invalid)?);
        Ok(())
    }

    pub fn open_socket(&self) -> Option<u32> {
        self.machine.open_socket().map(|socket| socket.0)
    }
    pub fn status(&self) -> String {
        self.machine.status().as_str().to_owned()
    }
}

impl Default for BrowserWsLink {
    fn default() -> Self {
        Self::new()
    }
}

fn feedback_json(commands: &mut Vec<FeedbackCommand>) -> String {
    let values: Vec<Value> = commands
        .drain(..)
        .map(|command| match command {
            FeedbackCommand::Schedule { timer, delay_ms } => {
                json!({"op": "schedule", "timer": timer.kind.code(), "seq": timer.seq, "delay": delay_ms})
            }
            FeedbackCommand::Publish(feedback) => {
                json!({"op": "publish", "state": feedback.state.as_str(), "reason": feedback.reason.as_str()})
            }
        })
        .collect();
    Value::Array(values).to_string()
}

/// Delayed connection feedback (`connectionFeedbackStore` semantics).
#[wasm_bindgen]
pub struct BrowserConnectionFeedback {
    feedback: ConnectionFeedback,
    out: Vec<FeedbackCommand>,
}

#[wasm_bindgen]
impl BrowserConnectionFeedback {
    #[wasm_bindgen(constructor)]
    pub fn new() -> BrowserConnectionFeedback {
        BrowserConnectionFeedback { feedback: ConnectionFeedback::new(), out: Vec::new() }
    }
    pub fn update(&mut self, online: bool, authenticated: bool, checking_auth: bool, status: &str, syncing: bool) -> Result<String, JsValue> {
        let status = status_of(status).ok_or_else(invalid)?;
        self.feedback.update(FeedbackInputs { online, authenticated, checking_auth, status, syncing }, &mut self.out);
        Ok(feedback_json(&mut self.out))
    }
    pub fn timer(&mut self, kind: u32, seq: u32) -> Result<String, JsValue> {
        let kind = FeedbackTimerKind::from_code(kind).ok_or_else(invalid)?;
        self.feedback.timer(FeedbackTimer { kind, seq }, &mut self.out);
        Ok(feedback_json(&mut self.out))
    }
    pub fn resume(&mut self) -> String {
        self.feedback.resume(&mut self.out);
        feedback_json(&mut self.out)
    }
    pub fn server_updating(&mut self) -> String {
        self.feedback.server_updating(&mut self.out);
        feedback_json(&mut self.out)
    }
    pub fn reset(&mut self) -> String {
        self.feedback.reset(&mut self.out);
        feedback_json(&mut self.out)
    }
}

impl Default for BrowserConnectionFeedback {
    fn default() -> Self {
        Self::new()
    }
}
