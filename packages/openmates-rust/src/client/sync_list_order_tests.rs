// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted,cli.output.actionable-readable
//! Actual Client/encryption/cache-policy units; managed execution remains required.
use super::*;
const IDS: [&str; 7] = [
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
    "55555555-5555-4555-8555-555555555555",
    "66666666-6666-4666-8666-666666666666",
    "77777777-7777-4777-8777-777777777777",
];
fn client() -> Client {
    let mut session = super::super::sdk_boundary_tests::session();
    session.master_key = zeroize::Zeroizing::new([7; 32]);
    let mut client = Client::new("https://api.example.org", Some(session)).unwrap();
    client.user = json!({"id":"synthetic-owner"});
    client
}
fn row(id: &str, title: &str, timestamp: Option<Value>) -> Value {
    let mut row = json!({"id":id,
        "encrypted_chat_key":crypto::encrypt_bytes(&[8;32],&[7;32]).unwrap(),
        "encrypted_title":crypto::encrypt_combined(title,&[8;32]).unwrap(),
        // Different timestamps must not be used as an accidental fallback.
        "updated_at":999999,"created_at":999999});
    if let Some(timestamp) = timestamp {
        row["last_edited_overall_timestamp"] = timestamp;
    }
    row
}
fn ids(items: &[Item]) -> Vec<&str> {
    items.iter().map(|item| item.id.as_str()).collect()
}
fn clock(tick: u64) -> CacheClockEvidence {
    CacheClockEvidence::from_platform("synthetic-order-boot".into(), tick, tick).unwrap()
}
#[test]
fn decrypted_foreground_cached_and_admitted_warm_pages_share_recency_without_receipt_renewal() {
    let mut c = client();
    let mut older = row(IDS[0], "Pinned but older", Some(json!(100)));
    older["pinned"] = json!(true);
    let draft = json!({"id":IDS[2],"last_edited_overall_timestamp":200,
        "encrypted_draft_md":crypto::encrypt_combined("Private full draft",&[7;32]).unwrap(),
        "encrypted_draft_preview":crypto::encrypt_combined("Private draft preview",&[7;32]).unwrap()});
    // Reverse insertion makes neither insertion nor UUID order a valid result.
    for value in [
        row(IDS[6], "Negative timestamp", Some(json!(-1))),
        row(IDS[5], "Null timestamp", Some(Value::Null)),
        row(IDS[4], "String timestamp", Some(json!("999999"))),
        row(IDS[3], "Newest", Some(json!(300))),
        draft,
        row(IDS[1], "Missing timestamp", None),
        older,
    ] {
        c.chats
            .insert(required(&value, "id").unwrap().to_owned(), value);
    }
    c.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| Some(clock(1_100)))));
    c.record_complete_chat_list_at(Some(&clock(1_000)));
    let ciphertext = c.ciphertext_snapshot();
    let expected = [IDS[3], IDS[2], IDS[0], IDS[1], IDS[4], IDS[5], IDS[6]];
    let foreground = c.render_chat_inventory().unwrap();
    let cached = c.cached_chat_items().unwrap();
    let warm = c.try_cached_default_chat_list(false).unwrap().unwrap();
    assert_eq!(ids(&foreground), expected);
    assert_eq!(ids(&cached), expected);
    assert_eq!(ids(&warm), expected);
    // The native list pager consumes this exact SDK order using skip/take.
    assert_eq!(ids(&foreground[2..4]), [IDS[0], IDS[1]]);
    assert_eq!(foreground[0].title, "Newest");
    assert_eq!(foreground[1].title, "Private draft preview");
    assert_eq!(foreground[1].status, "draft");
    assert_eq!(foreground[2].fields["pinned"], true);
    assert_eq!(
        serde_json::to_value(&foreground).unwrap(),
        serde_json::to_value(&cached).unwrap()
    );
    assert_eq!(
        serde_json::to_value(&foreground).unwrap(),
        serde_json::to_value(&warm).unwrap()
    );
    assert_eq!(c.ciphertext_snapshot(), ciphertext);
    assert!(!ciphertext.to_string().contains("Private draft preview"));
    assert!(!ciphertext.to_string().contains("Newest"));
    assert!(c.try_cached_default_chat_list(true).unwrap().is_none());
}
#[test]
fn equal_numeric_zero_signed_zero_missing_and_nonnumber_keep_existing_uuid_ties() {
    let mut c = client();
    for value in [
        row(IDS[3], "Nonnumeric", Some(json!("1000"))),
        row(IDS[2], "Absent", None),
        row(IDS[1], "Negative zero", Some(json!(-0.0))),
        row(IDS[0], "Positive zero", Some(json!(0.0))),
    ] {
        c.chats
            .insert(required(&value, "id").unwrap().to_owned(), value);
    }
    assert_eq!(ids(&c.render_chat_inventory().unwrap()), IDS[..4]);
    assert_eq!(ids(&c.cached_chat_items().unwrap()), IDS[..4]);
}
#[test]
fn locked_row_keeps_recency_position_without_new_key_fallback_or_offline_permission() {
    let mut c = client();
    c.chats
        .insert(IDS[0].into(), row(IDS[0], "Readable", Some(json!(100))));
    let mut locked = row(IDS[3], "Must stay encrypted", Some(json!(900)));
    locked["chat_visibility"] = json!("direct");
    locked["participant_user_hashes"] = json!(["unavailable-one", "unavailable-two"]);
    c.chats.insert(IDS[3].into(), locked);
    let rendered = c.render_chat_inventory().unwrap();
    assert_eq!(ids(&rendered), [IDS[3], IDS[0]]);
    assert_eq!(rendered[0].title, "Locked chat");
    assert_eq!(rendered[0].status, "locked");
    assert_eq!(rendered[1].title, "Readable");
    // The offline formatter's existing denial remains distinct from foreground
    // locked rendering; sharing order must not introduce a decryption fallback.
    assert!(matches!(c.cached_chat_items(), Err(Error::Forbidden)));
    c.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| Some(clock(1_100)))));
    c.record_complete_chat_list_at(Some(&clock(1_000)));
    assert!(c.try_cached_default_chat_list(false).unwrap().is_none());
}
