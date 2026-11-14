//! Ports of the web `videoTimelineModel` normalisation cases.
use super::*;
use serde_json::json;

fn sample() -> Value {
    json!({
        "made_by": "composed", "width": 1280,
        "timeline": {
            "fps": 30,
            "tracks": [{"id": "main", "name": "Scenes", "kind": "visual", "parts": [
                {"id": "b", "label": "Second", "from": 90, "duration_in_frames": 60},
                {"id": "a", "from": 0, "duration_in_frames": 90, "kind": "scene"},
                {"id": "bad", "from": -1, "duration_in_frames": 10},
                {"id": "zero", "from": 0, "duration_in_frames": 0}
            ]}],
            "audio": [
                {"id": "z", "kind": "bogus", "from": 0, "durationInFrames": 5},
                {"id": "m", "kind": "music", "label": "Bed", "from": 0, "durationInFrames": 200}
            ]
        }
    })
}

#[test]
fn sorts_parts_drops_invalid_and_extends_to_audio() {
    let tl = normalize_timeline(&sample()).expect("timeline");
    let ids: Vec<&str> = tl.tracks[0].parts.iter().map(|p| p.id.as_str()).collect();
    assert_eq!(ids, ["a", "b"]);
    assert_eq!(tl.tracks[0].parts[0].label, "a");
    assert_eq!(tl.duration_in_frames, 200);
    assert_eq!(tl.made_by, VideoMadeBy::Composed);
    assert_eq!(tl.width, 1280);
    assert_eq!(tl.audio.len(), 1);
    assert_eq!(tl.audio[0].kind, VideoAudioKind::Music);
}

#[test]
fn missing_or_empty_timeline_is_none() {
    assert!(normalize_timeline(&json!({})).is_none());
    assert!(normalize_timeline(&json!({"timeline": {"tracks": []}})).is_none());
    assert!(
        normalize_timeline(&json!({"timeline": {"tracks": [{"id": "t", "parts": []}]}})).is_none()
    );
}

#[test]
fn defaults_fps_kinds_and_generative_made_by() {
    let tl = normalize_timeline(&json!({"timeline": {"tracks": [
        {"id": "t", "kind": "weird", "parts": [
            {"id": "p", "from": 0, "duration_in_frames": 10.4, "kind": "image"}]}
    ]}}))
    .expect("timeline");
    assert_eq!(tl.fps, DEFAULT_FPS);
    assert_eq!(tl.tracks[0].kind, VideoTrackKind::Visual);
    assert_eq!(tl.tracks[0].name, "t");
    assert_eq!(tl.tracks[0].parts[0].kind, VideoPartKind::Image);
    assert_eq!(tl.tracks[0].parts[0].duration_in_frames, 10);
    assert_eq!(tl.made_by, VideoMadeBy::Generative);
}

#[test]
fn resolve_synthesizes_one_clip_from_stored_or_loaded_length() {
    assert!(resolve_timeline(&json!({}), 0.0, "Clip").is_none());
    let tl = resolve_timeline(&json!({"duration_seconds": 8.0}), 3.0, "Clip").expect("clip");
    assert_eq!(tl.duration_in_frames, 240);
    assert_eq!(tl.tracks[0].parts.len(), 1);
    assert_eq!(tl.tracks[0].parts[0].label, "Clip");
    assert_eq!(tl.made_by, VideoMadeBy::Generative);
    let loaded = resolve_timeline(&json!({"width": 640}), 2.0, "Clip").expect("clip");
    assert_eq!((loaded.duration_in_frames, loaded.width), (60, 640));
}
