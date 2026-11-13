//! Stored embed rows written by the TypeScript client
//! (tests/crypto_fixtures/ts_embed_writes.json) open to the plaintext the TS
//! reader (`getFromSeparateFields` + `decryptWithEmbedKey`) returns.
use super::super::keys::{self, NonceSource};
use super::*;
use crate::crypto::aead::{AeadProvider, NativeAead};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};

fn fixture() -> Value {
    serde_json::from_str(include_str!("../../tests/crypto_fixtures/ts_embed_writes.json")).unwrap()
}
fn raw_key(value: &Value) -> [u8; 32] {
    STANDARD.decode(value.as_str().unwrap()).unwrap().try_into().unwrap()
}
async fn open(raw: &[u8; 32], row: &Value) -> OpenedEmbedFields {
    let key = NativeAead.import_key(raw).await.unwrap();
    open_row_fields(key.as_ref(), row).await.unwrap()
}
struct Fixed(u8);
impl NonceSource for Fixed {
    fn next_nonce(&mut self) -> Result<[u8; 12]> {
        self.0 = self.0.wrapping_add(1);
        Ok([self.0; 12])
    }
}
fn seal(text: &str, raw: &[u8; 32]) -> String {
    keys::encrypt_text(text, raw, None, &mut Fixed(7)).unwrap()
}

#[tokio::test]
async fn typescript_written_rows_open_to_their_plaintext() {
    let f = fixture();
    for case in f["finalized"].as_array().unwrap() {
        let raw = raw_key(&case["embed_key_b64"]);
        let row = &case["expected"]["local_entry"];
        let input = &case["input"];
        let opened = open(&raw, row).await;
        assert!(!opened.content_failed);
        assert_eq!(opened.content.as_deref(), input["content"].as_str());
        assert_eq!(opened.embed_type.as_deref(), input["type"].as_str());
        let preview = input["text_preview"].as_str().filter(|text| !text.is_empty());
        if row.get("encrypted_text_preview").is_some() {
            assert_eq!(opened.text_preview.as_deref(), preview);
        } else {
            assert_eq!(opened.text_preview, None);
        }
    }
}

#[tokio::test]
async fn wrong_key_fails_content_only_and_absent_fields_stay_absent() {
    let f = fixture();
    let case = &f["finalized"][0];
    let mut wrong = raw_key(&case["embed_key_b64"]);
    wrong[0] ^= 1;
    let opened = open(&wrong, &case["expected"]["local_entry"]).await;
    assert_eq!(opened, OpenedEmbedFields { content_failed: true, ..Default::default() });
    let empty = open(&wrong, &json!({"embed_id": "x"})).await;
    assert_eq!(empty, OpenedEmbedFields::default());
    // An empty encrypted_content string is not a present field (TS truthiness).
    let blank = open(&wrong, &json!({"encrypted_content": ""})).await;
    assert!(!blank.content_failed);
}

#[tokio::test]
async fn text_decoder_and_trim_semantics_match_the_browser_reader() {
    let raw = [9u8; 32];
    let row = json!({
        "encrypted_content": format!("  {}\n", seal("\u{feff}type: code", &raw)),
        "encrypted_type": seal("", &raw),
        "encrypted_text_preview": "not base64 !",
    });
    let opened = open(&raw, &row).await;
    assert_eq!(opened.content.as_deref(), Some("type: code"));
    assert!(!opened.content_failed);
    // Empty type plaintext is ignored; undecodable preview is skipped.
    assert_eq!(opened.embed_type, None);
    assert_eq!(opened.text_preview, None);
    // Only content is trimmed, as in getFromSeparateFields: an untrimmed type is
    // padded before whitespace removal (base64ToUint8Array + atob) and fails.
    let padded_type = json!({ "encrypted_type": format!(" {}", seal("code", &raw)) });
    assert_eq!(open(&raw, &padded_type).await.embed_type, None);
    let clean_type = json!({ "encrypted_type": seal("code", &raw) });
    assert_eq!(open(&raw, &clean_type).await.embed_type.as_deref(), Some("code"));
    let short = json!({ "encrypted_content": STANDARD.encode([1u8; 20]) });
    assert!(open(&raw, &short).await.content_failed);
    let empty_plain = json!({ "encrypted_content": seal("", &raw) });
    assert!(open(&raw, &empty_plain).await.content_failed);
}

#[tokio::test]
async fn non_object_rows_are_refused() {
    let key = NativeAead.import_key(&[1u8; 32]).await.unwrap();
    assert!(open_row_fields(key.as_ref(), &json!("row")).await.is_err());
}
