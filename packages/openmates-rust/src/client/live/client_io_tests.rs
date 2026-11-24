//! A live item opened with a Project id resolves its head, key and content through the
//! Project path, never the chat-only embed key path (`live-collab.core.live-session`).
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
// contract-test: supporting surface=sdk assertions=live-collab.access.roles
use super::client_io::{ClientLiveIo, IoState, LiveSend};
use super::driver::LiveDriver;
use super::session_types::{Event, Status};
use super::stored_form::stored_with_text;
use super::{LiveError, LiveItemKind};
use crate::client::{Client, Session, sha256};
use crate::crypto;
use futures_util::{SinkExt, StreamExt};
use serde_json::{Value, json};
use std::cell::RefCell;
use std::rc::Rc;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const PROJECT: &str = "11111111-1111-4111-8111-111111111111";
const EMBED: &str = "22222222-2222-4222-8222-222222222222";
const TEAM: &str = "55555555-5555-4555-8555-555555555555";
const TEAM_KEY: [u8; 32] = [7; 32];
const CHAT: &str = "33333333-3333-4333-8333-333333333333";
const OWNER: &str = "44444444-4444-4444-8444-444444444444";
const MASTER: [u8; 32] = [1; 32];
const PROJECT_KEY: [u8; 32] = [5; 32];
const EMBED_KEY: [u8; 32] = [9; 32];
const TEXT: &str = "| A |\n| --- |\n| 1 |";

/// Fake server that serves only the Project routes and the embed socket read.
struct Peer {
    api: String,
    requests: Arc<Mutex<Vec<String>>>,
    task: tokio::task::JoinHandle<()>,
}

/// How the fake server refuses reads.
#[derive(Clone, Copy, Default)]
struct Refusals {
    /// `request_embed` is answered with the author-only not-found error frame (the caller
    /// is a Team member who did not create the embed).
    socket_embed: bool,
    /// The Project route answers 403 for the embed head.
    project_head: bool,
}

fn embed_row() -> Value {
    let content = stored_with_text(LiveItemKind::Sheet, &json!({}), TEXT, 3).unwrap();
    json!({"embed_id": EMBED, "already_encrypted": true, "chat_id": CHAT,
        "type": crypto::encrypt_combined("sheet", &EMBED_KEY).unwrap(),
        "content": crypto::encrypt_combined(&content, &EMBED_KEY).unwrap(),
        "status": "finished", "version_number": 3, "updatedAt": 1,
        "embed_keys": [], "parent_embed_id": null})
}

fn project_row() -> Value {
    json!({"project_id": PROJECT, "version": 1,
        "encrypted_project_key": crypto::encrypt_bytes(&PROJECT_KEY, &MASTER).unwrap()})
}

/// The Project row of a Team Project: its key sits under the Team key.
fn team_project_row() -> Value {
    json!({"project_id": PROJECT, "version": 1, "hashed_team_id": sha256(TEAM),
        "key_wrappers": [{"key_type": "team", "hashed_team_id": sha256(TEAM),
            "team_key_epoch": 1,
            "encrypted_project_key": crypto::encrypt_bytes(&PROJECT_KEY, &TEAM_KEY).unwrap()}]})
}

async fn http_request(stream: &mut tokio::net::TcpStream) -> String {
    let mut data = vec![];
    loop {
        let mut part = [0; 4096];
        let n = stream.read(&mut part).await.unwrap();
        assert!(n > 0);
        data.extend_from_slice(&part[..n]);
        if let Some(end) = data.windows(4).position(|v| v == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&data[..end]).to_ascii_lowercase();
            let length = headers
                .lines()
                .find_map(|l| l.strip_prefix("content-length:")?.trim().parse().ok())
                .unwrap_or(0);
            if data.len() >= end + 4 + length {
                return String::from_utf8(data).unwrap();
            }
        }
    }
}

