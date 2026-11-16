//! Frozen embed-key blob and short-URL vectors written by the web TypeScript
//! (ts_web_formats/generate_share_links.cjs), including legacy six-character short
//! links. Native replay of the same file the WASM binding tests read.
use base64::{Engine as _, engine::general_purpose::STANDARD};
use openmates_sdk::crypto::{
    share::{self, ShareKind},
    web_formats::{self, ShareKeyRefusal},
};
use serde_json::Value;

fn links() -> Value {
    serde_json::from_str(include_str!("crypto_fixtures/ts_share_links.json")).unwrap()
}
fn s(value: &Value) -> &str {
    value.as_str().unwrap()
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn ts_embed_key_blobs_decrypt_and_rust_blobs_round_trip() {
    let f = links();
    let (embed_id, now) = (s(&f["embed_id"]), f["generated_at"].as_i64().unwrap());
    for case in f["embed_blobs"].as_array().unwrap() {
        let password = case["password"].as_str();
        let duration = case["duration_seconds"].as_u64().unwrap();
        let expected = STANDARD.decode(s(&case["embed_key_b64"])).unwrap();
        let blob = s(&case["blob"]);
        let opened = web_formats::decrypt_embed_share_key_blob(embed_id, blob, now + 10, password)
            .unwrap()
            .unwrap();
        assert_eq!(opened.as_slice(), expected.as_slice(), "{}", s(&case["label"]));
        if password.is_some() {
            let refusal = web_formats::decrypt_embed_share_key_blob(embed_id, blob, now, None);
            assert_eq!(refusal.unwrap().unwrap_err(), ShareKeyRefusal::PasswordRequired);
        }
        if duration > 0 {
            let late = now + duration as i64 + 1;
            let refusal = web_formats::decrypt_embed_share_key_blob(embed_id, blob, late, password);
            assert_eq!(refusal.unwrap().unwrap_err(), ShareKeyRefusal::Expired);
        }
        // Rust writer output is read back by the same reader (TS reads it in the WASM test).
        let value = share::share_key_value(ShareKind::Embed, &expected);
        let rust_blob =
            share::generate_share_key_blob(ShareKind::Embed, embed_id, &value, duration, password, now)
                .unwrap();
        let back = web_formats::decrypt_embed_share_key_blob(embed_id, &rust_blob, now + 10, password)
            .unwrap()
            .unwrap();
        assert_eq!(back.as_slice(), expected.as_slice());
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn ts_short_urls_including_legacy_six_char_links_decrypt_and_round_trip() {
    let f = links();
    for case in f["short_urls"].as_array().unwrap() {
        let (token, key, url) = (s(&case["token"]), s(&case["short_key"]), s(&case["url"]));
        let label = s(&case["label"]);
        assert_eq!(
            web_formats::decrypt_short_url(s(&case["encrypted"]), token, key).unwrap(),
            url,
            "{label}"
        );
        assert!(web_formats::decrypt_short_url(s(&case["encrypted"]), token, "wrongKey").is_err());
        let rust_enc = share::encrypt_short_url(url, token, key).unwrap();
        assert_eq!(web_formats::decrypt_short_url(&rust_enc, token, key).unwrap(), url);
    }
}
