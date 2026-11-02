//! Real bridge/SDK WebSocket protocol exercised only against an in-process unit fixture.
use _native::SessionBridge;
use futures_util::{SinkExt, StreamExt};
use openmates_sdk::{ClientIdentity, crypto};
use serde_json::{Value, json};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    time::{Duration, timeout},
};
async fn frame(socket: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>) -> Value {
    loop {
        let message = socket.next().await.expect("frame").expect("socket");
        if message.is_text() {
            return serde_json::from_str(message.to_text().unwrap()).expect("json");
        }
    }
}
async fn send(
    socket: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,
    kind: &str,
    payload: Value,
) {
    socket
        .send(tokio_tungstenite::tungstenite::Message::Text(
            json!({"type":kind,"payload":payload}).to_string().into(),
        ))
        .await
        .expect("send")
}
#[tokio::test]
async fn encrypted_admission_stream_events_and_cooperative_cancel_reach_the_sdk() {
    timeout(Duration::from_secs(10),async {
        let listener=TcpListener::bind("127.0.0.1:0").await.unwrap();let endpoint=format!("http://{}",listener.local_addr().unwrap());
        let server=tokio::spawn(async move {
            // The SDK validates twice before the socket: once to learn the owner of
            // the imported session (prepare_validated_scoped_saved_send) and once
            // for a fresh WebSocket token immediately before connecting.
            for _ in 0..2 {
            let (mut http,_)=listener.accept().await.unwrap();let mut data=vec![];
            loop {let mut buffer=[0;8192];let n=http.read(&mut buffer).await.unwrap();assert!(n>0);data.extend_from_slice(&buffer[..n]);if let Some(end)=data.windows(4).position(|b|b==b"\r\n\r\n"){let headers=String::from_utf8_lossy(&data[..end]).to_ascii_lowercase();let length=headers.lines().find_map(|line|line.strip_prefix("content-length:").map(|v|v.trim().parse::<usize>().unwrap())).unwrap_or(0);if data.len()>=end+4+length{break}}}
            let request=String::from_utf8(data).unwrap();assert!(request.starts_with("POST /v1/auth/session HTTP/1.1\r\n"));assert!(request.to_ascii_lowercase().contains("x-openmates-sdk: npm\r\n"));
            let body=r#"{"success":true,"ws_token":"synthetic-ws-token","user":{"id":"synthetic-owner"}}"#;http.write_all(format!("HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",body.len(),body).as_bytes()).await.unwrap();drop(http);
            }
            let (tcp,_)=listener.accept().await.unwrap();let mut socket=tokio_tungstenite::accept_async(tcp).await.unwrap();
            loop {let event=frame(&mut socket).await;match event["type"].as_str().unwrap(){
                "native_client_lifecycle"=>{assert_eq!(event["payload"]["client_type"],"npm");assert_eq!(event["payload"]["interactive"],false);assert_eq!(event["payload"]["is_foreground"],true);},
                "set_active_chat"=>{},
                "personal_send_context_snapshot"=>{let p=&event["payload"];send(&mut socket,"personal_send_context_snapshot_result",json!({"request_id":p["request_id"],"turn_id":p["turn_id"],"success":true,"unchanged":false,"receipt_id":"synthetic-receipt","privacy_generation":1,"personal_memories":{"memories":[]},"project_candidates":[]})).await;},
                "chat_turn_admit"=>{
                    let p=&event["payload"];assert!(!p.to_string().contains("person@example.invalid"),"raw PII leaked into admission");assert!(p["inference_request"].get("model").is_none());assert!(p["inference_request"].get("provider").is_none());
                    let master:[u8;32]=std::array::from_fn(|i|i as u8);let chat_key=crypto::decrypt_bytes(p["encrypted_chat_key"].as_str().unwrap(),&master).unwrap();let chat_key:[u8;32]=chat_key.as_slice().try_into().unwrap();let plain=crypto::decrypt_combined(p["encrypted_user_message"]["encrypted_content"].as_str().unwrap(),&chat_key).unwrap();assert!(!plain.contains("person@example.invalid"));assert_eq!(plain,p["inference_request"]["message"]["content"]);
                    send(&mut socket,"chat_turn_preflight_ack",json!({"turn_id":p["turn_id"],"preflight_id":"synthetic-preflight","committed_messages_v":1})).await;
                    send(&mut socket,"chat_message_confirmed",json!({"chat_id":p["chat_id"],"message_id":p["message_id"],"new_messages_v":1})).await;
                    send(&mut socket,"ai_task_initiated",json!({"chat_id":p["chat_id"],"user_message_id":p["message_id"],"task_id":"synthetic-task"})).await;
                    send(&mut socket,"ai_message_update",json!({"chat_id":p["chat_id"],"user_message_id":p["message_id"],"task_id":"synthetic-task","full_content_so_far":"Synthetic native stream","is_final_chunk":false})).await;
                },
                "cancel_ai_task"=>{assert_eq!(event["payload"]["task_id"],"synthetic-task");break},
                _=>panic!("unexpected unit-fixture frame"),
            }}
        });
        let bridge=SessionBridge::with_identity(&json!({"api_url":endpoint,"app_url":null,"enhanced_privacy":false,"allow_private_operations":true}).to_string(),ClientIdentity::Npm).unwrap_or_else(|_|panic!("construct"));
        bridge.import_session(json!({"api_url":endpoint,"session_id":"synthetic-session","cookies":{},"ws_token":null,"master_key":"AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=","hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.unwrap_or_else(|_|panic!("import"));
        let id=bridge.start_send("Please email person@example.invalid".into(),None).await.unwrap_or_else(|_|panic!("start"));let mut seen=vec![];
        loop {let event:Value=serde_json::from_str(&bridge.next_event(id.clone()).await.unwrap_or_else(|_|panic!("event"))).unwrap();if let Some(update)=event["update"].as_object(){seen.extend(update.keys().cloned());if update.contains_key("Content"){assert_eq!(update["Content"]["content"],"Synthetic native stream");bridge.cancel().unwrap_or_else(|_|panic!("cancel"));}}
            if event["type"]=="error"{assert_eq!(event["error"]["code"],"cancelled");break}
        }
        for kind in ["Started","Submitted","Admitted","Content"]{assert!(seen.iter().any(|v|v==kind),"missing stream lifecycle update")};server.await.unwrap();bridge.close().await.unwrap_or_else(|_|panic!("close"));
    }).await.expect("bounded unit fixture");
}
