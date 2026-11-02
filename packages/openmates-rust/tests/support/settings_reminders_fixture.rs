//! Synthetic loopback-only fixture peer. No product requests or inference.
use serde_json::Value;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::JoinHandle,
};
pub async fn peer(case: &Value) -> (String, JoinHandle<usize>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let responses = case["responses"].as_array().unwrap().clone();
    let expected = case["expected"]["requests"].as_u64().unwrap() as usize;
    let task = tokio::spawn(async move {
        let mut cookie = "fixture";
        for response in responses.iter().take(expected) {
            let (mut socket, _) =
                tokio::time::timeout(std::time::Duration::from_secs(70), listener.accept())
                    .await
                    .unwrap()
                    .unwrap();
            let mut request = Vec::new();
            while !request.ends_with(b"\r\n\r\n") {
                let mut byte = [0];
                assert_eq!(socket.read(&mut byte).await.unwrap(), 1);
                request.push(byte[0]);
                assert!(request.len() <= 8192);
            }
            let request = String::from_utf8(request).unwrap().to_ascii_lowercase();
            assert!(request.starts_with("get /v1/settings/reminders http/1.1\r\n"));
            assert!(request.contains(&format!("\r\ncookie: auth_refresh_token={cookie}\r\n")));
            for forbidden in [
                "authorization:",
                "x-team-id:",
                "x-openmates-team",
                "content-type:",
                "content-length:",
            ] {
                assert!(!request.contains(forbidden), "unexpected settings header");
            }
            let body = response["body"].as_str().unwrap();
            let headers = response["headers"].as_array().unwrap();
            let mut head = format!(
                "HTTP/1.1 {} Fixture\r\nConnection: close\r\n",
                response["status"].as_u64().unwrap()
            );
            if !headers.iter().any(|h| {
                h[0].as_str()
                    .unwrap()
                    .eq_ignore_ascii_case("Content-Length")
            }) {
                head.push_str(&format!("Content-Length: {}\r\n", body.len()));
            }
            for header in headers {
                let name = header[0].as_str().unwrap();
                let value = header[1].as_str().unwrap();
                assert!(!name.contains(['\r', '\n']) && !value.contains(['\r', '\n']));
                head.push_str(&format!("{name}: {value}\r\n"));
                if name.eq_ignore_ascii_case("Set-Cookie")
                    && value.starts_with("auth_refresh_token=rotated;")
                {
                    cookie = "rotated";
                }
            }
            head.push_str("\r\n");
            socket.write_all(head.as_bytes()).await.unwrap();
            let _ = socket.write_all(body.as_bytes()).await; // guards may close before body
        }
        // Keep the listener until this bounded negative observation completes.
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(100), listener.accept())
                .await
                .is_err(),
            "unexpected extra request"
        );
        expected
    });
    (origin, task)
}

/// Response gate used only by the physical in-flight cancellation vectors.
/// Header/whole429 bytes are sent before `ready`; the caller cancels its own A,
/// then releases actual body completion. No fake production timer or SDK import.
pub struct Control {
    pub ready: tokio::sync::oneshot::Receiver<()>,
    pub release: tokio::sync::oneshot::Sender<()>,
}
pub async fn controlled_peer(case:&Value)->(String,JoinHandle<usize>,Option<Control>) {
    let action=case["action"].as_str().unwrap_or("");
    if action!="cancel_body" && action!="cancel_retry" {
        let (origin,peer)=peer(case).await;return (origin,peer,None);
    }
    let listener=TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin=format!("http://{}",listener.local_addr().unwrap());
    let (ready_tx,ready)=tokio::sync::oneshot::channel();
    let (release,release_rx)=tokio::sync::oneshot::channel();
    let response=case["responses"][0].clone();let body_gate=action=="cancel_body";
    let task=tokio::spawn(async move {
        let (mut socket,_)=tokio::time::timeout(std::time::Duration::from_secs(10),listener.accept()).await.unwrap().unwrap();
        let mut bytes=Vec::new();
        while !bytes.ends_with(b"\r\n\r\n") {let mut byte=[0];assert_eq!(socket.read(&mut byte).await.unwrap(),1);bytes.push(byte[0]);assert!(bytes.len()<=8192);}
        let request=String::from_utf8(bytes).unwrap().to_ascii_lowercase();
        assert!(request.starts_with("get /v1/settings/reminders http/1.1\r\n"));
        assert!(request.contains("\r\ncookie: auth_refresh_token=fixture\r\n"));
        for forbidden in ["authorization:","x-team-id:","x-openmates-team","content-type:","content-length:"] {assert!(!request.contains(forbidden));}
        let body=response["body"].as_str().unwrap();
        let mut head=format!("HTTP/1.1 {} Fixture\r\nContent-Length: {}\r\nConnection: close\r\n",response["status"].as_u64().unwrap(),body.len());
        for h in response["headers"].as_array().unwrap(){head.push_str(&format!("{}: {}\r\n",h[0].as_str().unwrap(),h[1].as_str().unwrap()));}
        head.push_str("\r\n");socket.write_all(head.as_bytes()).await.unwrap();
        if !body_gate {socket.write_all(body.as_bytes()).await.unwrap();}
        ready_tx.send(()).unwrap();
        tokio::time::timeout(std::time::Duration::from_secs(10),release_rx).await.unwrap().unwrap();
        if body_gate {socket.write_all(body.as_bytes()).await.unwrap();}
        drop(socket);
        assert!(tokio::time::timeout(std::time::Duration::from_millis(100),listener.accept()).await.is_err(),"cancelled A dispatched another request");
        1
    });
    (origin,task,Some(Control{ready,release}))
}
