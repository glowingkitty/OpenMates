//! Voice-call activity clock: unknown counts, idle dims, playback ignored, resume, frame parsing.
use super::*;

const LIVE: BillingActivity = BillingActivity {
    input_listening: true,
    processing: false,
};
const IDLE: BillingActivity = BillingActivity {
    input_listening: false,
    processing: false,
};

#[test]
fn voice_call_unknown_activity_counts() {
    let mut c = VoiceCallActivityClock::new();
    c.tick(0.0);
    let s = c.tick(5_900.0);
    assert_eq!(
        s,
        VoiceCallActivitySnapshot {
            active_elapsed_seconds: 5,
            dimmed: false,
            activity_known: false
        }
    );
}

#[test]
fn voice_call_known_idle_dims_and_stops() {
    let mut c = VoiceCallActivityClock::new();
    c.tick(0.0);
    c.apply_billing_activity(3_000.0, IDLE);
    let s = c.tick(10_000.0);
    assert_eq!(
        (s.active_elapsed_seconds, s.dimmed, s.activity_known),
        (3, true, true)
    );
}

#[test]
fn voice_call_playback_only_neither_advances_nor_dims() {
    // Playback is not an input: the server says idle, so nothing counts and
    // no extra flag exists for the shell to pass in.
    let mut c = VoiceCallActivityClock::new();
    c.tick(0.0);
    c.apply_billing_activity(1_000.0, IDLE);
    assert_eq!(c.tick(4_000.0).active_elapsed_seconds, 1);
    c.apply_billing_activity(5_000.0, LIVE);
    assert!(!c.tick(5_000.0).dimmed);
}

#[test]
fn voice_call_resume_continues_from_accumulated() {
    let mut c = VoiceCallActivityClock::new();
    c.tick(0.0);
    c.apply_billing_activity(2_000.0, IDLE);
    c.apply_billing_activity(
        8_000.0,
        BillingActivity {
            input_listening: false,
            processing: true,
        },
    );
    let s = c.tick(11_000.0);
    assert_eq!((s.active_elapsed_seconds, s.dimmed), (5, false));
}

#[test]
fn voice_call_backwards_time_is_ignored() {
    let mut c = VoiceCallActivityClock::new();
    c.tick(10_000.0);
    assert_eq!(c.tick(9_000.0).active_elapsed_seconds, 0);
}

#[test]
fn voice_call_frame_parse() {
    let ok = r#"{"type":"billing_activity","call_id":"c1","input_listening":true,"processing":false,"extra":1}"#;
    assert_eq!(
        parse_billing_activity(ok),
        Some(BillingActivityFrame {
            call_id: "c1".into(),
            activity: LIVE
        })
    );
    for bad in [
        r#"{"type":"billing_activity","call_id":"c1","input_listening":true}"#,
        r#"{"type":"billing_activity","call_id":"c1","input_listening":"yes","processing":false}"#,
        r#"{"type":"usage","call_id":"c1","input_listening":true,"processing":true}"#,
        r#"{"type":"billing_activity","input_listening":true,"processing":true}"#,
        "not json",
    ] {
        assert_eq!(parse_billing_activity(bad), None, "{bad}");
    }
}
