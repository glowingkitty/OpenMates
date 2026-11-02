//! Actual Bridge/prepared-future regressions using the existing independent peer.
//! Authored UNRUN; no native VM, account, paid inference or local product proof.
//! Every queued call is created BEFORE cancellation/import and before first poll.
//! Same-credential import still retires the original identity epoch; it does not
//! simulate a different account or replace the peer's independent crypto inputs.
use super::*;
use std::{future::Future, pin::Pin};

type Queued = Pin<Box<dyn Future<Output = Result<()>> + Send>>;
fn all_fresh(b: &SessionBridge, peer: &Peer) -> Vec<Queued> {
    let id = peer.suite["saved_stream"]["protocol"]["initial_chat_id"].as_str().unwrap();
    macro_rules! queued {($call:expr) => {{let original=$call;Box::pin(async move {original.await.map(|_| ())}) as Queued}};}
    vec![
        queued!(b.capture_first_page_open(id.into(), true, true)),
        queued!(b.capture_cache_chat_stage(id.into(), true)),
        queued!(b.capture_embeds_version_content(id.into(), "1".into())),
        queued!(b.capture_drafts_list_cached()),
        queued!(b.capture_drafts_list("{}".into())),
        queued!(b.capture_drafts_get(id.into(), "{}".into())),
        queued!(b.capture_drafts_sync()),
        queued!(b.capture_chat_monitor_open()),
        queued!(b.capture_completion_recovery_enable(true)),
        queued!(b.capture_completion_recovery_discover(None)),
        queued!(b.capture_completion_recovery_discover(Some(id.into()))),
        queued!(b.capture_project_task_watch_open("synthetic-project".into(), r#"{"source_id":"synthetic-source","checkpoint":null}"#.into(), r#"{"personal":true,"team_id":null}"#.into())),
        queued!(b.capture_chat_details_prepare(id.into(), "{}".into())),
        queued!(b.capture_full_chat_read_prepare(id.into())),
        queued!(b.capture_chat_message_window(id.into(), "{}".into())),
        queued!(b.capture_saved_chat_read(id.into(), "{}".into())),
        queued!(b.capture_saved_chat_exact_message(id.into(), "{}".into())),
        queued!(b.capture_start_saved_stream("old A private text must never reach B".into(), Some(id.into()))),
    ]
}
fn no_product_io(peer: &Peer) {
    let report = peer.get("/__test/status");
    assert!(report["failure"].is_null());
    assert_eq!(report["product_http_requests"], 0);
    assert_eq!(report["auth_checks"], 0);
    assert_eq!(report["admissions"], 0);
    assert_eq!(report["connections"], 0);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn all_eighteen_original_futures_cancel_or_import_before_first_poll_refuse_every_product_request() {
    for replacement in [false, true] {
        let peer = Peer::new("saved_queued_successor_terminal");
        let b = peer.bridge().await;
        let queued = all_fresh(&b, &peer);
        assert_eq!(queued.len(), 18);
        // The watch has its own original handle; seventeen calls use WorkGuard.
        assert_eq!(b.state.work_operations.lock().unwrap().len(), 17);
        no_product_io(&peer);
        if replacement {ok(b.import_session(peer.session()).await);} else {ok(b.cancel());}
        for call in queued {
            assert_eq!(call.await.err().map(|error| error.code), Some("cancelled"));
        }
        assert!(b.state.work_operations.lock().unwrap().is_empty());
        no_product_io(&peer);
        // A real explicit B uses the exact existing peer protocol and actual SDK.
        let id = peer.start(&b).await;
        let terminal = final_output(&b, &id).await;
        let output = ok(terminal.encode_with(|text| Ok(text.to_owned())));
        assert!(output.contains("completed"));
        let report = peer.get("/__test/status");
        assert!(report["failure"].is_null());
        assert_eq!(report["admissions"], 1);
        assert!(report["product_http_requests"].as_u64().unwrap() > 0);
        ok(b.close().await);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn stale_unpolled_a_refusal_and_drop_leave_real_b_original_stream_and_output_live() {
    let peer = Peer::new("saved_queued_successor_terminal");
    let b = peer.bridge().await;
    let queued = all_fresh(&b, &peer);
    ok(b.cancel());
    let id = peer.start(&b).await;
    // Every old A still owns its cancelled original guard/handle, never B's.
    for call in queued {
        assert_eq!(call.await.err().map(|error| error.code), Some("cancelled"));
    }
    {
        let active = b.state.active.lock().unwrap();
        let actual = active.as_ref().unwrap();
        assert_eq!(actual.id, id);
        assert!(!actual.cancel.is_cancelled());
    }
    let terminal = final_output(&b, &id).await;
    let output = ok(terminal.encode_with(|text| Ok(text.to_owned())));
    assert!(output.contains("completed"));
    assert_eq!(peer.get("/__test/status")["admissions"], 1);
    ok(b.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn dropping_unpolled_original_send_future_releases_only_a_and_fresh_b_can_complete() {
    let peer = Peer::new("saved_queued_successor_terminal");
    let b = peer.bridge().await;
    let old = b.capture_start_saved_stream("private queued A".into(), None);
    assert_eq!(b.state.work_operations.lock().unwrap().len(), 1);
    no_product_io(&peer);
    drop(old); // Zeroizing owns queued text; this is not a foreign-heap wipe claim.
    assert!(b.state.work_operations.lock().unwrap().is_empty());
    no_product_io(&peer);
    let id = peer.start(&b).await;
    let terminal = final_output(&b, &id).await;
    assert!(ok(terminal.encode_with(|text| Ok(text.to_owned()))).contains("completed"));
    assert_eq!(peer.get("/__test/status")["admissions"], 1);
    ok(b.close().await);
}
