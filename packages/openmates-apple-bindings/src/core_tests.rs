//! OpenMatesCore runtime: off-caller async delivery, cancellation by drop, and the credential snapshot round trip.
use crate::*;
use std::sync::{Arc, Mutex};
use std::time::Duration;

const API: &str = "https://never-contact.example.invalid";

fn core() -> Arc<OpenMatesCore> {
    OpenMatesCore::new(CoreConfig {
        api_url: API.into(),
        app_url: Some("https://app.example.invalid".into()),
        cache_container: None,
        cache_directory_name: None,
    })
    .unwrap()
}

#[derive(Default)]
struct Recorder(Mutex<Vec<u64>>);
impl CoreListener for Recorder {
    fn credentials_changed(&self, revision: u64) {
        self.0.lock().unwrap().push(revision);
    }
}

async fn wait_for<F: Fn() -> bool>(condition: F) {
    for _ in 0..200 {
        if condition() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    panic!("condition not reached");
}

#[tokio::test]
async fn probe_runs_on_the_core_runtime_not_the_caller() {
    let core = core();
    let probe = core.probe().await.unwrap();
    assert_eq!(probe.core_version, core_version());
    assert!(probe.ran_on_core_runtime);
    assert_eq!(core.active_operations(), 0);
}

#[tokio::test]
async fn cancelling_the_handle_stops_the_rust_work_and_returns_cancelled() {
    let core = core();
    let caller = core.clone();
    let cancellation = CoreCancellation::new();
    let handle = cancellation.clone();
    let task = tokio::spawn(async move { caller.sleep_cancellable(60_000, handle).await });
    wait_for(|| core.active_operations() == 1).await;
    // What Swift's withTaskCancellationHandler(onCancel:) does.
    cancellation.cancel();
    assert_eq!(task.await.unwrap(), Err(CoreError::Cancelled));
    assert!(cancellation.is_cancelled());
    assert_eq!(core.active_operations(), 0);
    assert_eq!(
        core.sleep_cancellable(1, CoreCancellation::new()).await,
        Ok(())
    );
    // A handle cancelled before the call starts refuses at once.
    let early = CoreCancellation::new();
    early.cancel();
    assert_eq!(
        core.sleep_cancellable(60_000, early).await,
        Err(CoreError::Cancelled)
    );
}

#[tokio::test]
async fn dropping_a_cancellable_call_stops_the_rust_work() {
    let core = core();
    let caller = core.clone();
    let task = tokio::spawn(async move {
        caller
            .sleep_cancellable(60_000, CoreCancellation::new())
            .await
    });
    wait_for(|| core.active_operations() == 1).await;
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    wait_for(|| core.active_operations() == 0).await;
}

#[tokio::test]
async fn non_cancellable_work_survives_a_dropped_caller() {
    let core = core();
    let caller = core.clone();
    let payload = test_support_synthetic_credentials_payload(API.into()).unwrap();
    let task = tokio::spawn(async move { caller.restore_credentials(payload).await });
    task.abort();
    let _ = task.await;
    // The restore either never started or ran to completion; never half-applied.
    wait_for(|| core.active_operations() == 0).await;
    if let Some(snapshot) = core.credential_snapshot().await.unwrap() {
        assert!(!snapshot.payload.is_empty());
    }
}

#[tokio::test]
async fn credential_snapshot_round_trip_notifies_and_acknowledges() {
    let core = core();
    let recorder = Arc::new(Recorder::default());
    core.set_listener(Some(recorder.clone()));
    assert!(core.credential_snapshot().await.unwrap().is_none());
    assert_eq!(
        core.acknowledge_credentials(1).await,
        Err(CoreError::Authentication)
    );

    let payload = test_support_synthetic_credentials_payload(API.into()).unwrap();
    core.restore_credentials(payload.clone()).await.unwrap();
    let snapshot = core.credential_snapshot().await.unwrap().unwrap();
    // The listener is told about exactly the revision the snapshot carries.
    let revision = snapshot.revision;
    wait_for(|| recorder.0.lock().unwrap().contains(&revision)).await;
    let stored: serde_json::Value = serde_json::from_slice(&snapshot.payload).unwrap();
    let original: serde_json::Value = serde_json::from_slice(&payload).unwrap();
    assert_eq!(stored, original);
    assert_eq!(
        core.acknowledge_credentials(snapshot.revision - 1).await,
        Err(CoreError::Cancelled)
    );
    assert_eq!(
        core.acknowledge_credentials(snapshot.revision).await,
        Ok(())
    );

    // A second core restores the stored payload byte for byte (app relaunch).
    let relaunched = self::core();
    relaunched
        .restore_credentials(snapshot.payload)
        .await
        .unwrap();
    let again = relaunched.credential_snapshot().await.unwrap().unwrap();
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&again.payload).unwrap(),
        original
    );

    core.clear_credentials().await.unwrap();
    wait_for(|| {
        recorder
            .0
            .lock()
            .unwrap()
            .iter()
            .any(|seen| *seen > revision)
    })
    .await;
    assert!(core.credential_snapshot().await.unwrap().is_none());
}

#[tokio::test]
async fn restore_refuses_garbage_and_foreign_origin_payloads() {
    let core = core();
    assert_eq!(
        core.restore_credentials(b"not json".to_vec()).await,
        Err(CoreError::Protocol)
    );
    let foreign =
        test_support_synthetic_credentials_payload("https://other.example.invalid".into()).unwrap();
    assert_eq!(
        core.restore_credentials(foreign).await,
        Err(CoreError::Forbidden)
    );
}

#[test]
fn invalid_api_url_is_a_typed_error() {
    let result = OpenMatesCore::new(CoreConfig {
        api_url: "ftp://bad".into(),
        app_url: None,
        cache_container: None,
        cache_directory_name: None,
    });
    assert!(matches!(result, Err(CoreError::Invalid { .. })));
}

#[tokio::test]
async fn dropping_the_core_inside_an_async_context_does_not_panic() {
    let core = core();
    core.probe().await.unwrap();
    drop(core);
}
