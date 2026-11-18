//! The actor's core lock: stream tasks lock it between requests, never during one.
// contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
use super::*;

#[tokio::test]
async fn stream_lease_waits_for_a_request_and_runs_between_requests() {
    let (_directory, mut actor) = super::tests::fixture().await;
    let lease = actor.core.lease();
    // While the actor serves a request it holds the core: a stream phase waits.
    assert!(tokio::time::timeout(Duration::from_millis(50), lease.lease()).await.is_err());
    // Released before the actor waits for its next command: the stream phase runs
    // and the actor (a follow-up Send) re-acquires once the phase guard drops.
    actor.core.release();
    {
        let phase = tokio::time::timeout(Duration::from_secs(1), lease.lease()).await
            .expect("the released core can be leased").unwrap();
        let second = tokio::time::timeout(Duration::from_millis(50), actor.core.acquire()).await;
        assert!(second.is_err(), "the actor waits only for the running phase, not the whole stream");
        drop(phase);
    }
    tokio::time::timeout(Duration::from_secs(1), actor.core.acquire()).await
        .expect("the actor takes the core back after the phase");
    assert!(actor.core.chat_monitor().is_none());
}

#[tokio::test]
async fn monitor_check_never_waits_on_a_streaming_phase() {
    let (_directory, mut actor) = super::tests::fixture().await;
    actor.core.release();
    let lease = actor.core.lease();
    let _phase = lease.lease().await.unwrap();
    assert!(!actor.core.monitor_valid());
}
