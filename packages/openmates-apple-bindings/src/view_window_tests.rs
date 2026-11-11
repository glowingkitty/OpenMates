//! ViewModelCore chat window and fresh session over a temp cache directory and a loopback server that only answers session validation: cached window before any chat request, load older on a complete window, close, and logout followed by begin-session and start.
use crate::view_core_tests::{Events, Keychain, NAME, SIGNED_OUT, cache_files, private_dir};
use crate::*;
use futures_util::future::BoxFuture;
use openmates_sdk::{
    Client,
    client::CredentialSnapshot,
    error::Result,
    local_cache::{
        CacheEngine, CacheStore, FileByteStore, FixedContext, NoScope, OrderedBlocking,
        RevocationFence,
    },
    session::Session,
    shell_session::{CredentialPersistence, CredentialSave, ShellSession, session_cache_context},
};
use serde_json::json;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use zeroize::Zeroizing;

const CHAT: &str = "11111111-1111-4111-8111-111111111111";
const BODY: &str = "Synthetic cached body";

/// Loopback API: `POST /v1/auth/session` succeeds. Every other request is
/// counted; with `serve_chat` the chat metadata and its one-page complete
/// history are served, otherwise the connection closes unanswered (the
/// server is "offline" for chat data).
struct Api {
    url: String,
    chat_requests: Arc<AtomicUsize>,
}

async fn read_request(stream: &mut tokio::net::TcpStream) -> String {
    let mut data = Vec::new();
    let mut part = [0; 4096];
    loop {
        let n = stream.read(&mut part).await.unwrap_or(0);
        if n == 0 {
            return String::from_utf8_lossy(&data).into_owned();
        }
        data.extend_from_slice(&part[..n]);
        let Some(end) = data.windows(4).position(|w| w == b"\r\n\r\n") else {
            continue;
        };
        let headers = String::from_utf8_lossy(&data[..end]).to_ascii_lowercase();
        let length = headers
            .lines()
            .find_map(|line| line.strip_prefix("content-length:"))
            .map_or(0, |n| n.trim().parse::<usize>().unwrap());
        if data.len() >= end + 4 + length {
            return String::from_utf8_lossy(&data).into_owned();
        }
    }
}

fn respond(body: &serde_json::Value) -> String {
    let body = body.to_string();
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
}

async fn api(serve_chat: bool) -> Api {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let chat_requests = Arc::new(AtomicUsize::new(0));
    let counter = chat_requests.clone();
    tokio::spawn(async move {
        while let Ok((mut stream, _)) = listener.accept().await {
            let counter = counter.clone();
            tokio::spawn(async move {
                let request = read_request(&mut stream).await;
                let body = if request.starts_with("POST /v1/auth/session ") {
                    json!({"success": true, "ws_token": "synthetic",
                        "user": {"id": "synthetic-user"}})
                } else {
                    counter.fetch_add(1, Ordering::SeqCst);
                    if !serve_chat {
                        return;
                    }
                    if request.starts_with("POST /v1/chats/metadata/batch ") {
                        // A changed visibility makes the cache-preferred read
                        // fall through to the canonical history read.
                        let mut row = chat_row();
                        row["chat_visibility"] = json!("private");
                        json!({"chats": [row]})
                    } else if request.starts_with(&format!("GET /v1/chats/{CHAT}/messages/window?"))
                    {
                        json!({"messages": [chat_message()], "has_more_before": false})
                    } else {
                        return;
                    }
                };
                let _ = stream.write_all(respond(&body).as_bytes()).await;
            });
        }
    });
    Api { url, chat_requests }
}

