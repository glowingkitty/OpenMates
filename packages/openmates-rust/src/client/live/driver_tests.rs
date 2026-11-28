//! `LiveDriver` routing with a fake transport/cache/key resolver: open, seed, persist, tick
//! checkpoint with a 409 retry, and non-live frames left alone.

use super::driver::{LiveDriver, LiveIo};
use super::engine::SealedUpdate;
use super::session_types::{CheckpointRequest, CheckpointResult, Event, Status};
use super::support::{ID, KEY};
use super::{LiveError, LiveItemKind};
use serde_json::{Value, json};
use std::collections::HashMap;

#[derive(Default)]
struct Fake {
    sent: Vec<(String, Value)>,
    stored: HashMap<String, Vec<SealedUpdate>>,
    checkpoints: Vec<CheckpointRequest>,
    results: Vec<CheckpointResult>,
    fail_key: bool,
    fail_outbox_once: bool,
}

impl LiveIo for Fake {
    fn send(&mut self, message_type: &str, payload: &Value) -> Result<(), LiveError> {
        self.sent.push((message_type.to_string(), payload.clone()));
        Ok(())
    }
    async fn persist_outbox(
        &mut self,
        item_id: &str,
        entries: &[SealedUpdate],
    ) -> Result<(), LiveError> {
        if std::mem::take(&mut self.fail_outbox_once) {
            return Err(LiveError::Io("live_outbox_unavailable"));
        }
        self.stored.insert(item_id.to_string(), entries.to_vec());
        Ok(())
    }
    async fn load_outbox(&mut self, item_id: &str) -> Result<Vec<SealedUpdate>, LiveError> {
        Ok(self.stored.get(item_id).cloned().unwrap_or_default())
    }
    async fn resolve_key(
        &mut self,
        _: &str,
        _: bool,
    ) -> Result<super::driver::LiveKeys, LiveError> {
        if self.fail_key {
            return Err(LiveError::Io("live_key_unavailable"));
        }
        Ok(super::driver::LiveKeys {
            epoch: 1,
            current: zeroize::Zeroizing::new(KEY),
            previous: vec![],
        })
    }
    async fn read_content(&mut self, _: &str) -> Result<String, LiveError> {
        Ok("| A |\n| --- |\n| 1 |".to_string())
    }
    async fn write_checkpoint(&mut self, request: &CheckpointRequest) -> CheckpointResult {
        self.checkpoints.push(request.clone());
        self.results.remove(0)
    }
    async fn read_version_text(&mut self, _: &str, _: i64) -> Result<String, LiveError> {
        Ok(String::new())
    }
    async fn post_assistant_outcome(&mut self, _: &str, _: &Value) -> Result<(), LiveError> {
        Ok(())
    }
    fn assistant_change_not_open(&mut self, _: &str, _: &Value) {}
    async fn base_version(&mut self, _: &str) -> Option<i64> {
        Some(3)
    }
}

fn types(io: &Fake) -> Vec<&str> {
    io.sent.iter().map(|(t, _)| t.as_str()).collect()
}

#[tokio::test]
async fn open_resolves_key_subscribes_and_seeds_an_empty_log() {
    let mut driver = LiveDriver::new(Fake::default());
    driver.set_connected(true, 0).await.unwrap();
    driver.open(ID, LiveItemKind::Sheet, 0).await.unwrap();
    assert_eq!(types(driver.io_mut()), ["live_item_subscribe"]);
    let state = json!({"item_id": ID, "role": "edit", "updates": [], "head_seq": 0});
    let events = driver
        .on_frame("live_item_state", &state, 10)
        .await
        .unwrap()
        .expect("live frame");
    assert!(events.iter().any(|e| matches!(e, Event::View { .. })));
    let io = driver.io_mut();
    assert!(types(io).contains(&"live_item_update"));
    assert!(!io.stored[ID].is_empty(), "outbox persisted to the cache");
}

