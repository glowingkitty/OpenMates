use super::*;

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[test]
fn replay_waits_for_every_explicit_watch_and_reconnect_revokes_old_lease() {
    assert!(Readiness::new(0).is_err());
    assert!(Readiness::new(MAX_WATCHES + 1).is_err());
    let gate = Readiness::new(2).unwrap();
    assert!(gate.lease().unwrap().is_none());
    gate.set(0, true).unwrap();
    assert!(gate.lease().unwrap().is_none());
    gate.set(1, true).unwrap();
    let lease = gate.lease().unwrap().unwrap();
    assert!(!lease.is_cancelled());
    gate.set(0, false).unwrap();
    assert!(lease.is_cancelled());
    assert!(gate.lease().unwrap().is_none());
    gate.set(0, true).unwrap();
    let current = gate.lease().unwrap().unwrap();
    assert!(!current.is_cancelled());
    assert!(lease.is_cancelled());
    gate.stop();
    assert!(current.is_cancelled());
    assert!(gate.lease().unwrap().is_none());
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[test]
fn one_watcher_never_promotes_the_other_or_cancels_its_owner() {
    let gate = Readiness::new(2).unwrap();
    let owner = CancellationToken::new();
    gate.set(0, true).unwrap();
    gate.set(1, true).unwrap();
    let lease = gate.lease().unwrap().unwrap();
    gate.set(1, false).unwrap();
    assert!(lease.is_cancelled());
    assert!(!owner.is_cancelled());
    gate.set(0, true).unwrap();
    assert!(gate.lease().unwrap().is_none());
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[test]
fn recoverable_contention_fences_replay_until_the_suspended_watch_commits_again() {
    let gate = Readiness::new(2).unwrap();
    gate.set(0, true).unwrap();
    gate.set(1, true).unwrap();
    let before_contention = gate.lease().unwrap().unwrap();
    // The actor clears readiness before suspend/reconnect and invalidated fsync
    // completion cannot set it: only fresh watch.commit reaches set(true).
    gate.set(0, false).unwrap();
    assert!(before_contention.is_cancelled());
    assert!(gate.lease().unwrap().is_none());
    // Another watch's final publication cannot substitute for the suspended one.
    gate.set(1, true).unwrap();
    assert!(gate.lease().unwrap().is_none());
    // A fresh durable publication and exact commit restores that watch only.
    gate.set(0, true).unwrap();
    let recovered = gate.lease().unwrap().unwrap();
    assert!(!recovered.is_cancelled());
    assert!(before_contention.is_cancelled());
}

fn private_root() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().unwrap()
}
fn seeded_cache(
    root: &std::path::Path,
    project: &str,
) -> (
    Cache,
    openmates_sdk::project_task_sync::TaskSyncScope,
    serde_json::Value,
) {
    use openmates_sdk::{
        crypto,
        project_task_sync::{TaskSyncEvent, TaskSyncFrame, TaskSyncScope, TaskSyncWorkspace},
    };
    use serde_json::json;
    use sha2::{Digest, Sha256};
    let hash = |value: &str| format!("{:x}", Sha256::digest(value.as_bytes()));
    let scope = TaskSyncScope::new(
        "https://example.invalid",
        "user",
        TaskSyncWorkspace::Personal,
        project,
        &format!("source-{project}"),
    )
    .unwrap();
    let mut cache = ProjectTaskCache::open(
        root,
        scope.clone(),
        "hashed-email",
        zeroize::Zeroizing::new([3; 32]),
        now(),
    )
    .unwrap();
    let id = format!("task-{project}");
    let key = [7; 32];
    let encrypted = json!({"task_id":id,"version":1,"status":"todo","hashed_user_id":hash("user"),
        "encrypted_title":crypto::encrypt_combined("Synthetic private Task",&key).unwrap(),
        "encrypted_description":crypto::encrypt_combined("Synthetic description",&key).unwrap(),
        "key_wrappers":[{"key_type":"project","hashed_project_id":hash(project),"hashed_task_id":hash(&id),
            "hashed_user_id":hash("user"),"encrypted_task_key":crypto::encrypt_bytes(&key,&[3;32]).unwrap()}]});
    cache
        .accept(
            &scope,
            TaskSyncEvent::Batch(TaskSyncFrame {
                project_id: project.into(),
                batch_id: "batch-1".into(),
                part: 0,
                final_part: true,
                reset: true,
                cursor: "epoch:1".into(),
                tasks: vec![encrypted.clone()],
                removed_task_ids: vec![],
            }),
            now(),
        )
        .unwrap();
    let _transferred_reducer = cache.take_sync().unwrap();
    (Arc::new(SyncMutex::new(cache)), scope, encrypted)
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn source_denial_a_fences_context_replay_and_retains_b_ciphertext() {
    let root = private_root();
    let (a, scope_a, _) = seeded_cache(root.path(), "project-a");
    let (b, scope_b, encrypted_b) = seeded_cache(root.path(), "project-b");
    let gate = Readiness::new(2).unwrap();
    gate.set(0, true).unwrap();
    gate.set(1, true).unwrap();
    let replay = gate.lease().unwrap().unwrap();
    gate.set(0, false).unwrap();
    cache_state(a.clone(), revoke_cache(true, true), true, scope_a)
        .await
        .unwrap();
    cache_state(b.clone(), revoke_cache(true, false), true, scope_b)
        .await
        .unwrap();
    assert!(replay.is_cancelled());
    assert!(gate.lease().unwrap().is_none());
    let a = a.lock().unwrap();
    let b = b.lock().unwrap();
    assert!(a.directory().join("revoked.json").exists());
    assert!(!b.directory().join("revoked.json").exists());
    let snapshot = b.snapshot().unwrap();
    assert!(snapshot.connection == crate::project_task_cache::CacheConnection::Stopped);
    assert_eq!(snapshot.tasks.len(), 1);
    assert_eq!(snapshot.tasks[0].encrypted, encrypted_b);
    let disk: serde_json::Value =
        serde_json::from_slice(&std::fs::read(b.directory().join("snapshot.json")).unwrap())
            .unwrap();
    assert_eq!(disk["tasks"][0]["encrypted"], encrypted_b);
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn mutation_403_without_owner_loss_stops_replay_without_revoking_caches() {
    let root = private_root();
    let gate = Readiness::new(2).unwrap();
    gate.set(0, true).unwrap();
    gate.set(1, true).unwrap();
    let replay = gate.lease().unwrap().unwrap();
    // Task transport denial stops the driver, but is no owner/source signal.
    let _mutation_result: Result<()> = Err(Error::Forbidden);
    gate.stop();
    for project in ["project-a", "project-b"] {
        let (cache, scope, encrypted) = seeded_cache(root.path(), project);
        cache_state(cache.clone(), revoke_cache(true, false), true, scope)
            .await
            .unwrap();
        let cache = cache.lock().unwrap();
        assert!(!cache.directory().join("revoked.json").exists());
        assert_eq!(cache.snapshot().unwrap().tasks[0].encrypted, encrypted);
    }
    assert!(replay.is_cancelled());
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn negative_owner_authority_signal_revokes_every_bound_cache() {
    let root = private_root();
    let gate = Readiness::new(2).unwrap();
    gate.set(0, true).unwrap();
    gate.set(1, true).unwrap();
    let replay = gate.lease().unwrap().unwrap();
    gate.stop();
    // False comes only from the SDK's opaque original owner epoch/expiry fence,
    // independently checked by each actor even if sibling cancellation wins.
    for project in ["project-a", "project-b"] {
        let (cache, scope, _) = seeded_cache(root.path(), project);
        cache_state(cache.clone(), revoke_cache(false, false), true, scope)
            .await
            .unwrap();
        let cache = cache.lock().unwrap();
        assert!(cache.directory().join("revoked.json").exists());
        assert!(cache.snapshot().unwrap().tasks.is_empty());
    }
    assert!(replay.is_cancelled());
    assert!(gate.lease().unwrap().is_none());
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn later_setup_source_lookup_denial_keeps_already_opened_valid_cache() {
    let root = private_root();
    let (opened, scope, encrypted) = seeded_cache(root.path(), "project-a");
    let opened_index = 0;
    let denied_lookup_index = 1;
    cache_state(
        opened.clone(),
        setup_revoke_cache(true, opened_index, denied_lookup_index, Error::Forbidden),
        true,
        scope,
    )
    .await
    .unwrap();
    let cache = opened.lock().unwrap();
    assert!(!cache.directory().join("revoked.json").exists());
    assert_eq!(cache.snapshot().unwrap().tasks[0].encrypted, encrypted);
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn blocked_real_journal_preparation_keeps_client_lane_and_replay_lease_available() {
    use std::future::Future;
    let root = private_root();
    let store = RuntimeStore::new(Some(root.path().to_owned()), true)
        .await
        .unwrap();
    let key = zeroize::Zeroizing::new([42; 32]);
    let session = crate::storage::Session {
        api_url: "https://example.invalid".into(),
        session_id: "synthetic-session".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: key.clone(),
        hashed_email: "owner".into(),
        user_email_salt: "synthetic-salt".into(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let client = Arc::new(Mutex::new(
        Client::new("https://example.invalid", Some(session)).unwrap(),
    ));
    let context = {
        let client = client.lock().await;
        CookieJournalContext::capture(&client).unwrap()
    };
    let journal = context.journal(&store).unwrap();
    let gate = Readiness::new(1).unwrap();
    gate.set(0, true).unwrap();
    let lease = gate.lease().unwrap().unwrap();
    let cancel = CancellationToken::new();
    let (entered, ready) = tokio::sync::oneshot::channel();
    let (release, wait) = std::sync::mpsc::channel();
    // Always release the blocking fixture on assertion failure too.
    struct Release(Option<std::sync::mpsc::Sender<()>>);
    impl Drop for Release {
        fn drop(&mut self) {
            if let Some(release) = self.0.take() {
                let _ = release.send(());
            }
        }
    }
    let release = Release(Some(release));
    let blocked_store = store.clone();
    let generation = store.generation();
    let blocker = tokio::spawn(async move {
        blocked_store
            .update_private_record(
                "owner".into(),
                "slow-journal-fixture".into(),
                "pause".into(),
                key,
                generation,
                move |_| {
                    let _ = entered.send(());
                    wait.recv().map_err(|_| Error::Io)?;
                    Ok((None, ()))
                },
            )
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), ready)
        .await
        .unwrap()
        .unwrap();
    // Poll the real replay_head into the already-held RuntimeStore queue. This
    // detects a future regression that takes Client before journal preparation.
    let mut head = Box::pin(replay_head(&client, &context, &journal, &lease, &cancel));
    std::future::poll_fn(|cx| {
        assert!(
            head.as_mut().poll(cx).is_pending(),
            "journal barrier must hold replay_head"
        );
        std::task::Poll::Ready(())
    })
    .await;
    let lane = tokio::time::timeout(FINISH_ADMISSION / 2, client.lock())
        .await
        .expect("blocked journal IO must leave Client acquirable before watch finish timeout");
    assert!(!lease.is_cancelled());
    assert!(gate.lease().unwrap().is_some());
    drop(lane);
    drop(release);
    blocker.await.unwrap().unwrap();
    assert!(!head.await.ok().unwrap()); // Empty journal: no network or Task execution.
    assert!(!lease.is_cancelled());
}
