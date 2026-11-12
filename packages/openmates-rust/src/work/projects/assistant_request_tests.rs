//! Assistant-requested Project creation: request validation, create + focus,
//! rollback, reload lookup and undo against a stateful in-process REST server.
// contract-test: supporting surface=sdks.rust assertions=projects.creation.assistant-inferred
use super::assistant_request::default_focus;
use super::*;
use crate::work::tasks::tests::client;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub(crate) const CHAT: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";
pub(crate) const REQUEST: &str = "project-create-request-bbbbbbbb-1111-4111-8111-aabbccddeeff";

pub(crate) fn request_event(now: u64) -> Value {
    json!({"chat_id":CHAT,"request_id":REQUEST,"pending_client_action":{
        "contract":PROJECT_CREATE_CONTRACT,"version":1,"request_id":REQUEST,"action":"create",
        "origin":"preprocessor","chat_id":CHAT,"message_id":"m","team_id":null,
        "name":"Recipe Manager","description":"","kind":"web_app","subfolder":"web-app",
        "write_mode":"apply_and_show","focus":{"activate":"immediate","countdown_seconds":0},
        "undo":{"available":true},"created_at":now,"expires_at":now+600,"notification_queued":false}})
}

#[test]
fn parse_accepts_the_contract_request_and_refuses_everything_else() {
    let request = ProjectCreateRequest::parse(&request_event(1_000), CHAT, 1_000).unwrap();
    assert_eq!(request.subfolder, "web-app");
    assert_eq!(request.team_id, None);
    let refused = |mutate: &dyn Fn(&mut Value)| {
        let mut value = request_event(1_000);
        mutate(&mut value);
        ProjectCreateRequest::parse(&value, CHAT, 1_000)
            .unwrap_err()
            .1
    };
    let action = "pending_client_action";
    assert_eq!(
        refused(&|v| v[action]["version"] = json!(2)),
        ProjectCreateRefusal::Invalid
    );
    assert_eq!(
        refused(&|v| v[action]["contract"] = json!("x")),
        ProjectCreateRefusal::Invalid
    );
    assert_eq!(
        refused(&|v| v[action]["subfolder"] = json!("native-app")),
        ProjectCreateRefusal::Invalid
    );
    assert_eq!(
        refused(&|v| v[action]["write_mode"] = json!("always_ask")),
        ProjectCreateRefusal::Invalid
    );
    assert_eq!(
        refused(&|v| v[action]["focus"]["activate"] = json!("none")),
        ProjectCreateRefusal::Invalid
    );
    assert_eq!(
        refused(&|v| v[action]["name"] = json!("x".repeat(121))),
        ProjectCreateRefusal::Invalid
    );
    assert_eq!(
        refused(&|v| v["request_id"] = json!("other")),
        ProjectCreateRefusal::Invalid
    );
    assert_eq!(
        ProjectCreateRequest::parse(&request_event(1_000), CHAT, 1_600)
            .unwrap_err()
            .1,
        ProjectCreateRefusal::Expired
    );
    let (id, _) =
        ProjectCreateRequest::parse(&request_event(1_000), "other-chat", 1_000).unwrap_err();
    assert_eq!(
        id.as_deref(),
        Some(REQUEST),
        "a refused request is still reportable"
    );
}

#[test]
fn default_focus_matches_the_rule_core_creation_applies() {
    let focus = default_focus("Recipe Manager");
    let raw = encode_create(
        &ProjectCreate {
            name: "Recipe Manager".into(),
            write_mode: Some(ProjectWriteMode::ApplyAndShow),
            ..Default::default()
        },
        &[8; 32],
        &[7; 32],
        None,
    )
    .unwrap();
    let settings = crypto::server_fields::decrypt_text(
        raw["encrypted_settings"].as_str().unwrap(),
        &[8; 32],
        &[],
    )
    .unwrap();
    let generated: Value = serde_json::from_str(&settings).unwrap();
    assert_eq!(generated["default_focus"]["name"], focus.name);
    assert_eq!(
        generated["default_focus"]["instructions"],
        focus.instructions
    );
}

