//! Actual Rust SessionBridge one-page conformance; no CLI application invocation.
//! The owned synthetic Python HTTP peer shares exact encrypted vectors with bindings.
//! Peer stdout is a bounded private readiness channel, never a public transcript.
//! Every library result, typed failure, request count and cursor flow is asserted.
//! Managed CI owns execution; source-only checks do not claim this example passed.
use _native::SessionBridge;
use openmates_sdk::ClientIdentity;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    process::{Child, Command, Stdio},
    time::Duration,
};
const CAPABILITY: &str = "session.message-window.v1";
type Check<T> = Result<T, &'static str>;
// Static source checkpoints only: no BindingError message or peer payload is projected.
#[derive(Clone, Copy)]
enum Phase {
    PeerStart,
    ClientSetup,
    SessionImport,
    CursorPreflight,
    CursorAssert,
    CachePreload,
    WindowRead,
    WindowAssert,
    CacheVerify,
    PeerControl,
    PeerStatus,
    Close,
}
impl Phase {
    fn label(self) -> &'static str {
        match self {
            Self::PeerStart => "peer_start",
            Self::ClientSetup => "client_setup",
            Self::SessionImport => "session_import",
            Self::CursorPreflight => "cursor_preflight",
            Self::CursorAssert => "cursor_assert",
            Self::CachePreload => "cache_preload",
            Self::WindowRead => "window_read",
            Self::WindowAssert => "window_assert",
            Self::CacheVerify => "cache_verify",
            Self::PeerControl => "peer_control",
            Self::PeerStatus => "peer_status",
            Self::Close => "close",
        }
    }
    fn source_coordinate(self) -> &'static str {
        match self {
            Self::PeerStart => "run_vector.peer_start",
            Self::ClientSetup => "run_vector.client_setup",
            Self::SessionImport => "run_vector.session_import",
            Self::CursorPreflight => "run_vector.cursor_preflight",
            Self::CursorAssert => "run_vector.cursor_assert",
            Self::CachePreload => "run_vector.cache_preload",
            Self::WindowRead => "run_vector.window_read",
            Self::WindowAssert => "run_vector.window_assert",
            Self::CacheVerify => "run_vector.cache_verify",
            Self::PeerControl => "run_vector.peer_control",
            Self::PeerStatus => "run_vector.peer_status",
            Self::Close => "run_vector.close",
        }
    }
}
fn closed_code(error: &str) -> &'static str {
    match error {
        "cancelled" => "cancelled",
        "conflict" => "conflict",
        "forbidden" => "forbidden",
        "expired" => "expired",
        "authentication" => "authentication",
        "invalid_argument" => "invalid",
        "crypto" => "crypto",
        "protocol" | "library JSON" => "protocol",
        "offline" => "offline",
        "unavailable" => "unavailable",
        "io" => "storage_io",
        "vector timeout" => "timeout",
        "peer launch" | "peer stdout" | "peer readiness" | "peer port" | "peer connect"
        | "peer timeout" | "peer write" | "peer read" | "peer body" | "peer JSON" => "peer_protocol",
        "one-page conformance assertion" | "cursor shape" => "assertion",
        _ => "unclassified",
    }
}
fn vector_id(vector: &Value) -> Check<&str> {
    let id = field(vector, "id")?;
    check(!id.is_empty() && id.len() <= 96 && id.bytes().all(|b|
        b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || b == b'_'))?;
    Ok(id)
}
fn failure_report(raw: &[u8], vector: &Value, phase: Phase, error: &str) -> Check<Value> {
    let id = vector_id(vector)?;
    Ok(json!({"capability":CAPABILITY,"language":"rust","status":"failed",
        "fixtureSha256":format!("{:x}",Sha256::digest(raw)),
        "results":[{"id":id,"status":"failed"}],
        "diagnostic":{"vectorId":id,"phase":phase.label(),"errorCode":closed_code(error),
            "sourceCoordinate":phase.source_coordinate()}}))
}

