use super::*;

fn texts(content: &str) -> Vec<(&'static str, String)> {
    project_assistant_speech(content, "en")
        .into_iter()
        .map(|s| (s.kind, s.speakable_text))
        .collect()
}

#[test]
fn projection_matches_the_shared_markdown_rules() {
    let content = concat!(
        "# Title\n\nSee [the docs](https://x.test/a) and `code` at https://x.test/b .\n\n",
        "| a | b |\n| - | - |\n\n```python\nprint(1)\n```\n\n",
        "```json\n{\"type\":\"app_skill_use\",\"app_id\":\"news\",\"skill_id\":\"search\"}\n```\n\n",
        "```json\n{\"type\":\"app_skill_use\",\"app_id\":\"news\",\"skill_id\":\"search\"}\n```\n\n",
        "{\"embed_id\":\"x\"}\n\n**Bold** _closing_ ~~done~~ words",
    );
    assert_eq!(
        texts(content),
        vec![
            ("prose_paragraph", "Title".to_owned()),
            ("prose_paragraph", "See the docs and at.".to_owned()),
            ("table_summary", "A table is available.".to_owned()),
            ("code_summary", "A code example is available.".to_owned()),
            ("embed_summary", "I used the News Search skill.".to_owned()),
            ("embed_summary", "Structured data is available.".to_owned()),
            // Only leading emphasis markers and underscore/tilde runs are removed.
            ("prose_paragraph", "Bold** closing done words".to_owned()),
        ]
    );
    let german = project_assistant_speech("```rust\nfn x() {}\n```", "de-DE");
    assert_eq!(german[0].speakable_text, "Ein Codebeispiel ist verfügbar.");
    assert!(project_assistant_speech("   \n\n`only code`", "en").is_empty());
}

#[test]
fn projection_bounds_segment_count_and_length() {
    let many = (0..30)
        .map(|i| format!("Paragraph {i}."))
        .collect::<Vec<_>>()
        .join("\n\n");
    let segments = project_assistant_speech(&many, "en");
    assert_eq!(segments.len(), MAX_SPEECH_SEGMENTS);
    assert_eq!(segments[19].sequence, 19);
    let sentence = "Word word word word word word word word word. ";
    let long = sentence.repeat(100);
    let chunks = split_long_paragraph(long.trim());
    assert!(chunks.len() > 1);
    assert!(
        chunks
            .iter()
            .all(|c| units(c) <= MAX_SEGMENT_UNITS && c.ends_with('.'))
    );
    let unbroken = "x".repeat(4500);
    let chunks = split_long_paragraph(&unbroken);
    assert_eq!(
        chunks.iter().map(|c| c.len()).collect::<Vec<_>>(),
        vec![2000, 2000, 500]
    );
}

#[test]
fn request_segments_carry_sha256_of_the_speakable_text() {
    let segments = speech_request_segments("Hello world.");
    assert_eq!(
        segments,
        vec![
            json!({"source_version":1,"sequence":0,"kind":"prose_paragraph",
            "source_hash":sha256("Hello world."),"speakable_text":"Hello world."})
        ]
    );
}

fn message(id: &str, role: &str, content: &str) -> Message {
    Message {
        id: id.into(),
        role: role.into(),
        content: content.into(),
        ..Message::default()
    }
}

#[test]
fn selection_requires_exactly_one_mode_and_an_assistant_target() {
    let messages = vec![
        message("u-1", "user", "Question?"),
        message("a-1", "assistant", "Answer."),
        message("a-2", "assistant", "`only code`"),
        message("a-3", "assistant", "Second answer."),
    ];
    let select = |message_id: Option<&str>, all: bool| {
        select_assistant_messages(
            &messages,
            &SpeechSelection {
                message_id: message_id.map(Into::into),
                all,
            },
        )
        .map(|rows| rows.iter().map(|m| m.id.clone()).collect::<Vec<_>>())
    };
    assert_eq!(select(None, true).unwrap(), vec!["a-1", "a-3"]);
    assert_eq!(select(Some("a-3"), false).unwrap(), vec!["a-3"]);
    assert_eq!(select(Some("a-"), false).unwrap(), vec!["a-1"]);
    for (id, all) in [(None, false), (Some("a-1"), true), (Some(""), false)] {
        assert_eq!(
            select(id, all).unwrap_err(),
            Error::Invalid("Select exactly one of --message <id> or --all.")
        );
    }
    assert_eq!(
        select(Some("u-1"), false).unwrap_err(),
        Error::Invalid("The selected message is not an eligible assistant message.")
    );
}

#[test]
fn tracker_counts_generated_reused_and_failed_segments() {
    let mut tracker = SpeechStatusTracker::new("m-1");
    assert_eq!(
        tracker
            .consume(&json!({"status":"queued","message_id":"m-1","segment_id":"early"}))
            .unwrap(),
        None
    );
    let accepted = json!({"status":"accepted","segments":[
        {"segment_id":"s1","status":"queued"},
        {"segment_id":"s2","status":"ready"},
        {"segment_id":"s3","status":"error","error":"provider_failed"}]});
    assert_eq!(tracker.consume(&accepted).unwrap(), None);
    // Unrelated messages and unknown segments are ignored.
    assert_eq!(
        tracker
            .consume(&json!({"message_id":"other","segment_id":"s9","status":"ready"}))
            .unwrap(),
        None
    );
    // A later standalone error frame rejects the request, as in the npm CLI;
    // failures are counted only from the accepted segment list.
    let mut rejected = SpeechStatusTracker::new("m-1");
    assert_eq!(rejected.consume(&accepted).unwrap(), None);
    assert_eq!(
        rejected
            .consume(&json!({"message_id":"m-1","segment_id":"s1","status":"error","error":"rate_limited"}))
            .unwrap_err(),
        Error::Invalid("rate_limited")
    );
    let done = tracker
        .consume(&json!({"segment_id":"s1","status":"ready"}))
        .unwrap();
    assert_eq!(
        done,
        Some(SpeechMessageResult {
            generated: 1,
            reused: 1,
            failed: 1,
            charged: 1
        })
    );
    let summary = summarize_assistant_speech(
        "c-1",
        &[
            done.unwrap(),
            SpeechMessageResult {
                generated: 2,
                charged: 2,
                ..Default::default()
            },
        ],
    );
    assert_eq!(
        serde_json::to_value(summary).unwrap(),
        json!({"chat_id":"c-1","messages":2,"generated_segments":3,"reused_segments":1,"failed_segments":1,"charged_segments":3})
    );
}

#[test]
fn tracker_rejects_server_errors_and_empty_acceptance() {
    let mut tracker = SpeechStatusTracker::new("m");
    assert_eq!(
        tracker
            .consume(&json!({"status":"error","error":"forbidden"}))
            .unwrap_err(),
        Error::Invalid("forbidden")
    );
    assert_eq!(
        tracker
            .consume(&json!({"status":"error","error":"provider secret detail"}))
            .unwrap_err(),
        Error::Invalid("Assistant speech request failed.")
    );
    assert_eq!(
        tracker
            .consume(&json!({"status":"accepted","segments":[]}))
            .unwrap_err(),
        Error::Invalid("No canonical speech segments are available for this historical message.")
    );
}
