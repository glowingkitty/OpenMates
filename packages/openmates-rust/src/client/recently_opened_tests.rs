//! Validated opened history input and protected local retention.
use super::*;

fn id(i: u128) -> String {
    uuid::Uuid::from_u128(i).hyphenated().to_string()
}

#[test]
fn recency_requires_distinct_canonical_ids_and_accepts_one_plus_ten() {
    let expected: Vec<_> = (1..=11).map(id).collect();
    assert_eq!(
        parse_ids(&json!(expected), STARTUP_HISTORY).unwrap(),
        expected
    );
    assert_eq!(
        parse_ids(
            &json!((1..=12).map(id).collect::<Vec<_>>()),
            STARTUP_HISTORY
        ),
        Err(Error::Protocol)
    );
    assert_eq!(
        parse_ids(&json!([id(1), id(1)]), STARTUP_HISTORY),
        Err(Error::Protocol)
    );
    assert_eq!(
        parse_ids(&json!(["/chat/new"]), STARTUP_HISTORY),
        Err(Error::Protocol)
    );
}

#[test]
fn native_retention_skips_offline_and_unsent_chats_without_deleting_headers() {
    let mut client = Client::new("https://example.invalid", None).unwrap();
    client.recently_opened.retained = (1..=100).map(id).collect();
    client.recently_opened.remote = vec![id(100)];
    let draft = id(99);
    let evicted = id(98);
    client.chats.insert(
        draft.clone(),
        json!({"id":draft,"encrypted_draft_md":"encrypted"}),
    );
    client.chats.insert(evicted.clone(), json!({"id":evicted}));
    for chat in [id(100), draft.clone(), evicted.clone()] {
        client.history.insert(chat, Vec::new());
    }
    client.retain_opened_history(&id(101), false);
    assert!(client.history.contains_key(&evicted));
    client.retain_opened_history(&id(101), true);
    assert_eq!(client.recently_opened.retained.len(), 100);
    assert!(client.history.contains_key(&id(100)));
    assert!(client.history.contains_key(&draft));
    assert!(!client.history.contains_key(&evicted));
    assert!(client.chats.contains_key(&evicted));
    let restored = RecentlyOpened::restore(client.recently_opened.snapshot().as_ref());
    assert_eq!(restored.retained, client.recently_opened.retained);
}

#[test]
fn confirmed_server_order_wins_over_a_persisted_offline_selection() {
    let mut client = Client::new("https://example.invalid", None).unwrap();
    let local = id(1);
    let other_device = id(2);
    client.recently_opened.pending = vec![local.clone()];
    assert_eq!(client.cached_startup_chat_id(), Some(local));
    client
        .recently_opened
        .reconcile_server(&[other_device.clone()]);
    assert_eq!(client.cached_startup_chat_id(), Some(other_device));
    assert!(client.recently_opened.pending.is_empty());
    assert!(client.recently_opened.remote_known);
}
