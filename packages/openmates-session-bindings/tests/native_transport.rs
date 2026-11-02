use _native::SessionBridge;
use openmates_sdk::ClientIdentity;
use serde_json::{Value, json};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};
#[tokio::test]
async fn language_identity_and_apps_list_use_the_rust_transport_directly() {
    for (identity, header) in [(ClientIdentity::Npm, "npm"), (ClientIdentity::Pip, "pip")] {
        let server = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint = format!("http://{}", server.local_addr().unwrap());
        let task = tokio::spawn(async move {
            let (mut socket, _) = server.accept().await.unwrap();
            let mut request = vec![0; 16384];
            let count = socket.read(&mut request).await.unwrap();
            let request = String::from_utf8(request[..count].to_vec()).unwrap();
            assert!(
                request.starts_with("GET /v1/apps/metadata?include_unavailable=true HTTP/1.1\r\n")
            );
            assert!(
                request
                    .to_ascii_lowercase()
                    .contains(&format!("x-openmates-sdk: {header}\r\n"))
            );
            assert!(!request.contains("synthetic-key-material"));
            let body = r#"{"apps":[{"id":"web","name":"Web","description":"Synthetic metadata","skills":[]}]}"#;
            socket.write_all(format!("HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",body.len(),body).as_bytes()).await.unwrap();
        });
        let options=json!({"api_url":endpoint,"app_url":null,"enhanced_privacy":false,"allow_private_operations":false}).to_string();
        let bridge = SessionBridge::with_identity(&options, identity)
            .unwrap_or_else(|_| panic!("construct"));
        bridge.import_session(json!({"api_url":endpoint,"session_id":"synthetic-session","cookies":{},"ws_token":null,"master_key":"AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=","hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.unwrap_or_else(|_|panic!("import"));
        let result: Value = serde_json::from_str(
            &bridge
                .list("apps".into())
                .await
                .unwrap_or_else(|_| panic!("list")),
        )
        .unwrap();
        assert_eq!(result[0]["id"], "web");
        task.await.unwrap();
        bridge.close().await.unwrap_or_else(|_| panic!("close"));
    }
}