fn session(api: &str, id: &str) -> Session {
    Session {
        api_url: api.into(),
        session_id: id.into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: Zeroizing::new([7; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}

/// The chat row, its key wrapped with the master key.
fn chat_row() -> serde_json::Value {
    use openmates_sdk::crypto::{encrypt_bytes, encrypt_combined};
    json!({"id": CHAT, "messages_v": 1, "last_edited_overall_timestamp": 1,
        "encrypted_chat_key": encrypt_bytes(&[9; 32], &[7; 32]).unwrap(),
        "encrypted_title": encrypt_combined("Synthetic cached title", &[9; 32]).unwrap()})
}

/// The chat's one message.
fn chat_message() -> serde_json::Value {
    json!({"id": "22222222-2222-4222-8222-222222222222", "chat_id": CHAT,
        "role": "user", "created_at": 1,
        "encrypted_content": openmates_sdk::crypto::encrypt_combined(BODY, &[9; 32]).unwrap()})
}

/// One cached chat with one message.
fn snapshot() -> serde_json::Value {
    json!({"chats": {CHAT: chat_row()}, "wrappers": [], "history": {CHAT: [chat_message()]},
        "embeds": {}, "embed_keys": [], "team_wrapped_key": null})
}

/// Credentials already durable elsewhere (seeding only).
struct Durable(Session);
impl CredentialPersistence for Durable {
    fn load(&self, _generation: u64) -> BoxFuture<'_, Result<Option<Session>>> {
        Box::pin(async { Ok(Some(self.0.clone())) })
    }
    fn store(&self, _: CredentialSnapshot, _: u64) -> BoxFuture<'_, Result<CredentialSave>> {
        Box::pin(async { Ok(CredentialSave::Saved) })
    }
    fn revoke(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async { Ok(()) })
    }
    fn clear(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async { Ok(()) })
    }
}

/// Write the encrypted cache an earlier app run of `session` left.
async fn seed_cache(dir: &Path, session: &Session) {
    let engine = Arc::new(CacheEngine::new(FileByteStore::open_in(dir, NAME).unwrap()));
    let cache = CacheStore::new(
        engine,
        Arc::new(FixedContext(session_cache_context(session).unwrap())),
        Arc::new(NoScope),
        OrderedBlocking::new(),
    );
    let mut client = Client::new(&session.api_url, Some(session.clone())).unwrap();
    client.restore_ciphertext_snapshot(&snapshot()).unwrap();
    ShellSession::new(cache)
        .persist(&mut client, &Durable(session.clone()))
        .await
        .unwrap();
}

fn core(
    dir: &Path,
    api: &str,
    keychain: &Arc<Keychain>,
    events: &Arc<Events>,
) -> Arc<ViewModelCore> {
    let config = CoreConfig {
        api_url: api.into(),
        app_url: None,
        cache_container: Some(dir.to_str().unwrap().to_owned()),
        cache_directory_name: Some(NAME.into()),
    };
    let core = ViewModelCore::build(
        config,
        keychain.clone(),
        events.clone(),
        Duration::from_secs(5),
    )
    .unwrap();
    keychain.core.set(Arc::downgrade(&core)).unwrap();
    core
}

fn windows(events: &[ViewEventRecord]) -> Vec<(u64, ChatWindowViewRecord)> {
    events
        .iter()
        .filter_map(|event| match event {
            ViewEventRecord::ChatWindow { request, window } => Some((*request, window.clone())),
            _ => None,
        })
        .collect()
}

/// Started over a seeded cache and admitted by the loopback server.
async fn admitted(dir: &Path, api: &Api) -> (Arc<ViewModelCore>, Arc<Events>) {
    let stored = session(&api.url, "synthetic-session");
    seed_cache(dir, &stored).await;
    let keychain = Keychain::holding(&stored, true);
    let events = Arc::new(Events::default());
    let core = core(dir, &api.url, &keychain, &events);
    core.start(None).await.unwrap();
    assert!(events.all().iter().any(|event| matches!(
        event,
        ViewEventRecord::Session {
            event: SessionEventRecord::Admitted { .. }
        }
    )));
    (core, events)
}

