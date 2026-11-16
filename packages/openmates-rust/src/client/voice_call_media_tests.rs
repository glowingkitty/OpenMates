//! Voice-call stage media: resolve and selection against vectors generated from the real web TypeScript.
use super::*;
use serde_json::Value;

fn fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/fixtures/ts_voice_call_media.json"
    ))
    .unwrap()
}

#[test]
fn stage_media_matches_web_resolver() {
    let f = fixture();
    let embeds: HashMap<String, VoiceCallMediaEmbed> =
        serde_json::from_value(f["embeds"].clone()).unwrap();
    for case in f["resolves"].as_array().unwrap() {
        let ids: Vec<String> = serde_json::from_value(case["candidate_ids"].clone()).unwrap();
        let expected: Vec<VoiceCallStageMedia> =
            serde_json::from_value(case["expected"].clone()).unwrap();
        assert_eq!(
            voice_call_stage_media(&ids, &embeds),
            expected,
            "{}",
            case["name"]
        );
    }
}

#[test]
fn stage_selection_matches_web_fresh_rule() {
    for case in fixture()["selections"].as_array().unwrap() {
        let ids: Vec<String> = serde_json::from_value(case["items"].clone()).unwrap();
        let items: Vec<VoiceCallStageMedia> = ids
            .iter()
            .map(|id| VoiceCallStageMedia {
                embed_id: id.clone(),
                kind: VoiceCallMediaKind::Image,
                variant: VoiceCallMediaVariant::Original,
                s3_key: String::new(),
                s3_base_url: String::new(),
                mime_type: None,
            })
            .collect();
        let presented: Vec<String> = serde_json::from_value(case["presented"].clone()).unwrap();
        let expected: VoiceCallStageSelection =
            serde_json::from_value(case["expected"].clone()).unwrap();
        let got = voice_call_stage_selection(&items, &presented, case["displayed"].as_str());
        assert_eq!(got, expected, "{case}");
    }
}
