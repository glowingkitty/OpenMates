//! Shared boundary fixture executed against the actual direct-library bridge.
use _native::SessionBridge;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
#[tokio::main]
async fn main() {
    let args = std::env::args().collect::<Vec<_>>();
    let value = |name: &str| {
        args.iter()
            .position(|v| v == name)
            .and_then(|i| args.get(i + 1))
            .cloned()
            .expect("missing conformance argument")
    };
    let capability = value("--capability");
    assert_eq!(
        capability, "session.native-boundary.v1",
        "unsupported bridge conformance capability"
    );
    let raw = std::fs::read(value("--fixture")).expect("fixture unavailable");
    let fixture: Value = serde_json::from_slice(&raw).expect("invalid fixture");
    let vectors = fixture["capabilities"][&capability]["vectors"]
        .as_array()
        .expect("missing capability vectors");
    let mut results = vec![];
    for vector in vectors {
        let bridge = SessionBridge::new(&vector["options"].to_string())
            .unwrap_or_else(|_| panic!("construct"));
        bridge
            .import_session(vector["session"].to_string())
            .await
            .unwrap_or_else(|_| panic!("import"));
        let exported: Value = serde_json::from_str(
            &bridge
                .export_session(true)
                .await
                .unwrap_or_else(|_| panic!("export")),
        )
        .expect("invalid export");
        assert!(
            exported["session"] == vector["session"],
            "session roundtrip mismatch"
        );
        assert_eq!(
            bridge.export_session(false).await.err().map(|e| e.code),
            Some("forbidden")
        );
        let mut wrong = vector["session"].clone();
        wrong["api_url"] = json!("https://other.example.invalid");
        assert_eq!(
            bridge
                .import_session(wrong.to_string())
                .await
                .err()
                .map(|e| e.code),
            Some("forbidden")
        );
        assert_eq!(
            bridge
                .login_password("invalid".into(), "synthetic-private-password".into(), None)
                .await
                .err()
                .map(|e| e.code),
            Some("authentication")
        );
        let preserved: Value = serde_json::from_str(
            &bridge
                .export_session(true)
                .await
                .unwrap_or_else(|_| panic!("preserved export")),
        )
        .expect("invalid preserved export");
        assert!(
            preserved["session"] == vector["session"],
            "failed login replaced credentials"
        );
        let mut enhanced = vector["options"].clone();
        enhanced["enhanced_privacy"] = json!(true);
        assert_eq!(
            SessionBridge::new(&enhanced.to_string())
                .err()
                .map(|e| e.code),
            Some("invalid_argument")
        );
        assert_eq!(
            bridge
                .consent("invented".into(), vec![])
                .err()
                .map(|e| e.code),
            Some("forbidden")
        );
        let id = bridge
            .start_send("Synthetic private send".into(), None)
            .await
            .unwrap_or_else(|_| panic!("start"));
        let event: Value = serde_json::from_str(
            &bridge
                .next_event(id)
                .await
                .unwrap_or_else(|_| panic!("event")),
        )
        .expect("invalid event");
        assert_eq!(event["error"]["code"], "forbidden");
        bridge.cancel().unwrap_or_else(|_| panic!("cancel"));
        bridge.logout().await.unwrap_or_else(|_| panic!("logout"));
        assert_eq!(
            bridge.export_session(true).await.err().map(|e| e.code),
            Some("authentication")
        );
        bridge.close().await.unwrap_or_else(|_| panic!("close"));
        assert_eq!(
            bridge.list("chats".into()).await.err().map(|e| e.code),
            Some("cancelled")
        );
        results.push(json!({"id":vector["id"],"status":"passed"}));
    }
    assert!(!results.is_empty(), "empty conformance suite");
    println!(
        "{}",
        json!({"capability":capability,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(&raw)),"results":results})
    );
}
