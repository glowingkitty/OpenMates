//! CI-only actual native executable → isolated loopback anonymous protocol.
//! Synthetic SSE response; no product service, credentials or AI inference.
use serde_json::{Value, json};
use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Command, Output},
    time::Duration,
};

fn cli(api: &str, state: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_openmates"))
        .args([
            "--api-url",
            api,
            "--state-dir",
            state.to_str().unwrap(),
            "--encrypted-vault",
        ])
        .args(args)
        .env_remove("OPENMATES_API_KEY")
        .env_remove("OPENMATES_PROFILE")
        .env_remove("OPENMATES_REQUIRE_TRUSTED_ACCOUNT")
        .env_remove("OPENMATES_ACCOUNT_GUARD")
        .env_remove("OPENMATES_APP_URL")
        .stdin(std::process::Stdio::null())
        .output()
        .unwrap()
}
fn request(socket: &mut TcpStream) -> (String, Value) {
    socket
        .set_read_timeout(Some(Duration::from_secs(10)))
        .unwrap();
    let mut bytes = vec![];
    let mut part = [0; 4096];
    let end = loop {
        let n = socket.read(&mut part).unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&part[..n]);
        if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
            break end + 4;
        }
    };
    let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
    let length = headers
        .lines()
        .filter_map(|v| v.split_once(':'))
        .find(|(key, _)| key.eq_ignore_ascii_case("content-length"))
        .map(|(_, value)| value.trim().parse::<usize>().unwrap())
        .unwrap_or(0);
    while bytes.len() < end + length {
        let n = socket.read(&mut part).unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&part[..n]);
    }
    let body = if length == 0 {
        Value::Null
    } else {
        serde_json::from_slice(&bytes[end..end + length]).unwrap()
    };
    (headers, body)
}
fn respond(socket: &mut TcpStream, kind: &str, body: &str) {
    write!(socket,"HTTP/1.1 200 OK\r\nContent-Type: {kind}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).unwrap();
    socket.flush().unwrap();
}
fn anonymous_id(headers: &str) -> String {
    let lower = headers.to_ascii_lowercase();
    for name in ["cookie", "authorization", "origin", "x-openmates-device-id"] {
        assert!(!lower.contains(&format!("\r\n{name}:")));
    }
    assert!(lower.contains("x-openmates-sdk: cli"));
    let id = headers
        .lines()
        .filter_map(|v| v.split_once(':'))
        .find(|(key, _)| key.eq_ignore_ascii_case("x-openmates-anonymous-id"))
        .unwrap()
        .1
        .trim()
        .to_owned();
    assert_eq!(uuid::Uuid::parse_str(&id).unwrap().get_version_num(), 4);
    id
}
fn files(directory: &Path, out: &mut Vec<PathBuf>) {
    for entry in std::fs::read_dir(directory).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            files(&path, out)
        } else {
            out.push(path)
        }
    }
}
#[test]
#[ignore = "requires isolated GitHub CI; starts only a synthetic loopback fixture"]
// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible,cli.surface.semantic-parity
fn native_anonymous_route_has_stable_public_identity_without_conversation_storage() {
    assert_eq!(
        std::env::var("CI").as_deref(),
        Ok("true"),
        "isolated GitHub CI only"
    );
    let temp = tempfile::tempdir().unwrap();
    let state = temp.path().join("native-profile");
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = std::thread::spawn(move || {
        let mut identities = vec![];
        for _ in 0..2 {
            let (mut socket, _) = listener.accept().unwrap();
            let (headers, _) = request(&mut socket);
            assert!(headers.starts_with("GET /v1/anonymous/free-usage/status "));
            let id = anonymous_id(&headers);
            identities.push(id.clone());
            respond(
                &mut socket,
                "application/json",
                r#"{"active":true,"can_send_text":true}"#,
            );
            drop(socket);
            let (mut socket, _) = listener.accept().unwrap();
            let (headers, body) = request(&mut socket);
            assert_eq!(anonymous_id(&headers), id);
            assert!(headers.starts_with("POST /v1/anonymous/chat/stream "));
            assert_eq!(body["anonymous_id"], id);
            assert_eq!(body["plaintext_message"], "Synthetic anonymous question");
            assert_eq!(body["message_history"], json!([]));
            let chat = &body["client_chat_id"];
            let user = &body["client_message_id"];
            let data=[
                json!({"type":"ai_task_initiated","chat_id":chat,"user_message_id":user,"ai_task_id":"fixture-task"}),
                json!({"type":"ai_message_chunk","chat_id":chat,"user_message_id":user,"task_id":"fixture-task","message_id":"fixture-answer","sequence":1,"full_content_so_far":"Synthetic answer 界","is_final_chunk":true}),
                json!({"type":"ai_task_ended","chatId":chat,"taskId":"fixture-task","status":"completed"}),
            ].into_iter().map(|v|format!("data: {v}\n\n")).collect::<String>();
            respond(&mut socket, "text/event-stream", &data);
        }
        listener.set_nonblocking(true).unwrap();
        std::thread::sleep(Duration::from_millis(100));
        assert_eq!(
            listener.accept().unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock
        );
        identities
    });
    for command in ["new", "incognito"] {
        let result = cli(
            &api,
            &state,
            &["chats", command, "Synthetic anonymous question", "--json"],
        );
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        let value: Value = serde_json::from_slice(&result.stdout).unwrap();
        assert_eq!(value["status"], "completed");
        assert_eq!(value["assistant"], "Synthetic answer 界");
        assert!(value["chatId"].as_str().unwrap().starts_with("anonymous-"));
        assert_eq!(value["taskEvents"], json!([]));
        assert_eq!(value["pendingTaskUpdateJobs"], json!([]));
    }
    let rejected = cli(
        &api,
        &state,
        &[
            "chats",
            "send",
            "must not dispatch",
            "--chat",
            "saved",
            "--json",
        ],
    );
    assert_eq!(rejected.status.code(), Some(1));
    let error: Value = serde_json::from_slice(&rejected.stderr).unwrap();
    assert_eq!(error["error"]["code"], "native_command_unsupported");
    let identities = server.join().unwrap();
    assert_eq!(identities[0], identities[1]);
    let mut written = vec![];
    files(&state, &mut written);
    let ids: Vec<_> = written
        .iter()
        .filter(|p| p.file_name().unwrap() == "anonymous-id")
        .collect();
    assert_eq!(ids.len(), 1);
    assert_eq!(std::fs::read_to_string(ids[0]).unwrap(), identities[0]);
    assert!(
        !written
            .iter()
            .any(|file| file.file_name().unwrap() == "sdk-device-id"),
        "public usage identity must not create an account/device identity"
    );
    for file in written {
        let name = file.file_name().unwrap().to_str().unwrap();
        assert!(
            name.ends_with(".lock") || name == "anonymous-id",
            "unexpected account/transcript state: {name}"
        );
    }
}
