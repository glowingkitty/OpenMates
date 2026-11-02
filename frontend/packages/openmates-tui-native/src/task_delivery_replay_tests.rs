// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity,chats.messages.client-encrypted
use super::*;
use openmates_sdk::work::TaskMutationKind;
const THREAD: &str = "11111111-1111-4111-8111-111111111111";
const OTHER_THREAD: &str = "22222222-2222-4222-8222-222222222222";
fn directory() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().unwrap()
}
fn context(team: Option<&str>) -> String {
    serde_json::to_string(&("https://api.example.test", team)).unwrap()
}
fn journal(store: RuntimeStore, team: Option<&str>) -> Journal {
    Journal::new(
        store,
        "owner".into(),
        context(team),
        Zeroizing::new([42; 32]),
    )
}
fn delivery(id: char) -> TaskDelivery {
    TaskDelivery {
        protocol_version: 1,
        delivery_id: id.to_string().repeat(64),
        task_id: "00000000-0000-4000-8000-000000000001".into(),
        team_id: None,
        scope: "SDK-authenticated-opaque-scope".into(),
        kind: TaskMutationKind::Create,
        input: serde_json::json!({"encrypted_title":"fixed-original-ciphertext","version":1}),
        expected_owner_hash: None,
        creator: false,
        actor_assignee: false,
    }
}
fn codex(thread: &str, as_assignee: bool) -> TaskCaller {
    TaskCaller {
        codex_thread_id: Some(thread.into()),
        as_assignee,
    }
}
fn assert_caller(actual: &TaskCaller, thread: Option<&str>, as_assignee: bool) {
    assert_eq!(actual.codex_thread_id.as_deref(), thread);
    assert_eq!(actual.as_assignee, as_assignee);
}

#[tokio::test]
async fn replay_restart_keeps_original_caller_ciphertext_ids_and_fifo_not_clock_or_id_order() {
    let directory = directory();
    let path = directory.path().to_path_buf();
    let first = delivery('f');
    let second = delivery('0');
    {
        let store = RuntimeStore::new(Some(path.clone()), true).await.unwrap();
        let j = journal(store, None);
        j.insert_for_caller(first.clone(), "first".into(), &codex(THREAD, false))
            .await
            .unwrap();
        j.insert_for_caller(second.clone(), "second".into(), &TaskCaller::default())
            .await
            .unwrap();
        // A clock rollback affects display metadata, never authoritative order.
        j.access(|mut state| {
            state
                .deliveries
                .get_mut(&"f".repeat(64))
                .unwrap()
                .replay
                .as_mut()
                .unwrap()
                .queued_at_ms = 200;
            state
                .deliveries
                .get_mut(&"0".repeat(64))
                .unwrap()
                .replay
                .as_mut()
                .unwrap()
                .queued_at_ms = 100;
            Ok((Some(state), ()))
        })
        .await
        .unwrap();
        let sent = j.begin_replay(&first.delivery_id, "first").await.unwrap();
        assert!(!sent.uncertain);
        assert_caller(
            &sent.replay.unwrap().task_caller().unwrap(),
            Some(THREAD),
            false,
        );
    }
    let store = RuntimeStore::new(Some(path), true).await.unwrap();
    let j = journal(store, None);
    let pending = j.pending_replay().await.unwrap();
    assert!(pending.quarantined.is_empty());
    assert_eq!(
        pending
            .ordered
            .iter()
            .map(|row| row.delivery.delivery_id.clone())
            .collect::<Vec<_>>(),
        [first.delivery_id.clone(), second.delivery_id.clone()]
    );
    assert_eq!(pending.ordered[0].replay_admission().unwrap().sequence(), 1);
    assert_eq!(pending.ordered[1].replay_admission().unwrap().sequence(), 2);
    assert!(matches!(
        j.begin_replay(&second.delivery_id, "second").await,
        Err(Error::Conflict)
    ));
    let resumed = j.begin_replay(&first.delivery_id, "first").await.unwrap();
    assert!(resumed.uncertain);
    assert_eq!(
        serde_json::to_value(resumed.delivery).unwrap(),
        serde_json::to_value(&first).unwrap()
    );
    assert_caller(
        &resumed.replay.unwrap().task_caller().unwrap(),
        Some(THREAD),
        false,
    );
    let receipt = serde_json::json!({"task_id":first.task_id,"version":1});
    j.acknowledge(&first.delivery_id, "first", receipt.clone())
        .await
        .unwrap();
    let completed = j.begin_replay(&first.delivery_id, "first").await.unwrap();
    assert_eq!(completed.completed, Some(receipt));
    let next = j.begin_replay(&second.delivery_id, "second").await.unwrap();
    assert!(!next.uncertain);
    assert_caller(&next.replay.unwrap().task_caller().unwrap(), None, false);
    assert_eq!(
        serde_json::to_value(next.delivery).unwrap(),
        serde_json::to_value(second).unwrap()
    );
}