struct Peer {
    child: Child,
    endpoint: String,
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
fn check(ok: bool) -> Check<()> {
    if ok {
        Ok(())
    } else {
        Err("one-page conformance assertion")
    }
}
fn field<'a>(v: &'a Value, name: &str) -> Check<&'a str> {
    v[name].as_str().ok_or("fixture string")
}
fn json_value(raw: String) -> Check<Value> {
    serde_json::from_str(&raw).map_err(|_| "library JSON")
}
impl Peer {
    fn start(path: &str, vector: &Value) -> Check<Self> {
        let mut child = Command::new(
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()),
        )
        .args([
            "tests/sdk-conformance/message_window_server.py",
            "--fixture",
            path,
            "--vector",
            field(vector, "id")?,
            "--identity",
            "rust",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "peer launch")?;
        let stdout = child.stdout.take().ok_or("peer stdout")?;
        let (send, receive) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let mut raw = String::new();
            let result = BufReader::new(stdout)
                .take(4096)
                .read_line(&mut raw)
                .map(|_| raw);
            let _ = send.send(result);
        });
        let ready = receive.recv_timeout(Duration::from_secs(10));
        let endpoint = ready
            .ok()
            .and_then(Result::ok)
            .and_then(|raw| serde_json::from_str::<Value>(&raw).ok())
            .and_then(|v| v["endpoint"].as_str().map(str::to_owned));
        let Some(endpoint) = endpoint.filter(|s| s.starts_with("http://127.0.0.1:")) else {
            let _ = child.kill();
            let _ = child.wait();
            return Err("peer readiness");
        };
        Ok(Self { child, endpoint })
    }
    fn request(&self, release: bool) -> Check<Value> {
        let port = self
            .endpoint
            .rsplit(':')
            .next()
            .ok_or("peer port")?
            .parse::<u16>()
            .map_err(|_| "peer port")?;
        let mut stream = TcpStream::connect(("127.0.0.1", port)).map_err(|_| "peer connect")?;
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .map_err(|_| "peer timeout")?;
        stream
            .set_write_timeout(Some(Duration::from_secs(3)))
            .map_err(|_| "peer timeout")?;
        let request = if release {
            let body = r#"{"action":"release"}"#;
            format!(
                "POST /__test/control HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            )
        } else {
            "GET /__test/status HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".into()
        };
        stream
            .write_all(request.as_bytes())
            .map_err(|_| "peer write")?;
        let mut raw = String::new();
        stream
            .take(65536)
            .read_to_string(&mut raw)
            .map_err(|_| "peer read")?;
        check(raw.starts_with("HTTP/1.0 200") || raw.starts_with("HTTP/1.1 200"))?;
        serde_json::from_str(raw.split_once("\r\n\r\n").ok_or("peer body")?.1)
            .map_err(|_| "peer JSON")
    }
}
fn assert_window(
    suite: &Value,
    vector: &Value,
    page: &Value,
    expected_scope: Option<&str>,
) -> Check<()> {
    let mut expected = vector["expected_public_paging"].clone();
    check(expected.is_object())?;
    expected["chat"]["messages"] = vector["expected_messages"].clone();
    let mut scope = expected_scope.map(str::to_owned);
    for name in ["startCursor", "endCursor", "oversizedMessageCursor"] {
        if expected[name].is_null() {
            check(page[name].is_null())?;
            continue;
        }
        let actual = page[name].as_object().ok_or("cursor shape")?;
        check(
            actual.len() == 4
                && ["chatId", "scope", "createdAt", "messageId"]
                    .iter()
                    .all(|key| actual.contains_key(*key)),
        )?;
        check(page[name]["chatId"] == suite["protocol"]["chat_id"])?;
        let current = field(&page[name], "scope")?;
        check(
            current.len() == 64
                && current
                    .bytes()
                    .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v)),
        )?;
        if let Some(scope) = &scope {
            check(current == scope)?;
        } else {
            scope = Some(current.to_owned());
        }
        expected[name]["chatId"] = suite["protocol"]["chat_id"].clone();
        expected[name]["scope"] = json!(current);
    }
    check(page == &expected)?;
    check(
        page["payloadBytes"]
            .as_u64()
            .is_some_and(|n| n <= 256 * 1024),
    )
}
async fn run_vector(suite: &Value, vector: &Value, path: &str, phase: &mut Phase) -> Check<Value> {
    *phase = Phase::PeerStart;
    let peer = Peer::start(path, vector)?;
    *phase = Phase::ClientSetup;
    let bridge=SessionBridge::with_identity(&json!({"api_url":peer.endpoint,"app_url":suite["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":vector.get("allow_private_operations").unwrap_or(&suite["allow_private_operations"]).as_bool().ok_or("fixture private policy")?}).to_string(),ClientIdentity::Rust).map_err(|error|error.code)?;
    let outcome=async {
  let mode=field(vector,"mode")?;let id=field(&suite["protocol"],"chat_id")?;
  *phase=Phase::SessionImport;
  if mode!="noauth"{bridge.import_session(json!({"api_url":peer.endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":suite["account"]["master_key"],"hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.map_err(|error|error.code)?;}
  let mut options=vector["options"].clone();let mut expected_scope:Option<String>=None;
  if vector.get("preflight").is_some(){
   *phase=Phase::CursorPreflight;
   let first=json_value(bridge.chat_message_window(id.into(),vector["preflight"].to_string()).await.map_err(|error|error.code)?)?;
   let latest=suite["vectors"].as_array().ok_or("fixture vectors")?.iter().find(|v|v["mode"]=="latest").ok_or("latest fixture")?;
   *phase=Phase::CursorAssert;
   assert_window(suite,latest,&first,None)?;expected_scope=Some(field(&first["startCursor"],"scope")?.to_owned());
   options["direction"]=json!(if mode=="after"{"after"}else{"before"});options["cursor"]=first["startCursor"].clone();
   check(options["cursor"]["scope"].as_str().is_some_and(|s|s.len()==64))?;
   if mode=="forbidden_context"{options["cursor"]["chatId"]=json!("99999999-9999-4999-8999-999999999999");}
   if mode=="wrong_scope"{options["cursor"]["scope"]=json!("0".repeat(64));}
  }
  if mode=="partial_cache"{*phase=Phase::CachePreload;let full=json_value(bridge.open_chat(id.into()).await.map_err(|error|error.code)?)?;check(full["messages"]==vector["expected_cached_messages"])?;}
  *phase=Phase::WindowRead;
  let result=if mode=="cancel"{
   let active=bridge.clone();let identity=id.to_owned();let encoded=options.to_string();
   let pending=tokio::spawn(async move{active.chat_message_window(identity,encoded).await});
   let mut observed=false;for _ in 0..500{if peer.request(false)?["metadata"]==1{observed=true;break;}tokio::time::sleep(Duration::from_millis(5)).await;}
   check(observed)?;*phase=Phase::PeerControl;bridge.cancel().map_err(|error|error.code)?;peer.request(true)?;
   *phase=Phase::WindowRead;pending.await.map_err(|_|"pending page")?
  }else{bridge.chat_message_window(id.into(),options.to_string()).await};
  *phase=Phase::WindowAssert;
  match result {
   Ok(raw)=>{check(vector["expected_error"].is_null())?;let page=json_value(raw)?;assert_window(suite,vector,&page,expected_scope.as_deref())?;},
   Err(error)=>check(vector["expected_error"]==error.code)?,
  }
  if mode=="partial_cache"{*phase=Phase::CacheVerify;let full=json_value(bridge.open_chat(id.into()).await.map_err(|error|error.code)?)?;check(full["messages"]==vector["expected_cached_messages"])?;}
  *phase=Phase::PeerStatus;
  let report=peer.request(false)?;check(report["failure"].is_null()&&report["metadata"]==vector["expected_metadata_requests"]&&report["window"]==vector["expected_window_requests"]&&report["identity"]=="rust")?;
  let checks=report["checks"].as_array().ok_or("peer checks")?;for expected in vector["expected_checks"].as_array().ok_or("fixture checks")?{check(checks.contains(expected))?;}
  Ok(json!({"id":vector["id"],"status":"passed","checks":vector["expected_checks"]}))
 }.await;
    let failed_phase = *phase;
    *phase = Phase::Close;
    let closed = bridge.close().await.map_err(|error| error.code);
    if outcome.is_err() {
        *phase = failed_phase;
    }
    outcome.and_then(|value| {
        closed?;
        Ok(value)
    })
}
async fn run() -> Check<Value> {
    let args: Vec<String> = std::env::args().collect();
    let option = |name| {
        args.iter()
            .position(|arg| arg == name)
            .and_then(|i| args.get(i + 1))
            .ok_or("argument")
    };
    check(option("--capability")? == CAPABILITY)?;
    let path = option("--fixture")?;
    let raw = std::fs::read(path).map_err(|_| "fixture read")?;
    let fixture: Value = serde_json::from_slice(&raw).map_err(|_| "fixture JSON")?;
    let suite = &fixture["capabilities"][CAPABILITY];
    let vectors = suite["vectors"].as_array().ok_or("fixture vectors")?;
    check(!vectors.is_empty())?;
    let mut results = vec![];
    for vector in vectors {
        vector_id(vector)?;
        let mut phase = Phase::PeerStart;
        let result = tokio::time::timeout(Duration::from_secs(20), run_vector(suite, vector, path, &mut phase))
            .await.map_err(|_| "vector timeout").and_then(|value| value);
        match result {
            Ok(value) => results.push(value),
            Err(error) => {
                println!("{}", failure_report(&raw, vector, phase, error)?);
                return Err(error);
            }
        }
    }
    Ok(
        json!({"capability":CAPABILITY,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(raw)),"results":results}),
    )
}
#[tokio::main]
async fn main() {
    match tokio::time::timeout(Duration::from_secs(240), run()).await {
        Ok(Ok(value)) => println!("{value}"),
        _ => {
            eprintln!("Rust one-page library conformance failed");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod diagnostic_tests {
    use super::*;
    #[test]
    fn failed_projection_never_includes_error_prose_or_fixture_contents() {
        let report = failure_report(b"private fixture", &json!({"id":"window-latest"}),
            Phase::WindowAssert, "private token/path/error prose").unwrap();
        assert_eq!(report["diagnostic"], json!({"vectorId":"window-latest",
            "phase":"window_assert","errorCode":"unclassified",
            "sourceCoordinate":"run_vector.window_assert"}));
        assert_eq!(report["fixtureSha256"], json!(format!("{:x}",Sha256::digest(b"private fixture"))));
        assert_eq!(report["results"], json!([{"id":"window-latest","status":"failed"}]));
        assert_eq!(report.as_object().unwrap().len(), 6);
        assert!(!report.to_string().contains("private"));
    }
    #[test]
    fn malformed_or_unbounded_vector_identifier_is_not_published() {
        for id in ["".to_owned(), "PRIVATE/path".to_owned(), "x".repeat(97)] {
            assert!(failure_report(b"fixture", &json!({"id":id}), Phase::PeerStart, "offline").is_err());
        }
    }
}
