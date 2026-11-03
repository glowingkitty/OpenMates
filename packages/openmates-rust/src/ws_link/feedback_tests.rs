//! Connection feedback timing (port of connectionFeedbackStore.ts).
use super::*;

struct Clock {
    feedback: ConnectionFeedback,
    now: u64,
    timers: Vec<(u64, FeedbackTimer)>,
    published: Vec<Feedback>,
}

impl Clock {
    fn new() -> Self {
        Self { feedback: ConnectionFeedback::new(), now: 0, timers: Vec::new(), published: Vec::new() }
    }
    fn apply(&mut self, out: Vec<FeedbackCommand>) {
        for command in out {
            match command {
                FeedbackCommand::Schedule { timer, delay_ms } => self.timers.push((self.now + delay_ms, timer)),
                FeedbackCommand::Publish(feedback) => self.published.push(feedback),
            }
        }
    }
    fn update(&mut self, online: bool, authenticated: bool, checking_auth: bool, status: LinkStatus, syncing: bool) {
        let mut out = Vec::new();
        self.feedback.update(FeedbackInputs { online, authenticated, checking_auth, status, syncing }, &mut out);
        self.apply(out);
    }
    fn advance(&mut self, ms: u64) {
        let target = self.now + ms;
        loop {
            let next = self.timers.iter().enumerate().filter(|(_, (due, _))| *due <= target).min_by_key(|(i, (due, _))| (*due, *i)).map(|(i, _)| i);
            let Some(index) = next else { break };
            let (due, timer) = self.timers.remove(index);
            self.now = due;
            let mut out = Vec::new();
            self.feedback.timer(timer, &mut out);
            self.apply(out);
        }
        self.now = target;
    }
    fn state(&self) -> FeedbackState {
        self.feedback.current().state
    }
}

#[test]
fn reconnect_feedback_appears_after_three_seconds_and_clears_on_connect() {
    let mut c = Clock::new();
    c.update(true, true, false, LinkStatus::Reconnecting, false);
    c.advance(2_999);
    assert_eq!(c.state(), FeedbackState::Idle);
    c.advance(1);
    assert_eq!(c.state(), FeedbackState::Reconnecting);
    c.update(true, true, false, LinkStatus::Connected, false);
    assert_eq!(c.state(), FeedbackState::Idle);
}

#[test]
fn brief_disconnect_never_shows_feedback() {
    let mut c = Clock::new();
    c.update(true, true, false, LinkStatus::Reconnecting, false);
    c.advance(2_000);
    c.update(true, true, false, LinkStatus::Connected, false);
    c.advance(10_000);
    assert!(c.published.is_empty());
}

#[test]
fn offline_wins_and_reports_its_reason() {
    let mut c = Clock::new();
    c.update(false, true, false, LinkStatus::Reconnecting, false);
    assert_eq!(c.feedback.current(), Feedback { state: FeedbackState::Offline, reason: FeedbackReason::Offline });
}

#[test]
fn syncing_feedback_waits_600_ms() {
    let mut c = Clock::new();
    c.update(true, true, false, LinkStatus::Connected, true);
    c.advance(599);
    assert_eq!(c.state(), FeedbackState::Idle);
    c.advance(1);
    assert_eq!(c.state(), FeedbackState::Syncing);
    c.update(true, true, false, LinkStatus::Connected, false);
    assert_eq!(c.state(), FeedbackState::Idle);
}

#[test]
fn stuck_auth_check_shows_reconnecting_after_twelve_seconds() {
    let mut c = Clock::new();
    c.update(true, true, true, LinkStatus::Connected, false);
    c.advance(11_999);
    assert_eq!(c.state(), FeedbackState::Idle);
    c.advance(1);
    assert_eq!(c.state(), FeedbackState::Reconnecting);
}

#[test]
fn resume_grace_hides_reconnect_for_ten_seconds_then_shows_if_still_down() {
    let mut c = Clock::new();
    c.update(true, true, false, LinkStatus::Reconnecting, false);
    let mut out = Vec::new();
    c.feedback.resume(&mut out);
    c.apply(out);
    c.advance(9_999);
    assert_eq!(c.state(), FeedbackState::Idle, "the pre-resume reconnect timer is disarmed");
    c.advance(1);
    assert_eq!(c.state(), FeedbackState::Reconnecting);
}

#[test]
fn server_updating_reason_lasts_until_connected() {
    let mut c = Clock::new();
    c.update(true, true, false, LinkStatus::Reconnecting, false);
    let mut out = Vec::new();
    c.feedback.server_updating(&mut out);
    c.apply(out);
    c.advance(3_000);
    assert_eq!(c.feedback.current(), Feedback { state: FeedbackState::Reconnecting, reason: FeedbackReason::ServerUpdating });
    c.update(true, true, false, LinkStatus::Connected, false);
    assert_eq!(c.feedback.current().reason, FeedbackReason::Reconnecting);
}

#[test]
fn reset_returns_to_idle_and_disarms_timers() {
    let mut c = Clock::new();
    c.update(true, true, false, LinkStatus::Reconnecting, false);
    let mut out = Vec::new();
    c.feedback.reset(&mut out);
    c.apply(out);
    c.advance(60_000);
    assert_eq!(c.state(), FeedbackState::Idle);
    assert!(c.published.is_empty());
}
