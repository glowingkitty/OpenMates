use super::*;
use crate::crypto::{self, master::MasterCapability};

fn toggle<'a>(chat: &'a str, message: &'a str, legacy: &'a [String]) -> BookmarkToggle<'a> {
    BookmarkToggle {
        chat_id: chat,
        message_id: message,
        legacy_ids: legacy,
    }
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn account_toggle_preserves_every_other_setting_verbatim_and_in_js_order() {
    let plaintext = r#"{"theme":"dark","ratio":1.0,"big":12345678901234567890,"7":true,"message_bookmarks":{"version":1,"chats":{"c1":["m1","m1","m2"]}},"tail":null}"#;
    let (next, index) = toggle_account_plaintext(Some(plaintext), &toggle("c2", "x", &[])).unwrap();
    assert_eq!(
        next,
        r#"{"7":true,"theme":"dark","ratio":1.0,"big":12345678901234567890,"message_bookmarks":{"version":1,"chats":{"c1":["m1","m2"],"c2":["x"]}},"tail":null}"#
    );
    assert_eq!(index.ids("c1"), vec!["m1", "m2"]);
    // Removing via a legacy alias drops every alias and the empty chat entry.
    let legacy = vec!["m2".to_owned()];
    let (after, index) =
        toggle_account_plaintext(Some(&next), &toggle("c1", "new-id", &legacy)).unwrap();
    assert_eq!(index.ids("c1"), vec!["m1"]);
    let (after, index) = toggle_account_plaintext(Some(&after), &toggle("c1", "m1", &[])).unwrap();
    assert!(index.ids("c1").is_empty());
    assert!(after.contains(r#""chats":{"c2":["x"]}"#));
    // A new settings key is appended after the existing ones.
    let (fresh, _) = toggle_account_plaintext(Some(r#"{"a":1}"#), &toggle("c", "m", &[])).unwrap();
    assert_eq!(
        fresh,
        r#"{"a":1,"message_bookmarks":{"version":1,"chats":{"c":["m"]}}}"#
    );
    let (empty, _) = toggle_account_plaintext(None, &toggle("c", "m", &[])).unwrap();
    assert_eq!(
        empty,
        r#"{"message_bookmarks":{"version":1,"chats":{"c":["m"]}}}"#
    );
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn corrupt_or_unsupported_settings_and_identities_refuse_without_a_write() {
    for bad in [
        "[]",
        "null",
        "not json",
        r#"{"message_bookmarks":null}"#,
        r#"{"message_bookmarks":{"version":2,"chats":{}}}"#,
        r#"{"message_bookmarks":{"version":1,"chats":[]}}"#,
        r#"{"message_bookmarks":{"version":1}}"#,
        r#"{"message_bookmarks":{"version":1,"chats":{"c":"m"}}}"#,
        r#"{"message_bookmarks":{"version":1,"chats":{"c":[1]}}}"#,
        r#"{"message_bookmarks":{"version":1,"chats":{"":["m"]}}}"#,
    ] {
        assert_eq!(
            decode_account_settings(Some(bad)).unwrap_err(),
            Error::Invalid("Bookmark settings unavailable"),
            "{bad}"
        );
    }
    assert!(
        decode_account_settings(Some(r#"{"message_bookmarks":{"version":1.0,"chats":{}}}"#))
            .is_ok()
    );
    let control = "a\u{1f}b";
    let long = "x".repeat(257);
    let three = vec!["a".to_owned(), "b".to_owned(), "c".to_owned()];
    for request in [
        toggle(control, "m", &[]),
        toggle("c", &long, &[]),
        toggle("c", "m", &three),
    ] {
        assert_eq!(
            toggle_account_plaintext(None, &request).unwrap_err(),
            Error::Invalid("Bookmark identity unavailable")
        );
    }
    // 256 UTF-16 units is the bound; astral characters count twice.
    assert!(valid_identity(&"🔖".repeat(128)) && !valid_identity(&"🔖".repeat(129)));
}

#[test]
fn the_ten_thousand_bookmark_limit_matches_the_web_client() {
    let ids: Vec<String> = (0..MAX_BOOKMARKS).map(|i| format!("m{i}")).collect();
    let full = format!(
        r#"{{"message_bookmarks":{{"version":1,"chats":{{"c":{}}}}}}}"#,
        serde_json::to_string(&ids).unwrap()
    );
    assert_eq!(
        decode_account_settings(Some(&full)).unwrap().total(),
        MAX_BOOKMARKS
    );
    assert_eq!(
        toggle_account_plaintext(Some(&full), &toggle("d", "m", &[])).unwrap_err(),
        Error::Invalid("Bookmark limit reached")
    );
    assert_eq!(
        toggle_local_bookmark(ids.clone(), &toggle("c", "extra", &[])).unwrap_err(),
        Error::Invalid("Bookmark limit reached")
    );
    let mut over = ids.clone();
    over.push("m0".into());
    let duplicated = format!(
        r#"{{"message_bookmarks":{{"version":1,"chats":{{"c":{}}}}}}}"#,
        serde_json::to_string(&over).unwrap()
    );
    assert!(
        decode_account_settings(Some(&duplicated)).is_err(),
        "raw count before dedupe is bounded"
    );
}

#[test]
fn device_values_round_trip_and_reject_corruption() {
    assert!(decode_device_bookmarks(None).unwrap().is_empty());
    assert!(decode_device_bookmarks(Some("")).unwrap().is_empty());
    assert_eq!(
        decode_device_bookmarks(Some(r#"["a","b","a"]"#)).unwrap(),
        vec!["a", "b"]
    );
    for bad in ["{", "{}", r#"["a",2]"#, r#"[""]"#] {
        assert!(decode_device_bookmarks(Some(bad)).is_err(), "{bad}");
    }
    let ids = toggle_local_bookmark(vec!["a".into()], &toggle("c", "b", &[])).unwrap();
    assert_eq!(encode_device_bookmarks(&ids), r#"["a","b"]"#);
    assert_eq!(
        toggle_local_bookmark(ids, &toggle("c", "a", &[])).unwrap(),
        vec!["b"]
    );
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[tokio::test]
async fn account_bookmarks_encrypt_with_the_master_key_in_browser_format_d() {
    let key = crypto::random_key();
    let master = MasterCapability::from_browser_raw(key.clone());
    let existing =
        crate::crypto::server_fields::encrypt_text(r#"{"theme":"dark"}"#, &key, &[]).unwrap();
    let write = toggle_account_bookmark(&master, Some(&existing), &toggle("c", "m", &[]))
        .await
        .unwrap();
    let raw = base64::Engine::decode(
        &base64::engine::general_purpose::STANDARD,
        &write.encrypted_settings,
    )
    .unwrap();
    let plaintext = crypto::decrypt_combined(&write.encrypted_settings, &key).unwrap();
    assert_eq!(
        raw.len(),
        12 + plaintext.len() + 16,
        "Format D is IV || ciphertext || tag, never OM framed"
    );
    assert_eq!(
        plaintext,
        r#"{"theme":"dark","message_bookmarks":{"version":1,"chats":{"c":["m"]}}}"#
    );
    assert_eq!(
        read_account_bookmarks(&master, Some(&write.encrypted_settings))
            .await
            .unwrap()
            .ids("c"),
        vec!["m"]
    );
    let other = MasterCapability::from_browser_raw(crypto::random_key());
    assert_eq!(
        read_account_bookmarks(&other, Some(&write.encrypted_settings))
            .await
            .unwrap_err(),
        Error::Invalid("Bookmark settings unavailable")
    );
    assert!(read_account_bookmarks(&master, None).await.unwrap().total() == 0);
}
