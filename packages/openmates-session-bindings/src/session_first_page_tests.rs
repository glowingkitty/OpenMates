//! Pure mailbox/queued-output regressions, authored for isolated CI. No HTTP,
//! account, fake canonical grant or product performance claim.
use super::*;
fn bridge() -> SessionBridge {
    SessionBridge::new(&json!({"api_url":"http://127.0.0.1:9","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}).to_string()).unwrap_or_else(|error|panic!("{}",error.code))
}
fn entry(bridge: &SessionBridge, id: &str) -> (Arc<Entry>, mpsc::Receiver<Pull>) {
    let guard = EssentialGuard::new(bridge, false).unwrap_or_else(|error| panic!("{}", error.code));
    let (pulls, receiver) = mpsc::channel(1);
    let entry = Arc::new(Entry {
        guard,
        pulls,
        pending: Mutex::new(None),
        reading: AtomicBool::new(false),
    });
    bridge
        .state
        .essential
        .first_pages
        .entries
        .lock()
        .unwrap()
        .insert(id.into(), entry.clone());
    (entry, receiver)
}
fn pending(entry: &Entry, id: &str) -> oneshot::Receiver<Receipt> {
    let (sender, receiver) = oneshot::channel();
    *entry.pending.lock().unwrap() = Some(Pending {
        id: id.into(),
        digest: "exact-stored-hash".into(),
        revision: 7,
        sender: PendingSender::Receipt(sender),
    });
    receiver
}
fn receipt(hash: &str, revision: u64) -> String {
    json!({"ciphertext_sha256":hash,"credential_revision":revision}).to_string()
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn mailbox_exact_receipt_operates_while_original_client_lock_is_held() {
    let bridge = bridge();
    let (entry, _) = entry(&bridge, "read-a");
    let received = pending(&entry, "stage-a");
    let _client = bridge.state.client.lock().await;
    bridge
        .first_page_receipt(
            "read-a".into(),
            "stage-a".into(),
            receipt("exact-stored-hash", 7),
        )
        .unwrap_or_else(|error| panic!("{}", error.code));
    assert_eq!(received.await.unwrap().credential_revision, 7);
    assert_eq!(
        bridge
            .first_page_receipt(
                "read-a".into(),
                "stage-a".into(),
                receipt("exact-stored-hash", 7)
            )
            .err()
            .unwrap()
            .code,
        "conflict"
    );
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn wrong_receipt_or_stage_preserves_exact_original_mailbox_for_retry() {
    let bridge = bridge();
    let (entry, _) = entry(&bridge, "read-a");
    let received = pending(&entry, "stage-a");
    for (stage, hash, revision) in [
        ("stale-stage", "exact-stored-hash", 7),
        ("stage-a", "wrong", 7),
        ("stage-a", "exact-stored-hash", 8),
    ] {
        assert_eq!(
            bridge
                .first_page_receipt("read-a".into(), stage.into(), receipt(hash, revision))
                .err()
                .unwrap()
                .code,
            "conflict"
        );
        assert!(entry.pending.lock().unwrap().is_some());
        assert!(!entry.guard.token().is_cancelled());
    }
    bridge
        .first_page_receipt(
            "read-a".into(),
            "stage-a".into(),
            receipt("exact-stored-hash", 7),
        )
        .unwrap_or_else(|error| panic!("{}", error.code));
    assert_eq!(
        received.await.unwrap().ciphertext_sha256,
        "exact-stored-hash"
    );
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn stale_a_close_or_receipt_never_cancels_b_and_drop_closes_only_owned_pending() {
    let bridge = bridge();
    let (a, _) = entry(&bridge, "a");
    let (b, _) = entry(&bridge, "b");
    let a_receipt = pending(&a, "a-stage");
    let b_receipt = pending(&b, "b-stage");
    bridge
        .first_page_close("a".into())
        .unwrap_or_else(|error| panic!("{}", error.code));
    assert!(a.guard.token().is_cancelled());
    assert!(a_receipt.await.is_err());
    assert_eq!(
        bridge.first_page_close("a".into()).err().unwrap().code,
        "conflict"
    );
    assert_eq!(
        bridge
            .first_page_receipt(
                "a".into(),
                "a-stage".into(),
                receipt("exact-stored-hash", 7)
            )
            .err()
            .unwrap()
            .code,
        "conflict"
    );
    assert!(!b.guard.token().is_cancelled());
    let delivery = ReadDelivery {
        entry: b.clone(),
        delivered: false,
    };
    drop(delivery);
    assert!(b.guard.token().is_cancelled());
    assert!(b_receipt.await.is_err());
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn queued_original_checks_reject_private_denial_request_cancel_and_resource_revocation() {
    // Mock the original proof's independently revocable resource/private gate.
    // The companion core regression uses a real captured MasterCapability.
    for change in ["resource", "private", "request"] {
        let bridge = bridge();
        let (entry, _) = entry(&bridge, "a");
        let resource = Arc::new(AtomicBool::new(true));
        let private = Arc::new(AtomicBool::new(true));
        let original_resource = resource.clone();
        let original_private = private.clone();
        let guard = entry.guard.clone();
        let check: Check = Arc::new(move || {
            guard.check()?;
            if !original_resource.load(Ordering::Acquire)
                || !original_private.load(Ordering::Acquire)
            {
                Err(Error::Cancelled.into())
            } else {
                Ok(())
            }
        });
        let (send, receive) = oneshot::channel();
        send.send(Envelope {
            output: Zeroizing::new("SYNTHETIC_PRIVATE_OUTPUT".into()),
            check,
            released: None,
        })
        .ok()
        .unwrap();
        match change {
            "resource" => resource.store(false, Ordering::Release),
            "private" => private.store(false, Ordering::Release),
            "request" => entry.guard.token().cancel(),
            _ => unreachable!(),
        }
        let mut output = receive.await.unwrap();
        assert!(output.release(&entry.guard).is_err(), "{change}");
        assert!(output.output.is_empty(), "{change}: queued plaintext wiped");
    }
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn consent_refusal_starts_no_driver_and_pull_drop_closes_original_only() {
    let bridge = bridge();
    for (secrets, private) in [(false, true), (true, false), (false, false)] {
        assert_eq!(
            bridge
                .first_page_open(
                    "22222222-2222-4222-8222-222222222222".into(),
                    secrets,
                    private
                )
                .await
                .err()
                .unwrap()
                .code,
            "invalid_argument"
        );
        assert!(
            bridge
                .state
                .essential
                .first_pages
                .entries
                .lock()
                .unwrap()
                .is_empty()
        );
    }
    let (a, _) = entry(&bridge, "a");
    let (b, _) = entry(&bridge, "b");
    let delivery = ReadDelivery {
        entry: a.clone(),
        delivered: false,
    };
    drop(delivery);
    assert!(a.guard.token().is_cancelled());
    assert!(!b.guard.token().is_cancelled());
}

// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn only_successful_original_output_release_signals_driver_to_resume() {
    for reject in [false, true] {
        let bridge = bridge();
        let (entry, _) = entry(&bridge, "a");
        let (send, receive) = oneshot::channel();
        let check: Check = Arc::new(move || {
            if reject {
                Err(Error::Cancelled.into())
            } else {
                Ok(())
            }
        });
        let mut envelope = Envelope {
            output: Zeroizing::new("SYNTHETIC_PRIVATE_OUTPUT".into()),
            check,
            released: Some(send),
        };
        let result = envelope.release(&entry.guard);
        if reject {
            assert!(result.is_err());
            assert!(envelope.output.is_empty());
            drop(envelope);
            assert!(receive.await.is_err());
        } else {
            let Ok(output) = result else {
                panic!("original output release failed");
            };
            assert_eq!(output, "SYNTHETIC_PRIVATE_OUTPUT");
            assert!(receive.await.is_ok());
        }
    }
}

// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn capacity_mailbox_is_typed_no_ack_or_client_lock_and_stale_stage_cannot_admit() {
    for accepted in [false, true] {
        let bridge = bridge();
        let (entry, _) = entry(&bridge, "read-a");
        let (sender, receiver) = oneshot::channel();
        *entry.pending.lock().unwrap() = Some(Pending {
            id: "capacity-a".into(),
            digest: String::new(),
            revision: 0,
            sender: PendingSender::Capacity(sender),
        });
        let _locked = bridge.state.client.lock().await;
        assert_eq!(
            bridge
                .first_page_receipt("read-a".into(), "capacity-a".into(), receipt("", 0))
                .err()
                .unwrap()
                .code,
            "conflict"
        );
        assert_eq!(
            bridge
                .first_page_capacity("read-a".into(), "wrong".into(), true)
                .err()
                .unwrap()
                .code,
            "conflict"
        );
        assert!(entry.pending.lock().unwrap().is_some());
        bridge
            .first_page_capacity("read-a".into(), "capacity-a".into(), accepted)
            .unwrap_or_else(|e| panic!("{}", e.code));
        assert_eq!(receiver.await.unwrap(), accepted);
        assert_eq!(
            bridge
                .first_page_capacity("read-a".into(), "capacity-a".into(), true)
                .err()
                .unwrap()
                .code,
            "conflict"
        );
    }
}
