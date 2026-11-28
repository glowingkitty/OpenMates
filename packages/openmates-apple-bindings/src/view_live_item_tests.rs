//! Live item binding: frame classification, event mapping and the Swift send/outbox adapters.
use super::*;
use std::collections::HashMap;

#[derive(Default)]
struct Frames(StdMutex<Vec<(String, String)>>, bool);

impl LiveItemSender for Frames {
    fn send_frame(&self, message_type: String, payload_json: String) -> bool {
        self.0.lock().unwrap().push((message_type, payload_json));
        !self.1
    }
}

#[derive(Default)]
struct Store(StdMutex<HashMap<String, String>>);

impl LiveOutboxStorage for Store {
    fn keys(&self, prefix: String) -> Option<Vec<String>> {
        let map = self.0.lock().unwrap();
        Some(map.keys().filter(|k| k.starts_with(&prefix)).cloned().collect())
    }
    fn read(&self, key: String) -> LiveOutboxReadRecord {
        match self.0.lock().unwrap().get(&key) {
            Some(value) => LiveOutboxReadRecord::Found {
                value: value.clone(),
            },
            None => LiveOutboxReadRecord::Missing,
        }
    }
    fn compare_and_put(
        &self,
        key: String,
        expected: Option<String>,
        next: Option<String>,
    ) -> LiveOutboxWriteRecord {
        let mut map = self.0.lock().unwrap();
        if map.get(&key) != expected.as_ref() {
            return LiveOutboxWriteRecord::Conflict;
        }
        match next {
            Some(value) => map.insert(key, value),
            None => map.remove(&key),
        };
        LiveOutboxWriteRecord::Written
    }
}

#[test]
fn classifies_live_and_assistant_frames_only() {
    assert!(live_is_frame("live_item_state".into()));
    assert!(live_is_frame("embed_assistant_change".into()));
    assert!(!live_is_frame("chat_message".into()));
}

#[test]
fn maps_remote_updates_and_named_events() {
    let update = event_record(Event::RemoteUpdate {
        item_id: "e1".into(),
        bytes: vec![1, 2],
    });
    assert_eq!(
        update,
        Some(LiveItemEventRecord::RemoteUpdate {
            item_id: "e1".into(),
            bytes: vec![1, 2]
        })
    );
    let presence = event_record(Event::Presence {
        item_id: "e1".into(),
        peers: serde_json::json!([]),
    });
    assert_eq!(
        presence,
        Some(LiveItemEventRecord::Named {
            name: "livePresence".into(),
            payload_json: r#"{"itemId":"e1","peers":[]}"#.into()
        })
    );
}

#[test]
fn sender_failure_is_a_not_connected_error() {
    let ok = AppleSend(Arc::new(Frames::default()));
    assert!(ok.send("live_item_open", "{}").is_ok());
    let closed = AppleSend(Arc::new(Frames(StdMutex::default(), true)));
    assert_eq!(
        closed.send("live_item_open", "{}").unwrap_err().code(),
        "live_not_connected"
    );
}

#[tokio::test]
async fn outbox_adapter_round_trips_and_reports_conflicts() {
    let outbox = AppleOutbox(Arc::new(Store::default()));
    assert!(outbox.compare_and_put("a:1", None, Some("x")).await.unwrap());
    assert!(!outbox.compare_and_put("a:1", None, Some("y")).await.unwrap());
    assert_eq!(outbox.read("a:1").await.unwrap(), Some("x".to_owned()));
    assert_eq!(outbox.keys("a:").await.unwrap(), vec!["a:1".to_owned()]);
    assert!(outbox.compare_and_put("a:1", Some("x"), None).await.unwrap());
    assert_eq!(outbox.read("a:1").await.unwrap(), None);
}
