//! The Apple search binding returns exactly what the core search returns for
//! the TypeScript vectors (`web_search_query_ts_vectors.json`).
use crate::view_search::*;
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!(
        "../../openmates-rust/src/web_search_query_ts_vectors.json"
    ))
    .unwrap()
}

fn opt(value: &Value) -> Option<String> {
    value.as_str().map(str::to_owned)
}

fn engine_and_chats(vectors: &Value) -> (CoreChatSearchIndex, Vec<SearchChatRecord>) {
    let engine = CoreChatSearchIndex::new();
    for (chat_id, entries) in vectors["ingests"].as_object().unwrap() {
        let entries = entries
            .as_array()
            .unwrap()
            .iter()
            .map(|item| {
                let meta = SearchEntryMetaRecord {
                    source_label: opt(&item["embedSourceLabel"]),
                    embed_id: opt(&item["embedId"]),
                    embed_type: opt(&item["embedType"]),
                    title: opt(&item["embedTitle"]),
                    subtitle: opt(&item["embedSubtitle"]),
                    app_id: opt(&item["embedAppId"]),
                    skill_id: opt(&item["embedSkillId"]),
                    focus_id: opt(&item["embedFocusId"]),
                    focus_mode_name: opt(&item["embedFocusModeName"]),
                };
                SearchIndexEntryRecord {
                    message_id: item["messageId"].as_str().unwrap().into(),
                    content: item["content"].as_str().unwrap().into(),
                    created_at: item["createdAt"].as_f64().unwrap(),
                    meta: (meta != SearchEntryMetaRecord::default()).then_some(meta),
                }
            })
            .collect();
        assert!(engine.ingest_chat(chat_id.clone(), entries).is_empty());
    }
    let chats = vectors["chats"]
        .as_array()
        .unwrap()
        .iter()
        .map(|chat| SearchChatRecord {
            chat_id: chat["chatId"].as_str().unwrap().into(),
            search_messages: chat["messages"].as_bool().unwrap(),
            title: opt(&chat["title"]),
            active_focus_id: opt(&chat["activeFocusId"]),
            summary: opt(&chat["summary"]),
            tags: chat["tags"].as_array().map(|tags| {
                tags.iter()
                    .map(|t| t.as_str().unwrap().to_owned())
                    .collect()
            }),
            draft: opt(&chat["draft"]),
            last_edited: chat["lastEdited"].as_f64().unwrap(),
        })
        .collect();
    (engine, chats)
}

#[test]
fn query_matches_typescript_case() {
    let vectors = vectors();
    let (engine, chats) = engine_and_chats(&vectors);
    let case = &vectors["cases"][0];
    let result = engine.query(SearchRequestRecord {
        query: case["query"].as_str().unwrap().into(),
        include_embeds: case["includeEmbeds"].as_bool().unwrap(),
        authenticated: case["isAuthenticated"].as_bool().unwrap(),
        admin: case["isAdmin"].as_bool().unwrap(),
        chats,
        catalog: Vec::new(),
    });
    let expected = case["expected"]["chats"].as_array().unwrap();
    assert_eq!(result.chats.len(), expected.len());
    for (got, want) in result.chats.iter().zip(expected) {
        assert_eq!(got.chat_id, want["chatId"].as_str().unwrap());
        let ranges: Vec<(u32, u32)> = want["titleMatchRanges"]
            .as_array()
            .map(|r| {
                r.iter()
                    .map(|r| {
                        (
                            r["start"].as_u64().unwrap() as u32,
                            r["length"].as_u64().unwrap() as u32,
                        )
                    })
                    .collect()
            })
            .unwrap_or_default();
        let got_ranges: Vec<(u32, u32)> = got
            .title_ranges
            .iter()
            .map(|r| (r.start, r.length))
            .collect();
        assert_eq!(got_ranges, ranges);
        let want_messages = want["messageSnippets"].as_array().unwrap();
        assert_eq!(got.messages.len(), want_messages.len());
        for (g, w) in got.messages.iter().zip(want_messages) {
            assert_eq!(g.message_id, w["messageId"].as_str().unwrap());
            assert_eq!(g.match_start as u64, w["matchStart"].as_u64().unwrap());
            assert_eq!(g.match_length as u64, w["matchLength"].as_u64().unwrap());
        }
    }
}

#[test]
fn clear_drops_chats_and_in_chat_search_finds_ranges() {
    let vectors = vectors();
    let (engine, _) = engine_and_chats(&vectors);
    assert!(engine.chat_count() > 0);
    engine.remove_chat("demo-1".into());
    engine.clear();
    assert_eq!(engine.chat_count(), 0);
    let matches = search_in_chat_messages(
        "Needle".into(),
        vec![
            InChatSearchMessageRecord {
                message_id: "a".into(),
                text: "a needle and a NEEDLE".into(),
            },
            InChatSearchMessageRecord {
                message_id: "b".into(),
                text: "nothing".into(),
            },
        ],
    );
    assert_eq!(matches.len(), 1);
    assert_eq!(matches[0].message_id, "a");
    assert_eq!(
        matches[0].ranges,
        vec![
            SearchMatchRangeRecord {
                start: 2,
                length: 6
            },
            SearchMatchRangeRecord {
                start: 15,
                length: 6
            }
        ]
    );
    assert_eq!(search_find_match_ranges("abc".into(), "".into()), vec![]);
}
