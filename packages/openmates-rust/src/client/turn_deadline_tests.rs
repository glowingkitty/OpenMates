//! A turn that keeps receiving frames outlives its idle limit; a silent one does not.
use super::*;

// contract-test: supporting surface=cli assertions=projects.agentic.long-turn-stays-online
#[test]
fn received_frames_extend_the_turn_past_its_idle_limit() {
    let start = Instant::now();
    let idle = Duration::from_secs(600);
    let mut deadline = TurnDeadline::start(start, idle);
    assert_eq!(deadline.at(), start + idle);
    // A coding turn still streaming after 14 minutes is not Offline.
    deadline.on_frame(start + Duration::from_secs(840));
    assert_eq!(deadline.at(), start + Duration::from_secs(840) + idle);
}

// contract-test: supporting surface=cli assertions=projects.agentic.long-turn-stays-online
#[test]
fn silent_turn_keeps_its_idle_deadline() {
    let start = Instant::now();
    let deadline = TurnDeadline::start(start, Duration::from_secs(2));
    assert_eq!(deadline.at(), start + Duration::from_secs(2));
}

// contract-test: supporting surface=cli assertions=projects.agentic.long-turn-stays-online
#[test]
fn frames_never_move_the_deadline_past_one_day() {
    let start = Instant::now();
    let mut deadline = TurnDeadline::start(start, Duration::from_secs(600));
    deadline.on_frame(start + TURN_MAX_DURATION - Duration::from_secs(1));
    assert_eq!(deadline.at(), start + TURN_MAX_DURATION);
}
