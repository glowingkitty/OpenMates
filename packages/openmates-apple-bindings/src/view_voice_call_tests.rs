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

#[test]
fn stage_media_selects_finished_image_and_prefers_fresh_item() {
    let embed = VoiceCallStageEmbedInput {
        embed_id: "e1".into(),
        app_id: None,
        skill_id: None,
        embed_type: Some("generated_image".into()),
        status: Some("finished".into()),
        decryption_failed: false,
        decryption_pending: false,
        content_json: r#"{"s3_base_url":"https://s3.example.org","aes_key":"k","files":{"original":{"s3_key":"k/e1"}}}"#.into(),
    };
    let items = voice_call_stage_media_items(vec!["e1".into(), "gone".into()], vec![embed]);
    assert_eq!(items.len(), 1);
    assert_eq!(items[0].variant, VoiceCallStageMediaVariant::Original);
    let fresh = voice_call_stage_media_selection(vec!["e1".into()], vec![], None);
    assert_eq!((fresh.displayed_index, fresh.fresh), (Some(0), true));
    let kept =
        voice_call_stage_media_selection(vec!["e1".into()], vec!["e1".into()], Some("zz".into()));
    assert_eq!((kept.displayed_index, kept.fresh), (Some(0), false));
}
