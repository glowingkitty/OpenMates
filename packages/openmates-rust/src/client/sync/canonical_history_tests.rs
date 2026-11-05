// contract-test-file: tooling
// Actual canonical accumulator/decoder with synthetic ciphertext; authored UNRUN.
use super::*;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const OTHER: &str = "11111111-1111-4111-8111-111111111111";
fn row(id: &str, content: &str) -> Value {
    json!({"client_message_id":id,"chat_id":CHAT,"role":"assistant","encrypted_content":crypto::encrypt_combined(content,&[8;32]).unwrap()})
}
fn page(rows: Vec<Value>, more: bool, cursor: i64) -> Value {
    json!({"messages":rows,"has_more_before":more,"start_cursor":{"created_at":cursor,"message_id":format!("cursor-{cursor}")}})
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn canonical_hundred_row_pages_keep_full_order_and_exact_ciphertext() {
    let mut history = CanonicalHistory::new(CHAT);
    let newest = (0..100)
        .map(|i| row(&format!("new-{i}"), &format!("new body {i}")))
        .collect::<Vec<_>>();
    let first = history
        .decode_page(page(newest.clone(), true, 100), &[8; 32])
        .unwrap();
    assert!(first.first());
    assert!(first.more());
    assert_eq!(first.decoded().len(), 100);
    assert!(!history.append_page(first).unwrap());
    let oldest = (0..100)
        .map(|i| row(&format!("old-{i}"), &format!("old body {i}")))
        .collect::<Vec<_>>();
    let last = history
        .decode_page(page(oldest.clone(), false, 0), &[8; 32])
        .unwrap();
    assert!(!last.first());
    assert!(history.append_page(last).unwrap());
    let (messages, encrypted, explicit) = history.into_parts().unwrap();
    assert!(explicit);
    assert_eq!(messages.len(), 200);
    assert_eq!(messages[0].id, "old-0");
    assert_eq!(messages[100].id, "new-0");
    assert_eq!(messages[199].content, "new body 99");
    assert_eq!(encrypted, [oldest, newest].concat());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn actual_identity_decoder_rejects_foreign_chat_and_cross_page_duplicate_alias() {
    let mut history = CanonicalHistory::new(CHAT);
    let first = history
        .decode_page(page(vec![row("same", "body")], true, 10), &[8; 32])
        .unwrap();
    history.append_page(first).unwrap();
    let duplicate = json!({"message_id":"same","chat_id":CHAT,"role":"assistant","encrypted_content":crypto::encrypt_combined("other",&[8;32]).unwrap()});
    assert!(
        history
            .decode_page(page(vec![duplicate], false, 0), &[8; 32])
            .is_err()
    );
    let mut foreign = row("foreign", "must not escape");
    foreign["chat_id"] = json!(OTHER);
    assert!(
        CanonicalHistory::new(CHAT)
            .decode_page(page(vec![foreign], false, 0), &[8; 32])
            .is_err()
    );
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[test]
fn repeated_cursor_and_one_hundred_page_limit_never_become_partial_success() {
    let mut repeated = CanonicalHistory::new(CHAT);
    let first = repeated
        .decode_page(page(vec![], true, 1), &[8; 32])
        .unwrap();
    repeated.append_page(first).unwrap();
    let same = repeated
        .decode_page(page(vec![], true, 1), &[8; 32])
        .unwrap();
    assert!(repeated.append_page(same).is_err());
    let mut bounded = CanonicalHistory::new(CHAT);
    for i in 0..100 {
        let part = bounded
            .decode_page(page(vec![], true, i), &[8; 32])
            .unwrap();
        assert!(!bounded.append_page(part).unwrap());
    }
    assert!(bounded.before_request().is_err());
    assert!(bounded.into_parts().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only
#[test]
fn legacy_missing_flag_does_not_mint_explicit_terminal_and_pii_uses_all_actual_rows() {
    let mut history = CanonicalHistory::new(CHAT);
    let mut first = row("mapping", "[EMAIL_1]");
    first["encrypted_pii_mappings"] = json!(crypto::encrypt_combined("[]", &[8; 32]).unwrap());
    let part = history
        .decode_page(json!({"messages":[first]}), &[8; 32])
        .unwrap();
    assert!(history.append_page(part).unwrap());
    let (messages, rows, explicit) = history.into_parts().unwrap();
    assert!(!explicit);
    let mut chat = Plain::new(Chat {
        id: CHAT.into(),
        messages: messages.into_inner(),
        ..Chat::default()
    });
    super::super::restore_chat_tokens_from_rows(&mut chat, &[8; 32], &rows).unwrap();
    assert_eq!(chat.messages[0].content, "[EMAIL_1]");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn item_projection_retains_summary_integrity_checks_and_ciphertext_errors() {
    let value = json!({"id":CHAT,"encrypted_title":crypto::encrypt_combined("title",&[8;32]).unwrap(),"encrypted_chat_summary":"invalid ciphertext"});
    assert!(saved_item(&value, &[8; 32]).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only
#[test]
fn all_one_hundred_nonempty_canonical_pages_keep_exact_order_and_ciphertext() {
    let mut history = CanonicalHistory::new(CHAT);
    let mut original_pages = Vec::new();
    for page_index in 0..100 {
        let rows = (0..100)
            .map(|offset| {
                row(
                    &format!("page-{page_index}-row-{offset}"),
                    &format!("body page {page_index}, row {offset}"),
                )
            })
            .collect::<Vec<_>>();
        let decoded = history
            .decode_page(page(rows.clone(), page_index < 99, 100 - page_index), &[8; 32])
            .unwrap();
        assert_eq!(history.append_page(decoded).unwrap(), page_index == 99);
        original_pages.push(rows);
    }
    let (messages, encrypted, explicit) = history.into_parts().unwrap();
    let expected_ciphertext = original_pages.into_iter().rev().flatten().collect::<Vec<_>>();
    assert!(explicit);
    assert_eq!(messages.len(), 10_000);
    assert_eq!(encrypted, expected_ciphertext);
    for (index, message) in messages.iter().enumerate() {
        let page_index = 99 - index / 100;
        let offset = index % 100;
        assert_eq!(message.id, format!("page-{page_index}-row-{offset}"));
        assert_eq!(message.content, format!("body page {page_index}, row {offset}"));
    }
}
