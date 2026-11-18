//! `embedVersionContent` on `ViewModelCore` against a loopback API: the
//! reconstructed content, cancellation and refusal of a non canonical id.
use crate::view_core_tests::{private_dir, Events, Keychain};
use crate::view_window_tests::{core, read_request, session};
use crate::*;
use serde_json::{json, Value};
use std::sync::Arc;
use std::time::Duration;
use tokio::io::AsyncWriteExt;

const EMBED: &str = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d";
const HANGING_EMBED: &str = "00000000-0000-4000-8000-000000000000";

fn reply(body: &Value) -> String {
    let body = body.to_string();
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
}

async fn api() -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    tokio::spawn(async move {
        while let Ok((mut stream, _)) = listener.accept().await {
            tokio::spawn(async move {
                let raw = read_request(&mut stream).await;
                let line = raw.lines().next().unwrap_or_default().to_owned();
                let body = if line.starts_with("POST /v1/auth/session ") {
                    json!({"success": true, "ws_token": "synthetic-ws",
                        "user": {"id": "synthetic-user", "username": "Synthetic Tester"}})
                } else if line.starts_with(&format!("GET /v1/embeds/{EMBED}/versions/2")) {
                    json!({"embed_id": EMBED, "version_number": 2, "current_version": 3,
                        "content": "title: Draft\nbody: second version"})
                } else if line.contains(HANGING_EMBED) {
                    tokio::time::sleep(Duration::from_secs(30)).await;
                    return;
                } else {
                    return;
                };
                let _ = stream.write_all(reply(&body).as_bytes()).await;
            });
        }
    });
    url
}

async fn signed_in() -> (tempfile::TempDir, Arc<ViewModelCore>) {
    let dir = private_dir();
    let url = api().await;
    let stored = session(&url, "synthetic-session-1");
    let (keychain, events) = (
        Keychain::holding(&stored, true),
        Arc::new(Events::default()),
    );
    let core = core(dir.path(), &url, &keychain, &events);
    core.start(None).await.unwrap();
    (dir, core)
}

#[tokio::test(flavor = "multi_thread")]
async fn version_content_returns_the_reconstructed_plaintext() {
    let (_dir, core) = signed_in().await;
    let record = core
        .embed_version_content(EMBED.into(), None, 2, None)
        .await
        .expect("content");
    assert_eq!(record.version, 2);
    assert_eq!(record.content, "title: Draft\nbody: second version");
}

#[tokio::test(flavor = "multi_thread")]
async fn a_cancelled_version_content_read_settles_as_cancelled() {
    let (_dir, core) = signed_in().await;
    let cancellation = CoreCancellation::new();
    let cancel = cancellation.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(200)).await;
        cancel.cancel();
    });
    let outcome = tokio::time::timeout(
        Duration::from_secs(10),
        core.embed_version_content(HANGING_EMBED.into(), None, 1, Some(cancellation)),
    )
    .await
    .expect("the cancelled read settles");
    assert_eq!(outcome, Err(EmbedEditError::Cancelled));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_non_canonical_embed_id_is_refused_as_validation() {
    let (_dir, core) = signed_in().await;
    assert_eq!(
        core.embed_version_content("not-a-uuid".into(), None, 1, None)
            .await,
        Err(EmbedEditError::Validation {
            code: "invalid_request".into()
        })
    );
}