#[tokio::test]
async fn sequence_is_one_atomic_account_api_record_under_concurrent_preparations() {
    let directory = directory();
    let store = RuntimeStore::new(Some(directory.path().into()), true)
        .await
        .unwrap();
    let j = std::sync::Arc::new(journal(store, None));
    let mut workers = vec![];
    for i in 0..8 {
        let j = j.clone();
        workers.push(tokio::spawn(async move {
            let mut d = delivery('a');
            d.delivery_id = format!("{i:064x}");
            j.insert_for_caller(d, format!("intent-{i}"), &TaskCaller::default())
                .await
                .unwrap()
                .replay_admission()
                .unwrap()
                .sequence()
        }));
    }
    let mut sequences = vec![];
    for worker in workers {
        sequences.push(worker.await.unwrap());
    }
    sequences.sort_unstable();
    assert_eq!(sequences, (1u64..=8).collect::<Vec<_>>());
    assert_eq!(j.pending_replay().await.unwrap().ordered.len(), 8);
    // A dropped, never-polled preparation reserves neither an ID nor a sequence.
    let caller = TaskCaller::default();
    let never_polled = j.insert_for_caller(delivery('b'), "not-admitted".into(), &caller);
    drop(never_polled);
    assert!(
        j.lookup(&"b".repeat(64), "not-admitted")
            .await
            .unwrap()
            .is_none()
    );
    let admitted = j
        .insert_for_caller(delivery('c'), "next".into(), &caller)
        .await
        .unwrap();
    assert_eq!(admitted.replay_admission().unwrap().sequence(), 9);
}

#[tokio::test]
async fn missing_legacy_actor_is_retained_unknown_and_blocks_selected_context_without_adoption() {
    let directory = directory();
    let store = RuntimeStore::new(Some(directory.path().into()), true)
        .await
        .unwrap();
    let j = journal(store, None);
    let old = delivery('f');
    j.insert(old.clone(), "legacy".into()).await.unwrap();
    let fresh = delivery('0');
    j.insert_for_caller(fresh.clone(), "fresh".into(), &TaskCaller::default())
        .await
        .unwrap();
    let queue = j.pending_replay().await.unwrap();
    assert_eq!(queue.quarantined.len(), 1);
    assert_eq!(queue.ordered.len(), 1);
    assert!(queue.quarantined[0].replay_admission().is_err());
    assert!(matches!(
        j.begin_replay(&old.delivery_id, "legacy").await,
        Err(Error::Unavailable {
            code: "task_delivery_replay_quarantined",
            ..
        })
    ));
    assert!(matches!(
        j.begin_replay(&fresh.delivery_id, "fresh").await,
        Err(Error::Unavailable {
            code: "task_delivery_replay_quarantined",
            ..
        })
    ));
    // Re-presenting an ID must never turn an old record into a Human admission.
    let repeated = j
        .insert_for_caller(old.clone(), "legacy".into(), &TaskCaller::default())
        .await
        .unwrap();
    assert!(repeated.replay.is_none());
    // Existing explicit-ID recovery remains possible; actual SDK caller/scope
    // validation is still required by its unchanged execute_delivery contract.
    assert_eq!(
        serde_json::to_value(j.begin(&old.delivery_id, "legacy").await.unwrap().delivery).unwrap(),
        serde_json::to_value(old).unwrap()
    );
    let original = serde_json::to_value(&repeated).unwrap();
    assert!(original.get("replay").is_none());
    let state=State::load(Some(serde_json::json!({"version":1,"deliveries":{(repeated.delivery.delivery_id.clone()):original}}))).unwrap();
    assert_eq!(state.last_sequence, 0);
    assert_eq!(state.replay_queue(&context(None)).quarantined.len(), 1);
}

