//! Actual Rust SessionBridge bounded saved-read conformance; no CLI application invocation.
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
const CAPABILITY: &str = "session.saved-chat-read.v1";
type Check<T> = Result<T, &'static str>;
// Static labels only; never project a BindingError message or peer payload.
#[derive(Clone, Copy)]
enum Phase {
    PeerStart,
    ClientSetup,
    SessionImport,
    CursorPreflight,
    CursorAssert,
    CachePreload,
    BoundedRead,
    BoundedAssert,
    ExactRead,
    ExactAssert,
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
            Self::BoundedRead => "bounded_read",
            Self::BoundedAssert => "bounded_assert",
            Self::ExactRead => "exact_read",
            Self::ExactAssert => "exact_assert",
            Self::CacheVerify => "cache_verify",
            Self::PeerControl => "peer_control",
            Self::PeerStatus => "peer_status",
            Self::Close => "close",
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
        | "peer timeout" | "peer write" | "peer read" | "peer body" | "peer JSON" => {
            "peer_protocol"
        }
        "bounded saved-read conformance assertion" | "cursor shape" => "assertion",
        _ => "unclassified",
    }
}
fn vector_id(vector: &Value) -> Check<&str> {
    let id = field(vector, "id")?;
    check(
        !id.is_empty()
            && id.len() <= 96
            && id
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || b == b'_'),
    )?;
    Ok(id)
}
fn failure_report(raw: &[u8], vector: &Value, phase: Phase, error: &str) -> Check<Value> {
    let id = vector_id(vector)?;
    Ok(
        json!({"capability":CAPABILITY,"language":"rust","status":"failed",
 "fixtureSha256":format!("{:x}",Sha256::digest(raw)),"results":[{"id":id,"status":"failed"}],
 "diagnostic":{"vectorId":id,"phase":phase.label(),"errorCode":closed_code(error)}}),
    )
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
        Err("bounded saved-read conformance assertion")
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
            "tests/sdk-conformance/saved_chat_read_server.py",
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
            .is_some_and(|n| n <= 5 * 256 * 1024),
    )
}
// Public full-read parity. This example cannot access crate-private opaque
// output; real Rust in-flight cancellation plus the seven required private
// final-lane unit tests cover its boundary without adding a public test helper.
async fn assert_full_read(bridge: &SessionBridge, suite: &Value, vector: &Value, peer: &Peer, phase: &mut Phase) -> Check<()> {
    let id=field(&suite["protocol"],"chat_id")?;
    *phase=Phase::BoundedRead;
    let result=if vector["full_action"]=="inflight_cancel" {
        let active=bridge.clone();let identity=id.to_owned();
        let pending=tokio::spawn(async move {active.open_chat(identity).await});
        let mut observed=false;
        for _ in 0..500 {if peer.request(false)?["metadata"]==1 {observed=true;break;}tokio::time::sleep(Duration::from_millis(5)).await;}
        check(observed)?;*phase=Phase::PeerControl;
        bridge.cancel().map_err(|error|error.code)?;peer.request(true)?;
        *phase=Phase::BoundedRead;pending.await.map_err(|_|"pending full read")?
    } else {bridge.open_chat(id.into()).await};
    *phase=Phase::BoundedAssert;
    match result {
        Ok(raw)=>{check(vector["expected_error"].is_null())?;check(json_value(raw)?==vector["full_expected"])?;},
        Err(error)=>check(vector["expected_error"]==error.code).map_err(|_|error.code)?,
    }
    *phase=Phase::PeerStatus;
    let report=peer.request(false)?;
    let counts=vector.get("expected_counts_by_language").and_then(|v|v.get("rust"));
    let expected_metadata=counts.map(|v|&v["metadata"]).unwrap_or(&vector["expected_metadata_requests"]);
    let expected_window=counts.map(|v|&v["window"]).unwrap_or(&vector["expected_window_requests"]);
    let requests=vector.get("requests_by_language").and_then(|v|v.get("rust")).unwrap_or(&vector["requests"]);
    check(report["failure"].is_null()&&report["identity"]=="rust")?;
    check(&report["metadata"]==expected_metadata && &report["window"]==expected_window&&report["exact"]==vector["expected_exact_requests"])?;
    check(report["consumed"].as_u64()==Some(requests.as_array().ok_or("full planned requests")?.len() as u64))?;
    let checks=report["checks"].as_array().ok_or("full peer checks")?;
    for expected in vector["expected_checks"].as_array().ok_or("full fixture checks")? {check(checks.contains(expected))?;}
    Ok(())
}

