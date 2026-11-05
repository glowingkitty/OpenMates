// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust
use super::downloads::{content_disposition_filename, document_path, join};
use super::stream::{Notification, decode, render};
use super::uploads::{detect_ai, detection_summary, detection_text};
use super::*;
use crate::client::SseMessage;
use openmates_sdk::Session;
use serde_json::json;
use std::collections::BTreeMap;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn invocation(args: &[&str]) -> Invocation {
    let mut full = vec!["openmates"];
    full.extend_from_slice(args);
    super::super::super::parse_from(full)
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .unwrap()
}
fn message(text: &CliError) -> String {
    match text {
        CliError::Contract { message, .. } | CliError::Invalid(message) => message.clone(),
        _ => panic!("expected a message error"),
    }
}

#[test]
fn every_transfer_command_routes_here() {
    for (args, path) in [
        (
            &["teams", "profile-image", "get", "t1"][..],
            "teams profile-image get",
        ),
        (
            &["teams", "profile-image", "upload", "t1"],
            "teams profile-image upload",
        ),
        (
            &["account", "profile-picture", "set", "a.png"],
            "account profile-picture set",
        ),
        (
            &["settings", "account", "profile-picture", "set", "a.png"],
            "settings account profile-picture set",
        ),
        (
            &["settings", "billing", "invoices", "download", "i1"],
            "settings billing invoices download",
        ),
        (
            &["settings", "billing", "invoices", "credit-note", "i1"],
            "settings billing invoices credit-note",
        ),
        (
            &["settings", "notifications", "stream"],
            "settings notifications stream",
        ),
        (
            &["apps", "images", "detect-ai", "a.png"],
            "apps images detect-ai",
        ),
        (
            &["apps", "images", "detect_ai", "a.png"],
            "apps images detect_ai",
        ),
    ] {
        let i = invocation(args);
        assert_eq!(i.command_path(), path);
        assert!(supported(&i), "{path}");
        assert!(super::super::supported(&i), "{path}");
    }
    assert!(!supported(&invocation(&[
        "teams",
        "profile-image",
        "generated",
        "t1"
    ])));
}

#[test]
fn npm_uri_and_content_disposition_rules() {
    assert_eq!(encode_uri_component("a b/ü!~*'()"), "a%20b%2F%C3%BC!~*'()");
    assert!(path_segment("..", "invoice ID").is_err());
    assert_eq!(
        path_segment("in/1", "invoice ID").ok().as_deref(),
        Some("in%2F1")
    );
    let parse = |h: &str| content_disposition_filename(Some(h)).ok().flatten();
    assert_eq!(
        parse("attachment; filename*=UTF-8''Rechnung%20%C3%A4.pdf; x=y").as_deref(),
        Some("Rechnung ä.pdf")
    );
    assert_eq!(
        parse("attachment; FILENAME=\"Invoice_1.pdf\"").as_deref(),
        Some("Invoice_1.pdf")
    );
    assert_eq!(
        parse("attachment; filename= plain.pdf ; x").as_deref(),
        Some("plain.pdf")
    );
    assert!(content_disposition_filename(Some("filename*=UTF-8''%E0%A4")).is_err());
    assert!(content_disposition_filename(None).ok().unwrap().is_none());
    assert!(
        content_disposition_filename(Some("inline"))
            .ok()
            .unwrap()
            .is_none()
    );
}

#[test]
fn npm_document_path_keeps_server_names_inside_the_target() {
    assert_eq!(document_path(None, "Invoice_1.pdf"), "Invoice_1.pdf");
    assert_eq!(document_path(Some("out/"), "../../etc/x.pdf"), "out/x.pdf");
    assert_eq!(document_path(Some("named.pdf"), "x.pdf"), "named.pdf");
    assert_eq!(document_path(Some("/tmp/./d"), ""), "/tmp/d/document.pdf");
    assert_eq!(join("..", "x"), "../x");
    assert_eq!(join("a/b/../..", "x"), "x");
    assert_eq!(basename("dir/a.png"), "a.png");
    assert_eq!(basename("dir/"), "dir");
}