#[tokio::test]
async fn due_checkpoint_retries_on_conflict_and_non_live_frames_are_ignored() {
    let mut driver = LiveDriver::new(Fake::default());
    driver.io_mut().results = vec![CheckpointResult::Conflict(7), CheckpointResult::Written(8)];
    driver.set_connected(true, 0).await.unwrap();
    driver.open(ID, LiveItemKind::Sheet, 0).await.unwrap();
    let state = json!({"item_id": ID, "role": "edit", "updates": [], "head_seq": 0});
    driver
        .on_frame("live_item_state", &state, 10)
        .await
        .unwrap();
    let ack = json!({"item_id": ID, "client_msg_id": driver.io_mut().stored[ID][0].client_msg_id, "seq": 1});
    driver
        .on_frame("live_item_update_ack", &ack, 20)
        .await
        .unwrap();
    let events = driver.tick(10 * 60_000).await.unwrap();
    // Only the written version is reported (the conflict is retried first).
    let written: Vec<_> = events
        .iter()
        .filter_map(|e| match e {
            Event::VersionWritten { version, text, .. } => Some((*version, text.clone())),
            _ => None,
        })
        .collect();
    assert_eq!(written.len(), 1);
    assert_eq!(written[0].0, 8);
    assert!(written[0].1.contains("| A |"));
    let io = driver.io_mut();
    assert_eq!(io.checkpoints.len(), 2);
    assert_eq!(io.checkpoints[0].base_version, Some(3));
    assert_eq!(io.checkpoints[1].base_version, Some(7));
    assert!(
        driver
            .on_frame("chat_message_added", &json!({}), 30)
            .await
            .unwrap()
            .is_none()
    );
}

#[tokio::test]
async fn core_opened_item_closes_only_after_its_update_is_acknowledged() {
    let mut driver = LiveDriver::new(Fake::default());
    driver.set_connected(true, 0).await.unwrap();
    driver.open(ID, LiveItemKind::Sheet, 0).await.unwrap();
    let state = json!({"item_id": ID, "role": "edit", "updates": [], "head_seq": 0});
    driver
        .on_frame("live_item_state", &state, 10)
        .await
        .unwrap();
    driver.session_mut().mark_headless(ID);
    driver.close_settled_headless(11).await.unwrap();
    assert_eq!(
        driver.session().len(),
        1,
        "unacknowledged update keeps it open"
    );
    let ack = json!({"item_id": ID, "client_msg_id": driver.io_mut().stored[ID][0].client_msg_id, "seq": 1});
    driver
        .on_frame("live_item_update_ack", &ack, 20)
        .await
        .unwrap();
    driver.close_settled_headless(21).await.unwrap();
    assert_eq!(driver.session().len(), 0);
    assert!(types(driver.io_mut()).contains(&"live_item_unsubscribe"));
}

#[tokio::test]
async fn open_with_unresolvable_key_emits_offline_status_instead_of_failing_silently() {
    let mut driver = LiveDriver::new(Fake {
        fail_key: true,
        ..Fake::default()
    });
    driver.set_connected(true, 0).await.unwrap();
    let events = driver.open(ID, LiveItemKind::Sheet, 0).await.unwrap();
    assert!(events.iter().any(|e| matches!(
        e,
        Event::Status { item_id, status: Status::Offline } if item_id == ID
    )));
    assert!(
        driver.io_mut().sent.is_empty(),
        "nothing is subscribed without a key"
    );
}

#[tokio::test]
async fn failed_cache_write_retries_before_sending_the_pending_update() {
    let mut driver = LiveDriver::new(Fake {
        fail_outbox_once: true,
        ..Fake::default()
    });
    driver.set_connected(true, 0).await.unwrap();
    driver.open(ID, LiveItemKind::Sheet, 0).await.unwrap();
    let state = json!({"item_id": ID, "role": "edit", "updates": [], "head_seq": 0});
    assert!(matches!(
        driver.on_frame("live_item_state", &state, 10).await,
        Err(LiveError::Io("live_outbox_unavailable"))
    ));
    assert_eq!(types(driver.io_mut()), ["live_item_subscribe"]);
    driver.tick(2_000).await.unwrap();
    let io = driver.io_mut();
    assert_eq!(io.stored[ID].len(), 1);
    assert_eq!(types(io), ["live_item_subscribe", "live_item_update"]);
}
