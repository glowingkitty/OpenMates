//! Marshalling checks for the voice-call clock and notice exports.
use super::*;

#[test]
fn clock_counts_while_unknown_and_dims_on_confirmed_idle() {
    let clock = VoiceCallActivityClockHandle::new();
    clock.tick(0.0);
    let unknown = clock.tick(3_000.0);
    assert_eq!(
        (
            unknown.active_elapsed_seconds,
            unknown.dimmed,
            unknown.activity_known
        ),
        (3, false, false)
    );
    let frame = r#"{"type":"billing_activity","call_id":"call-0001","input_listening":false,"processing":false}"#;
    assert!(!clock.apply_frame_json("other-call".into(), 4_000.0, frame.into()));
    assert!(clock.apply_frame_json("call-0001".into(), 4_000.0, frame.into()));
    let idle = clock.tick(9_000.0);
    assert_eq!(
        (
            idle.active_elapsed_seconds,
            idle.dimmed,
            idle.activity_known
        ),
        (4, true, true)
    );
}

#[test]
fn notice_round_trips_and_rejects_invalid_ids() {
    let built = build_voice_call_notice(
        VoiceCallNoticeAction::Ended,
        "call-0001".into(),
        1_792_067_580,
        120.7,
    )
    .expect("valid notice");
    assert_eq!(built.active_elapsed_seconds, Some(120));
    let parsed = voice_call_notice_from_message("system".into(), built.content_json.clone())
        .expect("notice");
    assert_eq!(parsed, built);
    assert!(voice_call_notice_from_message("user".into(), built.content_json).is_none());
    assert!(build_voice_call_notice(VoiceCallNoticeAction::Started, "bad".into(), 1, 0.0).is_err());
}