#[tokio::test]
async fn actor_capture_rejects_mismatch_and_duplicate_ids_preserve_original_metadata_and_payload() {
    let directory = directory();
    let store = RuntimeStore::new(Some(directory.path().into()), true)
        .await
        .unwrap();
    let j = journal(store, None);
    let first = delivery('a');
    let caller = codex(THREAD, false);
    let stored = j
        .insert_for_caller(first.clone(), "intent".into(), &caller)
        .await
        .unwrap();
    let mut regenerated = first.clone();
    regenerated.input["encrypted_title"] = serde_json::json!("different-random-ciphertext");
    let repeated = j
        .insert_for_caller(regenerated, "intent".into(), &caller)
        .await
        .unwrap();
    assert_eq!(
        serde_json::to_value(&repeated).unwrap(),
        serde_json::to_value(&stored).unwrap()
    );
    assert!(matches!(
        j.insert_for_caller(first.clone(), "intent".into(), &codex(OTHER_THREAD, false))
            .await,
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        j.insert_for_caller(
            delivery('b'),
            "bad".into(),
            &TaskCaller {
                codex_thread_id: None,
                as_assignee: true
            }
        )
        .await,
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        j.insert_for_caller(delivery('b'), "bad".into(), &codex("invalid", false))
            .await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        j.insert_for_caller(delivery('b'), "bad".into(), &codex(THREAD, true))
            .await,
        Err(Error::Forbidden)
    ));
    let fresh = j
        .insert_for_caller(delivery('c'), "fresh".into(), &TaskCaller::default())
        .await
        .unwrap();
    assert_eq!(fresh.replay_admission().unwrap().sequence(), 2);
    assert_eq!(
        serde_json::to_value(
            j.lookup(&first.delivery_id, "intent")
                .await
                .unwrap()
                .unwrap()
        )
        .unwrap(),
        serde_json::to_value(stored).unwrap()
    );
}

#[tokio::test]
async fn fifo_and_quarantine_never_switch_or_leak_other_team_contexts_and_cooldown_still_spans_them()
 {
    let directory = directory();
    let store = RuntimeStore::new(Some(directory.path().into()), true)
        .await
        .unwrap();
    let personal = journal(store.clone(), None);
    let team = journal(store.clone(), Some("team-a"));
    let old = delivery('f');
    let mut team_delivery = delivery('e');
    team_delivery.team_id = Some("team-a".into());
    team.insert(team_delivery.clone(), "legacy-team".into())
        .await
        .unwrap();
    let first = personal
        .insert_for_caller(old.clone(), "personal".into(), &TaskCaller::default())
        .await
        .unwrap();
    let mut known_team = delivery('d');
    known_team.team_id = Some("team-a".into());
    team.insert_for_caller(known_team, "new-team".into(), &TaskCaller::default())
        .await
        .unwrap();
    let last = personal
        .insert_for_caller(
            delivery('0'),
            "later-personal".into(),
            &TaskCaller::default(),
        )
        .await
        .unwrap();
    assert!(
        last.replay_admission().unwrap().sequence() > first.replay_admission().unwrap().sequence()
    );
    assert!(
        personal
            .pending_replay()
            .await
            .unwrap()
            .quarantined
            .is_empty()
    );
    assert_eq!(personal.pending_replay().await.unwrap().ordered.len(), 2);
    assert_eq!(team.pending_replay().await.unwrap().quarantined.len(), 1);
    assert!(matches!(
        personal
            .begin_replay(&team_delivery.delivery_id, "legacy-team")
            .await,
        Err(Error::Forbidden)
    ));
    personal
        .begin_replay(&old.delivery_id, "personal")
        .await
        .unwrap();
    let retry = personal.defer(&old.delivery_id, "personal").await.unwrap();
    assert_eq!(
        personal
            .begin_replay(&old.delivery_id, "personal")
            .await
            .unwrap()
            .deferred
            .unwrap()
            .retry_at,
        retry.retry_at
    );
    // Manual old-context recovery respects the very same account/API cooldown.
    assert_eq!(
        team.begin(&team_delivery.delivery_id, "legacy-team")
            .await
            .unwrap()
            .deferred
            .unwrap()
            .retry_at,
        retry.retry_at
    );
    personal
        .acknowledge(
            &old.delivery_id,
            "personal",
            serde_json::json!({"version":1}),
        )
        .await
        .unwrap();
    assert!(
        personal
            .begin_replay(&last.delivery.delivery_id, "later-personal")
            .await
            .unwrap()
            .deferred
            .is_none()
    );
    assert!(matches!(
        team.begin_replay(&"d".repeat(64), "new-team").await,
        Err(Error::Unavailable {
            code: "task_delivery_replay_quarantined",
            ..
        })
    ));
    let other_api = Journal::new(
        store.clone(),
        "owner".into(),
        serde_json::to_string(&("https://other.example.test", Option::<&str>::None)).unwrap(),
        Zeroizing::new([42; 32]),
    );
    assert!(other_api.pending_replay().await.unwrap().ordered.is_empty());
    let other_owner = Journal::new(
        store,
        "other-owner".into(),
        context(None),
        Zeroizing::new([42; 32]),
    );
    assert!(
        other_owner
            .pending_replay()
            .await
            .unwrap()
            .ordered
            .is_empty()
    );
}