#[test]
fn javascript_number_and_fixed_point_rules() {
    assert_eq!(to_fixed_1(12.25), "12.3");
    assert_eq!(to_fixed_1(12.75), "12.8");
    assert_eq!(to_fixed_1(0.15 * 100.0), "15.0");
    assert_eq!(to_fixed_1(93.456), "93.5");
    assert_eq!(to_fixed_1(0.0), "0.0");
    let count = invocation(&["settings", "notifications", "stream", "--count", " 2 "]);
    assert_eq!(required_number(&count, "count").ok(), Some(2.0));
    let invalid = invocation(&["settings", "notifications", "stream", "--count", "abc"]);
    assert_eq!(
        message(&required_number(&invalid, "count").unwrap_err()),
        "Invalid --count: abc"
    );
}

#[test]
fn detection_summary_matches_npm_order_and_text() {
    let detection = json!({"status": "success", "ai_generated": 0.93, "provider": "sightengine"});
    let mut entries = detection_summary(
        "/tmp/a.png",
        "a.png",
        "image/png",
        "e1",
        &json!(false),
        &detection,
    );
    entries.push(("ai_detection", detection.clone()));
    assert_eq!(
        ordered_json(&entries).ok().unwrap(),
        "{\n  \"success\": true,\n  \"file\": \"/tmp/a.png\",\n  \"filename\": \"a.png\",\n  \"content_type\": \"image/png\",\n  \"embed_id\": \"e1\",\n  \"deduplicated\": false,\n  \"stored\": true,\n  \"status\": \"success\",\n  \"provider\": \"sightengine\",\n  \"ai_generated\": 0.93,\n  \"classification\": \"likely_ai_generated\",\n  \"label\": \"Likely AI-generated\",\n  \"error\": null,\n  \"ai_detection\": {\n    \"ai_generated\": 0.93,\n    \"provider\": \"sightengine\",\n    \"status\": \"success\"\n  }\n}\n"
    );
    let text = detection_text(&entries);
    assert!(text.starts_with(
        "\x1b[1mImages › Detect AI\x1b[0m\n  \x1b[2mFile            \x1b[0m /tmp/a.png\n"
    ));
    assert!(text.contains("  \x1b[2mAI-generated probability\x1b[0m 93.0%\n"));
    assert!(!text.contains("Detection error"));
    assert!(text.ends_with("returns Sightengine metadata.\x1b[0m\n"));

    let missing = detection_summary("/f", "f", "image/png", "e", &Value::Null, &Value::Null);
    let keys: Vec<_> = missing.iter().map(|(k, _)| *k).collect();
    assert!(!keys.contains(&"deduplicated"));
    let text = detection_text(&missing);
    assert!(text.contains("Provider        \x1b[0m n/a\n"));
    assert!(text.contains("Detection status\x1b[0m unavailable\n"));
    assert!(text.contains("Classification  \x1b[0m Detection unavailable\n"));
    let failed = detection_summary(
        "/f",
        "f",
        "t",
        "e",
        &json!(true),
        &json!({"status": "error", "error": "quota"}),
    );
    assert!(detection_text(&failed).contains("Detection error \x1b[0m quota\n"));
    let possible = detection_summary(
        "/f",
        "f",
        "t",
        "e",
        &json!(true),
        &json!({"ai_generated": 0.5}),
    );
    assert_eq!(
        possible
            .iter()
            .find(|(k, _)| *k == "classification")
            .unwrap()
            .1,
        "possibly_ai_generated"
    );
}

#[test]
fn notification_events_follow_npm_filter_and_fallback() {
    let sse = |event: Option<&str>, data: &str| SseMessage {
        id: None,
        event: event.map(Into::into),
        data: data.into(),
    };
    assert!(decode(sse(Some("ping"), "{}")).is_none());
    assert!(matches!(
        decode(sse(Some(""), "1")),
        Some(Notification::Json(_))
    ));
    assert_eq!(
        render(
            decode(sse(Some("notification"), "{\"b\":1,\"a\":2}")).unwrap(),
            true
        )
        .ok()
        .unwrap(),
        "{\n  \"a\": 2,\n  \"b\": 1\n}\n"
    );
    assert_eq!(
        render(decode(sse(None, "not json")).unwrap(), true)
            .ok()
            .unwrap(),
        "{\n  \"event\": \"message\",\n  \"data\": \"not json\"\n}\n"
    );
    let text = render(decode(sse(None, "not json")).unwrap(), false)
        .ok()
        .unwrap();
    assert!(text.find("event").unwrap() < text.find("data").unwrap());
}