pub(crate) type Handler = Box<dyn Fn(&str, &Value, &Mutex<Option<Value>>) -> Value + Send>;

/// Serve one HTTP exchange per connection through `handler`, remembering the
/// created Project row so later reads return it like the real API would.
pub(crate) async fn rest_fixture(
    handler: Handler,
) -> (
    String,
    Arc<Mutex<Vec<(String, Value)>>>,
    Arc<Mutex<Option<Value>>>,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let log = Arc::new(Mutex::new(vec![]));
    let stored = Arc::new(Mutex::new(None));
    let (seen, state) = (log.clone(), stored.clone());
    tokio::spawn(async move {
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = Vec::new();
            let (head_end, size) = loop {
                let mut bytes = [0; 8192];
                let n = socket.read(&mut bytes).await.unwrap();
                assert!(n > 0);
                buf.extend_from_slice(&bytes[..n]);
                if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                    let size = head
                        .lines()
                        .find_map(|l| {
                            l.strip_prefix("content-length:")?
                                .trim()
                                .parse::<usize>()
                                .ok()
                        })
                        .unwrap_or(0);
                    if buf.len() >= end + 4 + size {
                        break (end, size);
                    }
                }
            };
            let text = String::from_utf8_lossy(&buf[..head_end]).into_owned();
            let line = text
                .lines()
                .next()
                .unwrap()
                .rsplit_once(' ')
                .unwrap()
                .0
                .to_owned();
            let body: Value = serde_json::from_slice(&buf[head_end + 4..head_end + 4 + size])
                .unwrap_or(Value::Null);
            let reply = handler(&line, &body, &state);
            seen.lock().unwrap().push((line, body));
            // A handler can answer an error status through `__status`.
            let status = reply["__status"].as_u64().unwrap_or(200);
            let reply = reply.to_string();
            socket
                .write_all(format!("HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{reply}", reply.len()).as_bytes())
                .await
                .unwrap();
        }
    });
    (api, log, stored)
}

pub(crate) fn rest_handler(activate_ok: bool) -> Handler {
    Box::new(move |line, body, stored| {
        let row = stored.lock().unwrap().clone();
        if line == "POST /v1/projects" {
            *stored.lock().unwrap() = Some(body.clone());
            json!({"project": {"project_id": body["project_id"]}})
        } else if line.ends_with("/focus/activate") {
            if activate_ok {
                json!({"focus": {"project_id": "p", "chat_id": CHAT}})
            } else {
                json!({})
            }
        } else if line.starts_with("GET /v1/projects/focus/current") {
            match row {
                Some(row) => json!({"focus":{"project_id":row["project_id"],"chat_id":CHAT}}),
                None => json!({"focus":null}),
            }
        } else if line.ends_with("/settings") {
            let row = row.unwrap();
            json!({"settings":{"encrypted_settings":row["encrypted_settings"],
                "default_focus_id_hash":hash(row["default_focus_id"].as_str().unwrap())}})
        } else if line.starts_with("GET /v1/projects/") {
            json!({"project": row.unwrap()})
        } else if line.starts_with("POST /v1/projects/focus/deactivate") {
            json!({"success": true})
        } else if line.starts_with("DELETE /v1/projects/") {
            *stored.lock().unwrap() = None;
            json!({"deleted": true})
        } else {
            panic!("unexpected request {line}")
        }
    })
}

fn request() -> ProjectCreateRequest {
    ProjectCreateRequest::parse(&request_event(now()), CHAT, now()).unwrap()
}

#[tokio::test]
async fn creates_an_apply_and_show_project_and_activates_its_default_focus() {
    let (api, log, _) = rest_fixture(rest_handler(true)).await;
    let mut c = client(&api);
    let record = c.projects().create_for_request(&request()).await.unwrap();
    let log = log.lock().unwrap();
    assert_eq!(log.len(), 2);
    let (create, body) = &log[0];
    assert_eq!(create, "POST /v1/projects");
    assert_eq!(body["write_mode"], "apply_and_show");
    assert_eq!(body["default_focus_id"], record.focus_id);
    assert!(
        !body.to_string().contains("Recipe Manager"),
        "name stays encrypted"
    );
    let (activate, focus) = &log[1];
    assert!(activate.ends_with(&format!("{}/focus/activate", record.project_id)));
    assert_eq!(focus["focus_id"], record.focus_id);
    assert_eq!(focus["chat_id"], CHAT);
    assert!(focus.get("activation_request_id").is_none(), "no countdown");
    assert_eq!(
        (record.subfolder.as_str(), record.undo_available),
        ("web-app", true)
    );
}