async fn assert_details_read(bridge: &SessionBridge, suite: &Value, vector: &Value, peer: &Peer, phase: &mut Phase) -> Check<()> {
    let id=field(&suite["protocol"],"chat_id")?;
    *phase=Phase::BoundedRead;
    let result=if vector["details_action"]=="inflight_cancel" {
        let active=bridge.clone();let identity=id.to_owned();let options=vector["details_options"].to_string();
        let pending=tokio::spawn(async move {active.chat_details(identity,options).await});
        let mut observed=false;
        for _ in 0..500 {if peer.request(false)?[vector.get("cancel_barrier").and_then(Value::as_str).unwrap_or("metadata")]==1 {observed=true;break;}tokio::time::sleep(Duration::from_millis(5)).await;}
        check(observed)?;*phase=Phase::PeerControl;
        bridge.cancel().map_err(|error|error.code)?;peer.request(true)?;
        *phase=Phase::BoundedRead;pending.await.map_err(|_|"pending full read")?
    } else {bridge.chat_details(id.into(),vector["details_options"].to_string()).await};
    *phase=Phase::BoundedAssert;
    match result {
        Ok(raw)=>{check(vector["expected_error"].is_null())?;
          if vector.get("expected_draft_utf16").is_some()||vector.get("expected_pii_utf16").is_some()||vector.get("semantic_pii").is_some(){
            let mut read:openmates_sdk::client::chat_details::ChatDetailsRead=serde_json::from_str(&raw).map_err(|_|"library JSON")?;
            let mut expected=vector["expected_details"].clone();
            if let Some(units)=vector.get("expected_draft_utf16").and_then(Value::as_array){
                let leaf=format!("\"{}\"",units.iter().map(|n|format!("\\u{:04x}",n.as_u64().unwrap())).collect::<String>());
                check(read.chat.draft_preview.as_ref().ok_or("preview leaf")?.encoded_json().map_err(|_|"library JSON")?==leaf)?;read.chat.draft_preview=None;
            }
            if let Some(pii)=vector.get("expected_pii_utf16"){
                let index=pii["index"].as_u64().ok_or("pii index")? as usize;
                let leaf=format!("[\"{}\"]",pii["units"].as_array().ok_or("pii units")?.iter().map(|n|format!("\\u{:04x}",n.as_u64().unwrap())).collect::<String>());
                check(read.messages[index].pii_mappings.as_ref().ok_or("pii leaf")?.encoded_json().map_err(|_|"library JSON")?==leaf)?;read.messages[index].pii_mappings=None;
                expected["messages"][index].as_object_mut().ok_or("pii message")?.remove("piiMappings");
            }
            if let Some(pii)=vector.get("semantic_pii"){
                let index=pii["message_index"].as_u64().ok_or("semantic pii index")? as usize;
                let expected_sdk:openmates_sdk::client::chat_details::ChatDetailsJson=serde_json::from_str(field(pii,"sdk_json")?).map_err(|_|"library JSON")?;
                let expected_cli:openmates_sdk::client::chat_details::ChatDetailsJson=serde_json::from_str(field(pii,"cli_json")?).map_err(|_|"library JSON")?;
                let actual=read.messages[index].pii_mappings.as_ref().ok_or("semantic pii")?;
                check(actual.value()==expected_sdk.value())?;
                let cli:openmates_sdk::client::chat_details::ChatDetailsJson=serde_json::from_str(&actual.encoded_json().map_err(|_|"library JSON")?).map_err(|_|"library JSON")?;
                check(cli.value()==expected_cli.value())?;
                read.messages[index].pii_mappings=None;expected["messages"][index].as_object_mut().ok_or("semantic message")?.remove("piiMappings");
            }
            check(serde_json::to_value(&read).map_err(|_|"library JSON")?==expected)?;
          }else{check(json_value(raw)?==vector["expected_details"])?;}
        },
        Err(error)=>check(vector["expected_error"]==error.code).map_err(|_|error.code)?,
    }
    *phase=Phase::PeerStatus;
    let report=peer.request(false)?;
    let counts=vector.get("expected_counts_by_language").and_then(|v|v.get("rust"));
    let expected_metadata=counts.map(|v|&v["metadata"]).unwrap_or(&vector["expected_metadata_requests"]);
    let expected_window=counts.map(|v|&v["window"]).unwrap_or(&vector["expected_window_requests"]);
    let requests=vector.get("requests_by_language").and_then(|v|v.get("rust")).unwrap_or(&vector["requests"]);
    check(report["failure"].is_null()&&report["identity"]=="rust")?;
    check(&report["metadata"]==expected_metadata && &report["window"]==expected_window&&report["exact"]==vector["expected_exact_requests"])?;
    check(report["consumed"].as_u64()==Some(requests.as_array().ok_or("full planned requests")?.len() as u64))?;
    check(report["details_embeds"]==counts.map(|v|&v["details_embeds"]).unwrap_or(&vector["expected_embed_requests"]).clone())?;
    let checks=report["checks"].as_array().ok_or("full peer checks")?;
    for expected in vector["expected_checks"].as_array().ok_or("full fixture checks")? {check(checks.contains(expected))?;}
    Ok(())
}