#[tokio::test(flavor = "multi_thread")]
async fn open_chat_emits_the_cached_window_before_any_chat_request() {
    let dir = private_dir();
    let api = api(false).await;
    let (core, events) = admitted(dir.path(), &api).await;
    let before = events.all().len();
    let requests = api.chat_requests.load(Ordering::SeqCst);
    // The strict read finds the server offline for chat data; its outcome
    // is not the subject, only what precedes it.
    core.open_chat(7, CHAT.into(), None).await.unwrap();
    let all = events.all();
    let ViewEventRecord::ChatWindow { request, window } = &all[before] else {
        panic!("cached window expected first: {:?}", &all[before..]);
    };
    assert_eq!(*request, 7);
    assert_eq!(window.source, ChatWindowSourceRecord::Cached);
    assert_eq!(window.chat_id, CHAT);
    assert_eq!(window.messages.len(), 1);
    assert_eq!(window.messages[0].content, BODY);
    assert_eq!(window.messages[0].role, MessageRoleRecord::User);
    // Only the strict read after the cached window asked for chat data;
    // offline, it settles on the read-only cached window.
    assert!(api.chat_requests.load(Ordering::SeqCst) > requests);
    let sources: Vec<_> = windows(&all[before..])
        .into_iter()
        .map(|(request, window)| (request, window.source))
        .collect();
    assert_eq!(
        sources,
        [
            (7, ChatWindowSourceRecord::Cached),
            (7, ChatWindowSourceRecord::CachedOffline)
        ]
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn load_older_on_a_complete_window_is_emitted_unchanged_without_a_request() {
    let dir = private_dir();
    let api = api(true).await;
    let (core, events) = admitted(dir.path(), &api).await;
    core.open_chat(1, CHAT.into(), None).await.unwrap();
    let (_, canonical) = windows(&events.all()).pop().expect("a window was shown");
    assert_eq!(canonical.source, ChatWindowSourceRecord::Canonical);
    assert!(canonical.history_complete);
    assert_eq!(canonical.has_more_before, Some(false));
    assert_eq!(canonical.messages[0].content, BODY);
    let requests = api.chat_requests.load(Ordering::SeqCst);
    core.load_older(2, CHAT.into(), None).await.unwrap();
    assert_eq!(windows(&events.all()).pop(), Some((2, canonical)));
    assert_eq!(api.chat_requests.load(Ordering::SeqCst), requests);
}

#[tokio::test(flavor = "multi_thread")]
async fn load_older_and_close_need_the_open_chat() {
    let dir = private_dir();
    let api = api(false).await;
    let (core, events) = admitted(dir.path(), &api).await;
    assert!(matches!(
        core.load_older(1, CHAT.into(), None).await,
        Err(CoreError::Invalid { .. })
    ));
    let _strict = core.open_chat(2, CHAT.into(), None).await;
    core.close_chat(CHAT.into()).await.unwrap();
    // Closed: paging refuses, and closing again does nothing.
    assert!(matches!(
        core.load_older(3, CHAT.into(), None).await,
        Err(CoreError::Invalid { .. })
    ));
    core.close_chat(CHAT.into()).await.unwrap();
    let count = events.all().len();
    assert!(matches!(
        core.open_chat(4, "not-a-chat-id".into(), None).await,
        Err(CoreError::Invalid { .. })
    ));
    assert_eq!(events.all().len(), count);
}

#[tokio::test(flavor = "multi_thread")]
async fn window_commands_while_signed_out_fail_with_authentication() {
    let dir = private_dir();
    let api = api(false).await;
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    core.start(None).await.unwrap();
    assert_eq!(
        core.open_chat(1, CHAT.into(), None).await,
        Err(CoreError::Authentication)
    );
    assert_eq!(
        core.close_chat(CHAT.into()).await,
        Err(CoreError::Authentication)
    );
    assert_eq!(
        core.mark_read(CHAT.into(), None).await,
        Err(CoreError::Authentication)
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn logout_then_begin_session_starts_a_fresh_session() {
    let dir = private_dir();
    let api = api(false).await;
    let (core, events) = admitted(dir.path(), &api).await;
    assert!(cache_files(dir.path()) > 0);
    // Remote logout gets no answer; local sign-out completes regardless.
    let _ = core.logout().await;
    let bytes = FileByteStore::open_in(dir.path(), NAME).unwrap();
    let revoked = RevocationFence::load(&bytes).unwrap();
    assert!(revoked.revoked);
    assert_eq!(events.all().last(), Some(&SIGNED_OUT));

    let fresh = session(&api.url, "fresh-session");
    core.begin_session(fresh, None).await.unwrap();
    let fence = RevocationFence::load(&bytes).unwrap();
    assert!(!fence.revoked);
    assert_ne!(fence.epoch, revoked.epoch);
    // The fresh session started and was admitted; the old cache is gone.
    let after_begin = events.all();
    assert!(matches!(
        after_begin.last(),
        Some(ViewEventRecord::Session {
            event: SessionEventRecord::Admitted { .. }
        })
    ));
    assert!(core.load_older(1, CHAT.into(), None).await.is_err());
    // A second start restores the stored fresh session again.
    core.start(None).await.unwrap();
    assert_ne!(events.all().last(), Some(&SIGNED_OUT));
    // A signed-in profile refuses another begin.
    assert!(matches!(
        core.begin_session(session(&api.url, "third-session"), None)
            .await,
        Err(CoreError::Invalid { .. })
    ));
    // The revoked session never begins again after the next sign-out.
    let _ = core.logout().await;
    assert_eq!(
        core.begin_session(session(&api.url, "fresh-session"), None)
            .await,
        Err(CoreError::Authentication)
    );
}