#[tokio::test]
async fn taken_slug_retries_with_a_numbered_slug_and_keeps_the_name() {
    let inner = rest_handler(true);
    let posts = Arc::new(Mutex::new(0));
    let count = posts.clone();
    let handler: Handler = Box::new(move |line, body, stored| {
        if line == "POST /v1/projects" {
            let mut n = count.lock().unwrap();
            *n += 1;
            if *n == 1 {
                return json!({"__status": 409, "detail": "PROJECT_SLUG_CONFLICT"});
            }
        }
        inner(line, body, stored)
    });
    let (api, log, _) = rest_fixture(handler).await;
    let mut c = client(&api);
    let record = c.projects().create_for_request(&request()).await.unwrap();
    let log = log.lock().unwrap();
    let creates: Vec<&Value> = log
        .iter()
        .filter(|(line, _)| line == "POST /v1/projects")
        .map(|(_, body)| body)
        .collect();
    assert_eq!(creates.len(), 2, "one retry after the conflict");
    assert_ne!(
        creates[0]["slug_lookup_hash"], creates[1]["slug_lookup_hash"],
        "the retry asks for a different slug"
    );
    assert_eq!(creates[1]["project_id"], record.project_id);
    assert_eq!(
        record.name, "Recipe Manager",
        "the shown name stays as asked"
    );
}

#[tokio::test]
async fn failed_focus_activation_deletes_the_new_project_and_reports_the_error() {
    let (api, log, stored) = rest_fixture(rest_handler(false)).await;
    let mut c = client(&api);
    assert!(c.projects().create_for_request(&request()).await.is_err());
    assert!(
        stored.lock().unwrap().is_none(),
        "no half-created Project remains"
    );
    assert!(log
        .lock()
        .unwrap()
        .iter()
        .any(|(line, _)| line.starts_with("DELETE /v1/projects/")));
}

#[tokio::test]
async fn created_project_is_found_again_after_reload_and_undo_removes_it() {
    let (api, log, stored) = rest_fixture(rest_handler(true)).await;
    let mut c = client(&api);
    let created = c.projects().create_for_request(&request()).await.unwrap();
    // A fresh client stands in for a chat reload: only server state remains.
    let mut reloaded = client(&api);
    let found = reloaded
        .projects()
        .created_for_chat(CHAT)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(found.project_id, created.project_id);
    assert_eq!(found.name, "Recipe Manager");
    assert_eq!(
        (found.kind.as_str(), found.subfolder.as_str()),
        ("web_app", "web-app")
    );
    reloaded.projects().undo_created(CHAT).await.unwrap();
    assert!(stored.lock().unwrap().is_none());
    let lines: Vec<String> = log.lock().unwrap().iter().map(|(l, _)| l.clone()).collect();
    let deactivate = lines
        .iter()
        .position(|l| l.starts_with("POST /v1/projects/focus/deactivate"))
        .unwrap();
    let delete = lines
        .iter()
        .position(|l| l.starts_with("DELETE /v1/projects/"))
        .unwrap();
    assert!(
        deactivate < delete,
        "focus is deactivated before the Project is deleted"
    );
    assert!(reloaded
        .projects()
        .created_for_chat(CHAT)
        .await
        .unwrap()
        .is_none());
}

#[tokio::test]
async fn undo_refuses_a_project_the_assistant_did_not_create_for_the_chat() {
    let (api, log, _) = rest_fixture(rest_handler(true)).await;
    let mut c = client(&api);
    assert_eq!(
        c.projects().undo_created(CHAT).await.unwrap_err(),
        Error::Forbidden
    );
    assert!(log
        .lock()
        .unwrap()
        .iter()
        .all(|(l, _)| !l.starts_with("DELETE")));
}