async fn respond(stream: &mut tokio::net::TcpStream, status: u16, body: Value) {
    let body = body.to_string();
    let head = format!(
        "HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(head.as_bytes()).await;
}

impl Peer {
    async fn start() -> Self {
        Self::start_with(Refusals::default()).await
    }

    async fn start_with(refusals: Refusals) -> Self {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let requests = Arc::new(Mutex::new(Vec::new()));
        let log = requests.clone();
        let task = tokio::spawn(async move {
            loop {
                let (mut stream, _) = listener.accept().await.unwrap();
                let log = log.clone();
                tokio::spawn(async move {
                    let mut head = [0; 4096];
                    let n = loop {
                        let n = stream.peek(&mut head).await.unwrap();
                        if head[..n].contains(&b'\n') {
                            break n;
                        }
                        tokio::task::yield_now().await;
                    };
                    if String::from_utf8_lossy(&head[..n]).starts_with("GET /v1/ws?") {
                        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
                        while let Some(Ok(frame)) = ws.next().await {
                            let Ok(text) = frame.to_text() else { break };
                            let frame: Value = serde_json::from_str(text).unwrap();
                            if frame["type"] == "request_embed" {
                                let reply = if refusals.socket_embed {
                                    json!({"type": "error", "payload": {"message": "Embed not found",
                                        "status": 404, "code": "embed_not_found", "embed_id": EMBED}})
                                } else {
                                    json!({"type": "send_embed_data", "payload": embed_row()})
                                };
                                ws.send(reply.to_string().into()).await.unwrap();
                            }
                        }
                        return;
                    }
                    let request = http_request(&mut stream).await;
                    let line = request.lines().next().unwrap().to_owned();
                    log.lock().unwrap().push(line.clone());
                    let path = line.split(' ').nth(1).unwrap_or_default().to_owned();
                    if line.starts_with("POST /v1/auth/session ") {
                        respond(&mut stream, 200, json!({"success": true, "ws_token": "t", "user": {"id": OWNER}, "client_security_capabilities": ["expected-principal-v1", "ws-dual-principal-v1"]})).await;
                    } else if path.starts_with(&format!("/v1/teams/{TEAM}")) {
                        respond(&mut stream, 200, json!({"team": {"team_id": TEAM, "team_key_epoch": 1,
                            "encrypted_team_key": crypto::encrypt_bytes(&TEAM_KEY, &MASTER).unwrap()}})).await;
                    } else if path.starts_with(&format!("/v1/projects/{PROJECT}")) {
                        let row = if path.contains(&format!("team_id={TEAM}")) {
                            team_project_row()
                        } else {
                            project_row()
                        };
                        respond(&mut stream, 200, json!({"project": row})).await;
                    } else if path.starts_with(&format!("/v1/embeds/{EMBED}/encrypted"))
                        && path.contains("project_id=")
                        && refusals.project_head
                    {
                        respond(&mut stream, 403, json!({"detail": "not a member"})).await;
                    } else if path.starts_with(&format!("/v1/embeds/{EMBED}/encrypted"))
                        && path.contains("project_id=")
                    {
                        let wrapper =
                            crypto::server_fields::encrypt_bytes(&EMBED_KEY, &PROJECT_KEY, &[])
                                .unwrap();
                        let row = embed_row();
                        respond(&mut stream, 200, json!({"embed": {"embed_id": EMBED,
                            "encrypted_type": row["type"], "encrypted_content": row["content"],
                            "status": "finished", "version_number": 3, "updated_at": 1},
                            "embed_keys": [{"key_type": "project", "encrypted_embed_key": wrapper}]})).await;
                    } else {
                        respond(&mut stream, 404, json!({"detail": "not served"})).await;
                    }
                });
            }
        });
        Self {
            api,
            requests,
            task,
        }
    }

    fn client(&self) -> Client {
        let session = Session {
            api_url: self.api.clone(),
            session_id: "synthetic".into(),
            cookies: Default::default(),
            ws_token: Some("t".into()),
            master_key: zeroize::Zeroizing::new(MASTER),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        let mut client = Client::new(&self.api, Some(session)).unwrap();
        client.user = json!({"id": OWNER, "username": "synthetic"});
        // Browser raw-master mode: the row read needs no wrapper, as in the web Worker.
        let native = client.session.take().unwrap();
        let credentials =
            crate::client::credentials::BrowserCredentials::from_native_session(native);

        client.browser_credentials = Some(credentials);
        client.browser_authority = Some(crate::client::browser::BrowserAuthority {
            principal: OWNER.into(),
            persistence: crate::client::browser::BrowserPersistence::MemoryOnly,
            owner_guards: true,
        });
        client
    }
}

#[derive(Default)]
struct Frames(RefCell<Vec<(String, Value)>>);

impl LiveSend for Frames {
    fn send(&self, message_type: &str, payload_json: &str) -> Result<(), LiveError> {
        self.0.borrow_mut().push((
            message_type.to_owned(),
            serde_json::from_str(payload_json).unwrap(),
        ));
        Ok(())
    }
}

/// Opens the sheet (with `project`) and returns the events of the open, the state frame
/// and the acknowledgement of its seed update.
async fn open_and_settle(peer: &Peer, project: Option<&str>, team: Option<&str>) -> Vec<Event> {
    let mut client = peer.client();
    // A signed-in shell has validated its session before it opens an item; the first
    // validation of a browser-mode client cancels the reads begun before it.
    client.validate_session().await.unwrap();
    let frames = Rc::new(Frames::default());
    let mut state = IoState::default();
    state.send = Some(frames.clone());
    state.kinds.insert(EMBED.into(), LiveItemKind::Sheet);
    if let Some(project) = project {
        state.projects.insert(EMBED.into(), project.into());
    }
    if let Some(team) = team {
        state.teams.insert(EMBED.into(), team.into());
    }
    let mut driver = LiveDriver::new(ClientLiveIo::new(&mut client, &mut state));
    driver.set_connected(true, 0).await.unwrap();
    let mut events = driver.open(EMBED, LiveItemKind::Sheet, 0).await.unwrap();
    if events.iter().any(|e| {
        matches!(
            e,
            Event::Status {
                status: Status::Offline,
                ..
            }
        )
    }) {
        return events;
    }
    let state_frame = json!({"item_id": EMBED, "role": "edit", "updates": [], "head_seq": 0});
    events.extend(
        driver
            .on_frame("live_item_state", &state_frame, 10)
            .await
            .unwrap()
            .unwrap(),
    );
    let id = frames
        .0
        .borrow()
        .iter()
        .find(|(t, _)| t == "live_item_update")
        .map(|(_, p)| p["client_msg_id"].clone())
        .expect("seed update sent");
    let ack = json!({"item_id": EMBED, "client_msg_id": id, "seq": 1});
    events.extend(
        driver
            .on_frame("live_item_update_ack", &ack, 20)
            .await
            .unwrap()
            .unwrap(),
    );
    events
}

#[tokio::test]
async fn item_opened_in_a_project_resolves_key_and_content_through_the_project_path() {
    let peer = Peer::start().await;
    let events = open_and_settle(&peer, Some(PROJECT), None).await;
    assert!(
        !events.iter().any(|e| matches!(
            e,
            Event::Status {
                status: Status::Offline,
                ..
            }
        )),
        "a Project file opens without a chat wrapper: {events:?} {:?}",
        peer.requests.lock().unwrap()
    );
    assert!(events.iter().any(|e| matches!(
        e,
        Event::Status {
            status: Status::Saved,
            ..
        }
    )));
    let requests = peer.requests.lock().unwrap().clone();
    assert!(
        requests
            .iter()
            .any(|r| r.contains(&format!("/v1/embeds/{EMBED}/encrypted"))
                && r.contains("project_id=")),
        "the key came from the Project wrapper route: {requests:?}"
    );
    assert!(
        requests
            .iter()
            .all(|r| !r.contains(&sha256(CHAT)) && !r.contains("/chats/")),
        "no chat-only route is touched: {requests:?}"
    );
    peer.task.abort();
}

#[tokio::test]
async fn item_opened_without_a_project_on_a_project_only_server_is_offline() {
    let peer = Peer::start().await;
    let events = open_and_settle(&peer, None, None).await;
    assert!(events.iter().any(|e| matches!(
        e,
        Event::Status { item_id, status: Status::Offline } if item_id == EMBED
    )));
    let requests = peer.requests.lock().unwrap().clone();
    assert!(
        !requests.iter().any(|r| r.contains("project_id=")),
        "without a Project id the Project route is never read: {requests:?}"
    );
    peer.task.abort();
}

#[tokio::test]
async fn item_opened_in_a_team_project_reads_the_project_with_its_team_while_no_team_is_active() {
    let peer = Peer::start().await;
    let events = open_and_settle(&peer, Some(PROJECT), Some(TEAM)).await;
    let requests = peer.requests.lock().unwrap().clone();
    assert!(
        events.iter().any(|e| matches!(
            e,
            Event::Status {
                status: Status::Saved,
                ..
            }
        )),
        "a Team Project file reaches Saved: {events:?} {requests:?}"
    );
    assert!(
        requests
            .iter()
            .any(|r| r.contains(&format!("/v1/projects/{PROJECT}"))
                && r.contains(&format!("team_id={TEAM}"))),
        "the Project is requested with its Team: {requests:?}"
    );
    peer.task.abort();
}

#[tokio::test]
async fn team_member_who_did_not_create_the_item_opens_it_through_the_project_route() {
    let peer = Peer::start_with(Refusals {
        socket_embed: true,
        project_head: false,
    })
    .await;
    let events = tokio::time::timeout(
        std::time::Duration::from_secs(10),
        open_and_settle(&peer, Some(PROJECT), Some(TEAM)),
    )
    .await
    .expect("the open does not hang");
    let requests = peer.requests.lock().unwrap().clone();
    assert!(
        events.iter().any(|e| matches!(
            e,
            Event::Status {
                status: Status::Saved,
                ..
            }
        )),
        "a member who is not the author reaches Saved: {events:?} {requests:?}"
    );
    assert!(
        requests
            .iter()
            .any(|r| r.contains(&format!("/v1/embeds/{EMBED}/encrypted"))
                && r.contains(&format!("team_id={TEAM}"))),
        "the head is read through the Project route with the Team: {requests:?}"
    );
    peer.task.abort();
}

#[tokio::test]
async fn refused_head_read_takes_the_item_offline_without_hanging() {
    let peer = Peer::start_with(Refusals {
        socket_embed: true,
        project_head: true,
    })
    .await;
    let events = tokio::time::timeout(
        std::time::Duration::from_secs(10),
        open_and_settle(&peer, Some(PROJECT), Some(TEAM)),
    )
    .await
    .expect("a refused open ends instead of waiting");
    assert!(events.iter().any(|e| matches!(
        e,
        Event::Status { item_id, status: Status::Offline } if item_id == EMBED
    )));
    peer.task.abort();
}
