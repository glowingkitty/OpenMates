//! Replays the TS-generated bookmark and highlight vectors
//! (`bookmark_highlight_ts_vectors.json`, written from the real flag-off
//! messageBookmarks / handlersMessageHighlights / sendersMessageHighlights by
//! `generateBookmarkHighlightVectors.mjs`) against the shared Rust decisions that
//! the web `chatState` unit serves.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use super::bookmarks::{self, BookmarkToggle};
use super::highlights::{self, HighlightInbound, HighlightRecord};
use crate::{crypto, Error};
use serde_json::{json, Value};

fn vectors() -> Value {
    serde_json::from_str(include_str!("bookmark_highlight_ts_vectors.json"))
        .expect("committed vectors are valid JSON")
}

fn strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .expect("string array")
        .iter()
        .map(|item| item.as_str().expect("string").to_owned())
        .collect()
}

/// The web client's error text for a Rust refusal.
fn message(error: Error) -> String {
    match error {
        Error::Invalid(text) => text.to_owned(),
        other => panic!("unexpected error {other:?}"),
    }
}

fn assert_chats(index: &bookmarks::BookmarkIndex, expected: &Value, name: &str) {
    let expected = expected.as_array().expect("chats");
    let total: usize = expected
        .iter()
        .map(|pair| pair[1].as_array().expect("ids").len())
        .sum();
    assert_eq!(index.total(), total, "{name}: total");
    for pair in expected {
        let chat = pair[0].as_str().expect("chat id");
        assert_eq!(index.ids(chat), strings(&pair[1]), "{name}: {chat}");
    }
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn account_toggle_matches_the_typescript_service_for_every_vector() {
    for case in vectors()["account"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let legacy = strings(&case["legacy"]);
        let toggle = BookmarkToggle {
            chat_id: case["chat"].as_str().unwrap(),
            message_id: case["message"].as_str().unwrap(),
            legacy_ids: &legacy,
        };
        let result = bookmarks::toggle_account_plaintext(case["settings"].as_str(), &toggle);
        let out = &case["out"];
        if out["ok"] == json!(true) {
            let (plaintext, index) = result.unwrap_or_else(|e| panic!("{name}: {e:?}"));
            assert_eq!(Some(plaintext.as_str()), out["plaintext"].as_str(), "{name}");
            assert_chats(&index, &out["chats"], name);
        } else {
            let error = result.err().unwrap_or_else(|| panic!("{name}: expected refusal"));
            assert_eq!(Some(message(error).as_str()), out["error"].as_str(), "{name}");
        }
    }
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn account_decode_matches_the_typescript_service_for_every_vector() {
    for case in vectors()["decode"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let chat = case["chat"].as_str().unwrap();
        let out = &case["out"];
        // loadMessageBookmarks checks the chat identity before it reads any settings.
        let result = if bookmarks::valid_identity(chat) {
            bookmarks::decode_account_settings(case["settings"].as_str())
        } else {
            Err(Error::Invalid("Bookmark identity unavailable"))
        };
        if out["ok"] == json!(true) {
            assert_chats(&result.unwrap_or_else(|e| panic!("{name}: {e:?}")), &out["chats"], name);
        } else {
            let error = result.err().unwrap_or_else(|| panic!("{name}: expected refusal"));
            assert_eq!(Some(message(error).as_str()), out["error"].as_str(), "{name}");
        }
    }
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn device_toggle_matches_the_typescript_service_for_every_vector() {
    for case in vectors()["device"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let legacy = strings(&case["legacy"]);
        let toggle = BookmarkToggle {
            chat_id: case["chat"].as_str().unwrap(),
            message_id: case["message"].as_str().unwrap(),
            legacy_ids: &legacy,
        };
        // The unit's device op decodes the stored value, toggles and re-encodes.
        let result = bookmarks::decode_device_bookmarks(case["stored"].as_str())
            .and_then(|ids| bookmarks::toggle_local_bookmark(ids, &toggle))
            .map(|ids| bookmarks::encode_device_bookmarks(&ids));
        let out = &case["out"];
        if out["ok"] == json!(true) {
            assert_eq!(
                result.unwrap_or_else(|e| panic!("{name}: {e:?}")).as_str(),
                out["stored"].as_str().unwrap(),
                "{name}"
            );
        } else {
            let error = result.err().unwrap_or_else(|| panic!("{name}: expected refusal"));
            assert_eq!(Some(message(error).as_str()), out["error"].as_str(), "{name}");
        }
    }
}

/// A row without `key_version` and one with `key_version: null` are equivalent: the
/// record deserializes JSON null as absent and every reader uses `key_version ?? null`.
fn normalized(mut row: Value) -> Value {
    if row.get("key_version") == Some(&Value::Null) {
        row.as_object_mut().expect("row object").remove("key_version");
    }
    row
}

fn comparable(record: &HighlightRecord) -> Value {
    normalized(serde_json::from_str(&record.to_json()).expect("record JSON"))
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn inbound_highlights_match_the_typescript_handlers_for_every_vector() {
    let key = crypto::random_key();
    for case in vectors()["inbound"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut frame = case["frame"].clone();
        frame["encrypted_payload"] = if case["plain"].is_null() {
            json!("not-a-ciphertext")
        } else {
            json!(crypto::encrypt_combined(&case["plain"].to_string(), &key).unwrap())
        };
        let payload = frame.to_string();
        let cached = case["cached"]
            .is_object()
            .then(|| HighlightRecord::parse(&case["cached"].to_string()).unwrap());
        let inbound = if case["kind"] == json!("added") {
            highlights::decode_added(&payload, &key)
        } else {
            highlights::decode_updated(&payload, &key, cached.as_ref())
        }
        .unwrap_or_else(|e| panic!("{name}: {e:?}"));
        match (&inbound, &case["row"]) {
            (HighlightInbound::Store(record), row) if row.is_object() => {
                assert_eq!(comparable(record), normalized(row.clone()), "{name}");
            }
            (HighlightInbound::Drop(_), Value::Null) => {}
            (other, row) => panic!("{name}: Rust {other:?} but TypeScript stored {row}"),
        }
    }
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn outbound_highlights_match_the_typescript_senders_for_every_vector() {
    let key = crypto::random_key();
    for case in vectors()["outbound"].as_array().unwrap() {
        let operation = case["operation"].as_str().unwrap();
        let name = format!("{operation} {}", case["record"]["id"]);
        let write = match operation {
            "remove" => {
                let ids = strings(&case["ids"]);
                highlights::remove_highlight(&ids[0], &ids[1], &ids[2])
            }
            _ => {
                let record = HighlightRecord::parse(&case["record"].to_string()).unwrap();
                let now = case["nowSeconds"].as_u64().unwrap();
                if operation == "add" {
                    highlights::add_highlight(&record, &key).unwrap()
                } else {
                    highlights::update_highlight(&record, &key, now).unwrap()
                }
            }
        };
        assert_eq!(Some(write.frame_type), case["frameType"].as_str(), "{name}");
        let mut payload = write.payload.clone();
        if operation != "remove" {
            let encrypted = payload
                .as_object_mut()
                .unwrap()
                .remove("encrypted_payload")
                .expect("ciphertext");
            assert_eq!(
                Some(crypto::decrypt_combined(encrypted.as_str().unwrap(), &key).unwrap().as_str()),
                case["plaintext"].as_str(),
                "{name}: plaintext"
            );
            assert_eq!(
                comparable(write.record.as_ref().unwrap()),
                normalized(case["row"].clone()),
                "{name}: optimistic row"
            );
        }
        assert_eq!(payload, case["frame"], "{name}: frame");
    }
}