#[tokio::test]
async fn detect_ai_reports_local_refusals_like_npm() {
    let mut client = Client::new("https://api.dev.openmates.org", None).unwrap();
    let out = detect_ai(&invocation(&["apps", "images", "detect-ai"]), &mut client)
        .await
        .ok()
        .unwrap();
    assert_eq!(out.exit_code, 1);
    assert_eq!(
        out.stderr,
        "Missing image file.\n\nUsage:\n  openmates apps images detect-ai --file ./image.png [--json]\n\n"
    );
    let out = detect_ai(
        // The native parser bounds positionals; the handler keeps npm's check.
        &Invocation {
            path: vec!["apps".into(), "images".into(), "detect-ai".into()],
            positionals: vec!["b".into(), "c".into()],
            flags: BTreeMap::from([("file".to_owned(), json!("a.png"))]),
        },
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        out.stderr,
        "Unexpected argument(s): b c\n\nRun: openmates apps images detect-ai --help\n"
    );
    let out = detect_ai(
        &invocation(&[
            "apps",
            "images",
            "detect_ai",
            "/nonexistent/openmates/x.png",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        out.stderr,
        "\x1b[31m✗ Image file not found:\x1b[0m /nonexistent/openmates/x.png\n"
    );
    assert_eq!(out.exit_code, 1);
}

/// One-connection loopback server answering a raw HTTP response.
async fn serve(response: Vec<u8>) -> (Client, tokio::task::JoinHandle<String>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut head = Vec::new();
        let mut byte = [0u8; 1];
        while !head.ends_with(b"\r\n\r\n") {
            socket.read_exact(&mut byte).await.unwrap();
            head.push(byte[0]);
        }
        socket.write_all(&response).await.unwrap();
        String::from_utf8_lossy(&head).to_ascii_lowercase()
    });
    let session = Session {
        api_url: api.clone(),
        session_id: "synthetic-transfers".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture".into())]),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: "c2FsdA==".into(),
        email_encryption_key: None,
        created_at: 0,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    (Client::new(&api, Some(session)).unwrap(), handle)
}
fn binary_response(status: &str, headers: &str, body: &[u8]) -> Vec<u8> {
    let mut response = format!(
        "HTTP/1.1 {status}\r\n{headers}Content-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )
    .into_bytes();
    response.extend_from_slice(body);
    response
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn invoice_download_saves_the_server_named_pdf_inside_output() {
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("docs").to_string_lossy().into_owned();
    let (mut client, server) = serve(binary_response(
        "200 OK",
        "Content-Type: application/pdf\r\nContent-Disposition: attachment; filename=\"../Invoice_9.pdf\"\r\n",
        b"%PDF-1.7\x00\xff",
    ))
    .await;
    let i = invocation(&[
        "settings", "billing", "invoices", "download", "inv 9", "--output", &target, "--json",
    ]);
    let out = execute(&i, &mut client).await.ok().unwrap();
    let saved = format!("{target}/Invoice_9.pdf");
    assert_eq!(
        out.stdout,
        format!("{{\n  \"path\": \"{saved}\",\n  \"filename\": \"../Invoice_9.pdf\"\n}}\n")
    );
    assert_eq!(std::fs::read(&saved).unwrap(), b"%PDF-1.7\x00\xff");
    let head = server.await.unwrap();
    assert!(head.starts_with("get /v1/payments/invoices/inv%209/download "));
    assert!(head.contains("\r\naccept: application/pdf,application/octet-stream\r\n"));
    assert!(head.contains("cookie: auth_refresh_token=fixture"));
}

#[tokio::test]
async fn credit_note_failure_and_missing_id_use_npm_messages() {
    let (mut client, server) = serve(binary_response("404 Not Found", "", b"missing")).await;
    let i = invocation(&["settings", "billing", "invoices", "credit-note", "i1"]);
    assert_eq!(
        message(&execute(&i, &mut client).await.err().unwrap()),
        "Download failed (HTTP 404)"
    );
    assert!(
        server
            .await
            .unwrap()
            .starts_with("get /v1/payments/invoices/i1/credit-note/download ")
    );
    let i = invocation(&["settings", "billing", "invoices", "credit-note"]);
    assert_eq!(
        message(&execute(&i, &mut client).await.err().unwrap()),
        "Missing invoice ID."
    );
}

#[cfg(unix)]
#[tokio::test]
async fn team_profile_image_get_writes_an_owner_only_file() {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().unwrap();
    let output = dir.path().join("team.png").to_string_lossy().into_owned();
    let (mut client, server) = serve(binary_response(
        "200 OK",
        "Content-Type: image/png\r\n",
        b"\x89PNG",
    ))
    .await;
    let i = invocation(&[
        "teams",
        "profile-image",
        "get",
        "team-1",
        "--output",
        &output,
        "--json",
    ]);
    let out = execute(&i, &mut client).await.ok().unwrap();
    assert_eq!(
        out.stdout,
        format!(
            "{{\n  \"output\": \"{output}\",\n  \"content_type\": \"image/png\",\n  \"size_bytes\": 4\n}}\n"
        )
    );
    let metadata = std::fs::metadata(&output).unwrap();
    assert_eq!(metadata.permissions().mode() & 0o777, 0o600);
    let head = server.await.unwrap();
    assert!(head.starts_with("get /v1/teams/team-1/profile-image "));
    assert!(head.contains("\r\naccept: image/jpeg,image/png,application/octet-stream\r\n"));
}

#[tokio::test]
async fn team_profile_image_requires_team_and_output() {
    let mut client = Client::new("https://api.dev.openmates.org", None).unwrap();
    let i = invocation(&["teams", "profile-image", "get"]);
    assert_eq!(
        message(&execute(&i, &mut client).await.err().unwrap()),
        "Missing --team <team-id>."
    );
    let i = invocation(&["teams", "profile-image", "get", "t1"]);
    assert_eq!(
        message(&execute(&i, &mut client).await.err().unwrap()),
        "Missing --output <path>."
    );
    let i = invocation(&["teams", "profile-image", "upload", "t1"]);
    assert_eq!(
        message(&execute(&i, &mut client).await.err().unwrap()),
        "Missing --file <path>."
    );
    let i = invocation(&["account", "profile-picture", "set"]);
    assert_eq!(
        message(&execute(&i, &mut client).await.err().unwrap()),
        "Missing image file. Example: openmates settings account profile-picture set ./avatar.jpg"
    );
}

#[tokio::test]
async fn profile_picture_rejects_non_jpeg_png_before_upload() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("a.gif");
    std::fs::write(&file, b"GIF89a").unwrap();
    let (mut client, server) = serve(Vec::new()).await;
    let i = invocation(&[
        "settings",
        "account",
        "profile-picture",
        "set",
        &file.to_string_lossy(),
    ]);
    assert_eq!(
        message(&execute(&i, &mut client).await.err().unwrap()),
        "Profile images must be JPEG or PNG files."
    );
    server.abort();
}

#[tokio::test]
async fn notification_stream_stops_after_count_and_reports_http_failure() {
    let body = b"event: ping\ndata: {}\n\nevent: notification\ndata: {\"id\":1}\n\nevent: notification\ndata: {\"id\":2}\n\n";
    let (mut client, server) = serve(binary_response(
        "200 OK",
        "Content-Type: text/event-stream\r\n",
        body,
    ))
    .await;
    let i = invocation(&[
        "settings",
        "notifications",
        "stream",
        "--count",
        "1",
        "--json",
    ]);
    let out = execute(&i, &mut client).await.ok().unwrap();
    assert!(out.stdout.is_empty() && out.exit_code == 0);
    assert!(
        server
            .await
            .unwrap()
            .contains("\r\naccept: text/event-stream\r\n")
    );

    let (mut client, server) = serve(binary_response("503 Service Unavailable", "", b"")).await;
    let i = invocation(&["settings", "notifications", "stream"]);
    assert_eq!(
        message(&execute(&i, &mut client).await.err().unwrap()),
        "SSE request failed with HTTP 503"
    );
    server.await.unwrap();
}