#[tokio::test]
async fn duplicate_or_invalid_order_metadata_is_retained_quarantined_and_cannot_skip_fifo() {
    let directory = directory();
    let store = RuntimeStore::new(Some(directory.path().into()), true)
        .await
        .unwrap();
    let j = journal(store, None);
    for id in ['a', 'b'] {
        j.insert_for_caller(delivery(id), id.to_string(), &TaskCaller::default())
            .await
            .unwrap();
    }
    j.access(|mut state| {
        state
            .deliveries
            .get_mut(&"b".repeat(64))
            .unwrap()
            .replay
            .as_mut()
            .unwrap()
            .sequence = 1;
        Ok((Some(state), ()))
    })
    .await
    .unwrap();
    assert_eq!(j.pending_replay().await.unwrap().quarantined.len(), 2);
    assert!(j.pending_replay().await.unwrap().ordered.is_empty());
    assert!(matches!(
        j.begin_replay(&"a".repeat(64), "a").await,
        Err(Error::Unavailable {
            code: "task_delivery_replay_quarantined",
            ..
        })
    ));
    j.access(|mut state| {
        let metadata = state
            .deliveries
            .get_mut(&"b".repeat(64))
            .unwrap()
            .replay
            .as_mut()
            .unwrap();
        metadata.sequence = 2;
        metadata.version = 2;
        Ok((Some(state), ()))
    })
    .await
    .unwrap();
    assert_eq!(j.pending_replay().await.unwrap().quarantined.len(), 1);
    assert_eq!(j.pending().await.unwrap().len(), 2);
    assert!(matches!(
        j.begin_replay(&"a".repeat(64), "a").await,
        Err(Error::Unavailable {
            code: "task_delivery_replay_quarantined",
            ..
        })
    ));
    assert!(j.lookup(&"a".repeat(64), "a").await.unwrap().unwrap().phase == Phase::Prepared);
}

#[tokio::test]
async fn actor_metadata_and_sequence_are_encrypted_with_the_payload_and_counter_exhaustion_retains_work()
 {
    let directory = directory();
    let store = RuntimeStore::new(Some(directory.path().into()), true)
        .await
        .unwrap();
    let j = journal(store, None);
    j.insert_for_caller(
        delivery('a'),
        "private-intent".into(),
        &codex(THREAD, false),
    )
    .await
    .unwrap();
    for file in std::fs::read_dir(directory.path()).unwrap() {
        let path = file.unwrap().path();
        if path.is_file() {
            let bytes = std::fs::read(path).unwrap();
            assert!(!bytes.windows(THREAD.len()).any(|w| w == THREAD.as_bytes()));
            assert!(!bytes.windows(13).any(|w| w == b"private-intent"));
        }
    }
    j.access(|mut state| {
        state.last_sequence = u64::MAX;
        Ok((Some(state), ()))
    })
    .await
    .unwrap();
    assert!(matches!(
        j.insert_for_caller(delivery('b'), "later".into(), &TaskCaller::default())
            .await,
        Err(Error::Invalid(_))
    ));
    assert_eq!(j.pending().await.unwrap().len(), 1);
    assert!(j.lookup(&"b".repeat(64), "later").await.unwrap().is_none());
}
