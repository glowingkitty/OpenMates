//! Draft read and remote draft change events over the `actor_tests` fixture (real cache directory, unreachable API): invalid ids refused before any network, the cached draft restored offline only with the host's admission, and `DraftChanged` for a remote save or clear but never for an unchanged (echoed) draft.
use super::actor_tests::{CHAT, Fixture, Sink, fixture, persisted, session, snapshot};
use super::draft_flows::{DraftSnapshot, publish_draft_changes};
use super::*;
use crate::error::{Error, Result};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

/// A started fixture: cached index restored, session admitted.
async fn started() -> (Fixture, Sink) {
    let mut f = fixture();
    persisted(&mut f).await;
    let sink = Sink::default();
    start(&mut f.host, session(), &sink, &CancellationToken::new())
        .await
        .unwrap();
    (f, sink)
}

/// The fixture snapshot whose chat holds `markdown` as its draft at `draft_v`
/// (`None`: no draft ciphertext, version kept as the cleared floor).
fn with_draft(markdown: Option<&str>, draft_v: u64) -> Value {
    let mut snapshot = snapshot();
    let row = &mut snapshot["chats"][CHAT];
    row["draft_v"] = json!(draft_v);
    if let Some(markdown) = markdown {
        row["encrypted_draft_md"] =
            json!(crate::crypto::encrypt_combined(markdown, &[7; 32]).unwrap());
        row["encrypted_draft_preview"] = Value::Null;
    }
    snapshot
}

fn drafts_changed(sink: &Sink) -> Vec<(String, Option<DraftView>)> {
    sink.events()
        .into_iter()
        .filter_map(|event| match event {
            ViewEvent::DraftChanged { chat_id, draft } => Some((chat_id, draft)),
            _ => None,
        })
        .collect()
}

#[tokio::test]
async fn a_malformed_chat_id_is_invalid_without_events() {
    let (mut f, sink) = started().await;
    let before = sink.events().len();
    let result = draft(
        &mut f.host,
        "not-a-uuid".into(),
        &sink,
        &CancellationToken::new(),
    )
    .await;
    assert!(matches!(result, Err(Error::Invalid(_))), "{result:?}");
    assert_eq!(sink.events().len(), before, "a refusal publishes nothing");
}

#[tokio::test]
async fn offline_the_cached_draft_is_restored_and_none_without_one() {
    let (mut f, sink) = started().await;
    let cancel = CancellationToken::new();
    let none = draft(&mut f.host, CHAT.into(), &sink, &cancel).await;
    assert!(matches!(none, Ok(None)), "{none:?}");
    f.host
        .core
        .client_mut()
        .restore_ciphertext_snapshot(&with_draft(Some("Draft typed offline"), 3))
        .unwrap();
    let restored = draft(&mut f.host, CHAT.into(), &sink, &cancel)
        .await
        .unwrap()
        .expect("the cached draft");
    assert_eq!(restored.chat_id, CHAT);
    assert_eq!(restored.markdown, "Draft typed offline");
    assert_eq!(restored.draft_v, 3);
}

#[tokio::test]
async fn offline_without_the_hosts_cache_admission_the_read_fails_offline() {
    let (mut f, sink) = started().await;
    f.host
        .core
        .client_mut()
        .restore_ciphertext_snapshot(&with_draft(Some("Hidden draft"), 3))
        .unwrap();
    f.host.offline_allowed = false;
    let result = draft(&mut f.host, CHAT.into(), &sink, &CancellationToken::new()).await;
    assert!(matches!(result, Err(Error::Offline)), "{result:?}");
}

#[tokio::test]
async fn a_remote_save_publishes_the_new_draft_and_a_remote_clear_publishes_none() {
    let (mut f, sink) = started().await;
    let client = f.host.core.client_mut();

    // Another device saved a draft; a refresh applied its row.
    let before = DraftSnapshot::capture(client).unwrap();
    client
        .restore_ciphertext_snapshot(&with_draft(Some("Typed on the phone"), 4))
        .unwrap();
    publish_draft_changes(client, before, &sink).await.unwrap();
    let changed = drafts_changed(&sink);
    assert_eq!(changed.len(), 1);
    assert_eq!(changed[0].0, CHAT);
    let saved = changed[0].1.as_ref().expect("the remote draft");
    assert_eq!(saved.markdown, "Typed on the phone");
    assert_eq!(saved.draft_v, 4);

    // Another device cleared it.
    let before = DraftSnapshot::capture(client).unwrap();
    client
        .restore_ciphertext_snapshot(&with_draft(None, 5))
        .unwrap();
    publish_draft_changes(client, before, &sink).await.unwrap();
    let changed = drafts_changed(&sink);
    assert_eq!(changed.len(), 2);
    assert_eq!(changed[1], (CHAT.to_owned(), None));
}

#[tokio::test]
async fn an_unchanged_draft_such_as_the_echo_of_an_own_save_publishes_nothing() {
    let (mut f, sink) = started().await;
    let client = f.host.core.client_mut();
    let own = with_draft(Some("Saved here"), 6);
    client.restore_ciphertext_snapshot(&own).unwrap();
    let before = DraftSnapshot::capture(client).unwrap();
    // The server echoes the same version and ciphertext back.
    client.restore_ciphertext_snapshot(&own).unwrap();
    publish_draft_changes(client, before, &sink).await.unwrap();
    assert!(drafts_changed(&sink).is_empty());
}

/// `refresh_chats` over the unreachable API: the recovery hook applies the
/// remote rows, the list read then fails offline, so the draft events are
/// asserted through a feed-less refresh that reaches the list read.
async fn refreshed(f: &mut Fixture, sink: &Sink) -> Result<()> {
    refresh_chats(&mut f.host, sink, &CancellationToken::new()).await
}

#[tokio::test]
async fn refresh_chats_publishes_a_remote_draft_save_and_clear() {
    let (mut f, sink) = started().await;
    f.host.recovered_snapshot = Some(with_draft(Some("Typed on the phone"), 4));
    refreshed(&mut f, &sink).await.unwrap();
    let changed = drafts_changed(&sink);
    assert_eq!(changed.len(), 1);
    assert_eq!(changed[0].0, CHAT);
    assert_eq!(
        changed[0].1.as_ref().unwrap().markdown,
        "Typed on the phone"
    );

    f.host.recovered_snapshot = Some(with_draft(None, 5));
    refreshed(&mut f, &sink).await.unwrap();
    let changed = drafts_changed(&sink);
    assert_eq!(changed.len(), 2);
    assert_eq!(changed[1], (CHAT.to_owned(), None));
}

#[tokio::test]
async fn refresh_chats_and_boot_sync_publish_nothing_for_an_unchanged_draft() {
    let (mut f, sink) = started().await;
    // Encryption is randomized: the echo must be the very same ciphertext.
    let own = with_draft(Some("Saved here"), 6);
    f.host.recovered_snapshot = Some(own.clone());
    refreshed(&mut f, &sink).await.unwrap();
    assert_eq!(drafts_changed(&sink).len(), 1);
    f.host.recovered_snapshot = Some(own);
    refreshed(&mut f, &sink).await.unwrap();
    boot_sync(&mut f.host, &sink, &CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(drafts_changed(&sink).len(), 1);
}

#[tokio::test]
async fn boot_sync_publishes_a_remote_draft_save() {
    let (mut f, sink) = started().await;
    f.host.recovered_snapshot = Some(with_draft(Some("Typed on the phone"), 4));
    boot_sync(&mut f.host, &sink, &CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(drafts_changed(&sink).len(), 1);
}