async fn run_vector(suite: &Value, vector: &Value, path: &str, phase: &mut Phase) -> Check<Value> {
    *phase = Phase::PeerStart;
    let peer = Peer::start(path, vector)?;
    *phase = Phase::ClientSetup;
    let bridge=SessionBridge::with_identity(&json!({"api_url":peer.endpoint,"app_url":suite["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":vector.get("allow_private_operations").unwrap_or(&suite["allow_private_operations"]).as_bool().ok_or("fixture private policy")?}).to_string(),ClientIdentity::Rust).map_err(|error|error.code)?;
    let outcome=async {
  let mode=field(vector,"mode")?;let id=field(&suite["protocol"],"chat_id")?;
  *phase=Phase::SessionImport;
  if mode!="noauth"&&vector["full_action"]!="noauth"&&vector["details_action"]!="noauth"{bridge.import_session(json!({"api_url":peer.endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":suite["account"]["master_key"],"hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":vector.get("team_id").unwrap_or(&Value::Null)}).to_string()).await.map_err(|error|error.code)?;}
  if mode=="details" {
   assert_details_read(&bridge,suite,vector,&peer,phase).await?;
   return Ok(json!({"id":vector["id"],"status":"passed","checks":vector["expected_checks"],"detailsBoundary":"public-rich-read-or-inflight-cancel"}));
  }
  if mode=="full" {
   assert_full_read(&bridge,suite,vector,&peer,phase).await?;
   return Ok(json!({"id":vector["id"],"status":"passed","checks":vector["expected_checks"],"fullReadBoundary":"public-full-read-or-inflight-cancel"}));
  }
  let mut options=vector["options"].clone();let mut expected_scope:Option<String>=None;
  if vector.get("preflight").is_some(){
   *phase=Phase::CursorPreflight;
   let first=json_value(bridge.saved_chat_read(id.into(),vector["preflight"].to_string()).await.map_err(|error|error.code)?)?;
   let preflight=json!({"expected_public_paging":vector["preflight_expected"],"expected_messages":vector["preflight_expected"]["chat"]["messages"]});
   *phase=Phase::CursorAssert;
   assert_window(suite,&preflight,&first,None)?;expected_scope=Some(field(&first["startCursor"],"scope")?.to_owned());
   options[if mode=="after"{"after"}else{"before"}]=first["startCursor"].clone();
  }
  if mode=="partial_cache"{*phase=Phase::CachePreload;let full=json_value(bridge.open_chat(id.into()).await.map_err(|error|error.code)?)?;check(full["messages"]==vector["expected_cached_messages"])?;}
  *phase=Phase::BoundedRead;
  let result=if mode=="cancel"{
   let active=bridge.clone();let identity=id.to_owned();let encoded=options.to_string();
   let pending=tokio::spawn(async move{active.saved_chat_read(identity,encoded).await});
   let mut observed=false;for _ in 0..500{if peer.request(false)?["metadata"]==1{observed=true;break;}tokio::time::sleep(Duration::from_millis(5)).await;}
   check(observed)?;*phase=Phase::PeerControl;bridge.cancel().map_err(|error|error.code)?;peer.request(true)?;
   *phase=Phase::BoundedRead;pending.await.map_err(|_|"pending page")?
  }else{bridge.saved_chat_read(id.into(),options.to_string()).await};
  *phase=Phase::BoundedAssert;
  match result {
   Ok(raw)=>{check(vector["expected_error"].is_null())?;let page=json_value(raw)?;assert_window(suite,vector,&page,expected_scope.as_deref())?;if mode == "exact" {
                    let mut cursor=page["oversizedMessageCursor"].clone();
                    if vector["exactCursorMutation"]=="scope" { cursor["scope"]=json!("0".repeat(64)); }
                    if vector["exactCursorMutation"]=="chat" { cursor["chatId"]=json!("99999999-9999-4999-8999-999999999999"); }
                    let encoded=json!({"cursor":cursor,"contentMode":"stored"}).to_string();
                    *phase=Phase::ExactRead;
                    let exact=if vector["exactAction"]=="cancel" {
                        let active=bridge.clone();let identity=id.to_owned();
                        let pending=tokio::spawn(async move{active.saved_chat_exact_message(identity,encoded).await});
                        let mut observed=false;for _ in 0..500 { if peer.request(false)?["metadata"]==2 { observed=true;break; }tokio::time::sleep(Duration::from_millis(5)).await; }
                        check(observed)?;*phase=Phase::PeerControl;bridge.cancel().map_err(|error|error.code)?;peer.request(true)?;
                        *phase=Phase::ExactRead;pending.await.map_err(|_|"pending exact")?
                    }else{bridge.saved_chat_exact_message(id.into(),encoded).await};
                    *phase=Phase::ExactAssert;
                    match exact {
                        Ok(raw)=>{check(vector["exact_expected_error"].is_null())?;check(json_value(raw)?==vector["exact_expected"])?;},
                        Err(error)=>check(vector["exact_expected_error"]==error.code).map_err(|_|error.code)?,
                    }
                }},
   Err(error)=>check(vector["expected_error"]==error.code).map_err(|_|error.code)?,
  }
  if mode=="partial_cache"{*phase=Phase::CacheVerify;let full=json_value(bridge.open_chat(id.into()).await.map_err(|error|error.code)?)?;check(full["messages"]==vector["expected_cached_messages"])?;}
  *phase=Phase::PeerStatus;
  let report=peer.request(false)?;check(report["exact"]==vector["expected_exact_requests"]&&report["consumed"].as_u64()==Some(vector["requests"].as_array().ok_or("planned requests")?.len() as u64))?;check(report["failure"].is_null()&&report["metadata"]==vector["expected_metadata_requests"]&&report["window"]==vector["expected_window_requests"]&&report["identity"]=="rust")?;
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
        let mut phase = Phase::PeerStart;
        // Validate the fixture identifier before executing or publishing it.
        vector_id(vector)?;
        let result = tokio::time::timeout(
            Duration::from_secs(20),
            run_vector(suite, vector, path, &mut phase),
        )
        .await
        .map_err(|_| "vector timeout")
        .and_then(|value| value);
        match result {
            Ok(value) => results.push(value),
            Err(error) => {
                // Reuse the trusted driver's existing failed-result contract.
                // Success still emits exactly its single unchanged JSON object.
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
            eprintln!("Rust bounded saved-read library conformance failed");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod diagnostic_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
    #[test]
    fn failure_projection_contains_only_closed_identity_phase_and_code() {
        let vector = json!({"id":"default-30-from-65","secret":"NEVER_EXPORT_PRIVATE_SESSION"});
        let value = failure_report(
            b"fixture",
            &vector,
            Phase::BoundedAssert,
            "NEVER_EXPORT_PRIVATE_RESPONSE",
        )
        .unwrap();
        assert_eq!(value["status"], "failed");
        assert_eq!(value["language"], "rust");
        assert_eq!(value["capability"], CAPABILITY);
        assert_eq!(
            value["results"],
            json!([{"id":"default-30-from-65","status":"failed"}])
        );
        assert_eq!(
            value["diagnostic"],
            json!({"vectorId":"default-30-from-65","phase":"bounded_assert","errorCode":"unclassified"})
        );
        assert!(!value.to_string().contains("NEVER_EXPORT"));
        assert!(value["diagnostic"].to_string().len() <= 512);
    }
    #[test]
    fn binding_codes_are_normalized_without_messages_and_noncanonical_identifiers_refuse() {
        for (input, expected) in [
            ("invalid_argument", "invalid"),
            ("authentication", "authentication"),
            ("cancelled", "cancelled"),
            ("protocol", "protocol"),
            ("io", "storage_io"),
            ("vector timeout", "timeout"),
            ("peer readiness", "peer_protocol"),
            ("untrusted private text", "unclassified"),
        ] {
            assert_eq!(closed_code(input), expected);
        }
        for id in ["", "../private", "ID", "line\nsecret"] {
            assert!(
                failure_report(b"fixture", &json!({"id":id}), Phase::PeerStart, "offline").is_err()
            );
        }
        assert!(
            failure_report(
                b"fixture",
                &json!({"id":"x".repeat(97)}),
                Phase::PeerStart,
                "offline"
            )
            .is_err()
        );
        assert!(
            failure_report(b"fixture", &json!({"id":null}), Phase::PeerStart, "offline").is_err()
        );
    }
}
