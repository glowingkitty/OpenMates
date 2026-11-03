//! Deterministic fake clock and fake sockets for link machine tests.
use super::*;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) enum SocketState {
    Opening,
    Open,
    Closed { code: u16, reason: String },
}

#[derive(Debug)]
pub(super) struct FakeSocket {
    pub id: SocketId,
    pub state: SocketState,
    pub sent: Vec<String>,
}

pub(super) struct Harness {
    pub machine: LinkMachine,
    pub now: u64,
    timers: Vec<(u64, TimerId)>,
    pub log: Vec<Command>,
    pub sockets: Vec<FakeSocket>,
    pub refreshes: Vec<(u32, RefreshReason)>,
}

impl Harness {
    pub fn new() -> Self {
        Self::with(LinkConfig::default())
    }

    pub fn with(config: LinkConfig) -> Self {
        Self { machine: LinkMachine::new(config), now: 0, timers: Vec::new(), log: Vec::new(), sockets: Vec::new(), refreshes: Vec::new() }
    }

    pub fn feed(&mut self, input: Input<'_>) -> Vec<Command> {
        let mut out = Vec::new();
        self.machine.handle(self.now, input, &mut out);
        self.apply(&out);
        out
    }

    pub fn frame(&mut self, socket: SocketId, kind: FrameKind<'_>) -> (bool, Vec<Command>) {
        let mut out = Vec::new();
        let admitted = self.machine.frame(self.now, socket, kind, &mut out);
        self.apply(&out);
        (admitted, out)
    }

    fn apply(&mut self, commands: &[Command]) {
        for command in commands {
            match command {
                Command::Schedule { timer, delay_ms } => self.timers.push((self.now + delay_ms, *timer)),
                Command::Open { socket } => {
                    self.sockets.push(FakeSocket { id: *socket, state: SocketState::Opening, sent: Vec::new() })
                }
                Command::Close { socket, code, reason } => {
                    self.socket_mut(*socket).state = SocketState::Closed { code: *code, reason: reason.clone() }
                }
                Command::SendPing { socket } => self.socket_mut(*socket).sent.push("ping".into()),
                Command::SendLifecycle { socket, foreground, source } => {
                    let sent = format!("lifecycle:{}:{}", source.as_str(), foreground);
                    self.socket_mut(*socket).sent.push(sent)
                }
                Command::RefreshSession { refresh, reason } => self.refreshes.push((*refresh, *reason)),
                Command::Status { .. } | Command::Emit(_) | Command::Settle(_) => {}
            }
        }
        self.log.extend_from_slice(commands);
    }

    fn socket_mut(&mut self, id: SocketId) -> &mut FakeSocket {
        self.sockets.iter_mut().find(|socket| socket.id == id).expect("command for an unknown socket")
    }

    pub fn socket(&self, id: SocketId) -> &FakeSocket {
        self.sockets.iter().find(|socket| socket.id == id).expect("unknown socket")
    }

    /// Advance the fake clock, firing due timers in due order.
    pub fn advance(&mut self, ms: u64) -> Vec<Command> {
        let target = self.now + ms;
        let mut fired = Vec::new();
        loop {
            let next = self
                .timers
                .iter()
                .enumerate()
                .filter(|(_, (due, _))| *due <= target)
                .min_by_key(|(index, (due, _))| (*due, *index))
                .map(|(index, _)| index);
            let Some(index) = next else { break };
            let (due, timer) = self.timers.remove(index);
            self.now = due;
            fired.extend(self.feed(Input::Timer(timer)));
        }
        self.now = target;
        fired
    }

    pub fn sign_in(&mut self, has_token: bool) -> Vec<Command> {
        self.feed(Input::Session { authenticated: true, logging_out: false, has_token })
    }

    pub fn last(&self) -> SocketId {
        self.sockets.last().expect("no socket opened").id
    }

    pub fn open_last(&mut self) -> Vec<Command> {
        let socket = self.last();
        self.socket_mut(socket).state = SocketState::Open;
        self.feed(Input::Opened(socket))
    }

    pub fn close_last(&mut self, code: u16, reason: &str, was_clean: bool) -> Vec<Command> {
        let socket = self.last();
        self.socket_mut(socket).state = SocketState::Closed { code, reason: reason.to_owned() };
        self.feed(Input::Closed { socket, code, reason, was_clean })
    }

    pub fn answer_refresh(&mut self, outcome: RefreshOutcome, has_token: bool) -> Vec<Command> {
        let (refresh, _) = *self.refreshes.last().expect("no refresh requested");
        self.feed(Input::Refreshed { refresh, outcome, has_token })
    }

    /// Signed in with a stored token and an open socket.
    pub fn connected() -> Self {
        let mut harness = Self::new();
        harness.sign_in(true);
        harness.open_last();
        harness
    }

    /// Fail the current attempt: answer its pending refresh, then close the
    /// socket cleanly before it opens.
    pub fn fail_attempt(&mut self) -> Vec<Command> {
        let mut out = Vec::new();
        if self.opening().is_none() {
            out.extend(self.answer_refresh(RefreshOutcome::Ready, true));
        }
        out.extend(self.close_last(1000, "", true));
        out
    }

    pub fn opening(&self) -> Option<SocketId> {
        self.sockets.iter().rev().find(|socket| socket.state == SocketState::Opening).map(|socket| socket.id)
    }
}

pub(super) fn statuses(commands: &[Command]) -> Vec<LinkStatus> {
    commands.iter().filter_map(|command| match command {
        Command::Status { status, .. } => Some(*status),
        _ => None,
    }).collect()
}

pub(super) fn events(commands: &[Command]) -> Vec<LinkEvent> {
    commands.iter().filter_map(|command| match command {
        Command::Emit(event) => Some(event.clone()),
        _ => None,
    }).collect()
}

pub(super) fn delays(commands: &[Command], kind: TimerKind) -> Vec<u64> {
    commands.iter().filter_map(|command| match command {
        Command::Schedule { timer, delay_ms } if timer.kind == kind => Some(*delay_ms),
        _ => None,
    }).collect()
}

pub(super) fn opens(commands: &[Command]) -> usize {
    commands.iter().filter(|command| matches!(command, Command::Open { .. })).count()
}

pub(super) fn refresh_reasons(commands: &[Command]) -> Vec<RefreshReason> {
    commands.iter().filter_map(|command| match command {
        Command::RefreshSession { reason, .. } => Some(*reason),
        _ => None,
    }).collect()
}
