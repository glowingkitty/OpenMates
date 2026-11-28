//! Current and legacy personalized Daily Inspiration snapshot fixtures.

use super::*;

fn row(id: &str, content_type: &str, timestamp: f64) -> Value {
    json!({
        "inspiration_id": id,
        "content_type": content_type,
        "generated_at": timestamp,
        "phrase": "Explore a topic",
        "category": "science",
    })
}

fn select(records: &[Value], now: f64) -> Option<Vec<u8>> {
    select_personalized_snapshot(
        &serde_json::to_vec(&json!({ "inspirations": records })).unwrap(),
        now,
    )
}

// contract-test: supporting surface=gui.apple assertions=daily-inspiration.personalized-priority
#[test]
fn selects_three_videos_and_three_articles_from_a_legacy_snapshot() {
    let now = 1_800_000_000.0;
    let legacy = row("retired", "feature", now);
    let mut records = vec![legacy, row("expired", "video", now - SNAPSHOT_TTL_SECONDS)];
    for (id, kind) in [
        ("video-b", "video"),
        ("article-c", "wiki"),
        ("video-a", "video"),
        ("article-a", "wiki"),
        ("video-c", "video"),
        ("article-b", "wiki"),
    ] {
        records.push(row(id, kind, now - 1.0));
    }
    let snapshot = select(&records, now).unwrap();
    let body: Value = serde_json::from_slice(&snapshot).unwrap();
    let ids: Vec<_> = body["inspirations"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|record| record["inspiration_id"].as_str())
        .collect();
    assert_eq!(
        ids,
        [
            "article-a",
            "article-b",
            "article-c",
            "video-a",
            "video-b",
            "video-c"
        ]
    );

    records.pop();
    assert!(select(&records, now).is_none());
    records.push(row("article-a", "wiki", now - 1.0));
    assert!(select(&records, now).is_none());
}
