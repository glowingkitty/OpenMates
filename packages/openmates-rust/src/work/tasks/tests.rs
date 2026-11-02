use super::*;
use crate::{ClientIdentity, ClientOptions, Session};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const TASK: &str = "aabbccdd-1111-4111-8111-aabbccddeeff";
const THREAD: &str = "bbbbbbbb-1111-4111-8111-aabbccddeeff";
pub(in crate::work) fn client(api: &str) -> Client {
    Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: "fixture".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "fixture-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
fn raw_task() -> Value {
    encrypt_create(
        &TaskCreate {
            title: "Private task".into(),
            description: "Private details".into(),
            task_id: Some(TASK.into()),
            labels: vec![" Secret label ".into()],
            ..Default::default()
        },
        &[7; 32],
        &[7; 32],
        None,
    )
    .unwrap()
}
fn delivery(kind: TaskMutationKind, input: Value) -> TaskDelivery {
    TaskDelivery {
        protocol_version: 1,
        delivery_id: "a".repeat(64),
        task_id: TASK.into(),
        team_id: None,
        scope: String::new(),
        kind,
        input,
        expected_owner_hash: None,
        creator: false,
        actor_assignee: false,
    }
}
pub(in crate::work) async fn mock(
    responses: Vec<Value>,
) -> (String, tokio::task::JoinHandle<Vec<String>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        let mut requests = vec![];
        for response in responses {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = Vec::new();
            loop {
                let mut bytes = [0; 4096];
                let n = socket.read(&mut bytes).await.unwrap();
                assert!(n > 0);
                buf.extend_from_slice(&bytes[..n]);
                if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                    let size = head
                        .lines()
                        .find_map(|line| {
                            line.strip_prefix("content-length:")
                                .and_then(|n| n.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if buf.len() >= end + 4 + size {
                        break;
                    }
                }
            }
            requests.push(String::from_utf8(buf).unwrap());
            let body = response.to_string();
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    (api, handle)
}
#[test]
fn private_fields_and_activity_are_encrypted_and_bound() {
    let raw = raw_task();
    let encoded = raw.to_string();
    for private in ["Private task", "Private details", "Secret label"] {
        assert!(!encoded.contains(private));
    }
    let task = decrypt(raw, &[7; 32], &[7; 32], None).unwrap();
    assert_eq!(task.public["title"], "Private task");
    let entry_id = "b".repeat(64);
    let input = activity_input(
        &task,
        &TaskActivityInput {
            message: "Private comment".into(),
            entry_id: Some(entry_id.clone()),
            ..Default::default()
        },
    )
    .unwrap();
    assert!(!input.to_string().contains("Private comment"));
    let mut row = input;
    row["kind"] = json!("comment");
    assert_eq!(
        task_crypto::activity(&task, &row).unwrap()["message"],
        "Private comment"
    );
    row["entry_id"] = json!("other-entry");
    assert!(matches!(
        task_crypto::activity(&task, &row),
        Err(Error::Crypto)
    ));
    assert!(super::entry_id(&"a".repeat(64)).is_ok());
}
#[test]
fn team_key_wrappers_cannot_fall_back_to_personal_key() {
    let team = "cccccccc-1111-4111-8111-aabbccddeeff";
    let mut raw = encrypt_create(
        &TaskCreate {
            title: "Team secret".into(),
            ..Default::default()
        },
        &[7; 32],
        &[8; 32],
        Some(team),
    )
    .unwrap();
    assert!(decrypt(raw.clone(), &[7; 32], &[8; 32], Some(team)).is_ok());
    assert!(decrypt(raw.clone(), &[7; 32], &[7; 32], None).is_err());
    raw["key_wrappers"][0]["hashed_team_id"] = json!(hash("different-team"));
    assert!(matches!(
        decrypt(raw, &[7; 32], &[8; 32], Some(team)),
        Err(Error::Forbidden)
    ));
}
#[test]
fn nullable_patch_and_projection_controls_preserve_intent() {
    let missing: TaskPatch = serde_json::from_value(json!({})).unwrap();
    assert!(missing.primary_chat_id.is_none());
    let clear: TaskPatch = serde_json::from_value(json!({"chat_id":null,"plan_id":null})).unwrap();
    assert_eq!(clear.primary_chat_id, Some(None));
    assert_eq!(clear.plan_id, Some(None));
    let mut raw = json!({"source":"workflow_run","task_id":"workflow-schedule:trigger:123","projection_kind":"next_run","scheduled_at":123,"can_delete":true});
    let projection = decrypt(raw.clone(), &[7; 32], &[7; 32], None).unwrap();
    assert!(deletable(&projection).is_ok());
    assert!(readonly(&projection).is_err());
    raw["projection_kind"] = json!("current_run");
    assert!(deletable(&decrypt(raw, &[7; 32], &[7; 32], None).unwrap()).is_err());
}
#[tokio::test]
async fn ambient_codex_thread_does_not_mark_unlinked_creation() {
    let mut client = client("https://api.example.org");
    let tasks = client.tasks().with_caller(TaskCaller {
        codex_thread_id: Some(THREAD.into()),
        as_assignee: false,
    });
    let headers = tasks.owner_headers(None, false).unwrap();
    assert!(!headers.creator && !headers.assignee && headers.owner.is_none());
    let linked = tasks.owner_headers(None, true).unwrap();
    assert!(linked.creator && linked.assignee);
}
#[tokio::test]
async fn delivery_rejects_other_caller_before_network() {
    let mut client = client("https://api.example.org");
    let prepared = client
        .tasks()
        .with_caller(TaskCaller {
            codex_thread_id: Some(THREAD.into()),
            as_assignee: false,
        })
        .prepare_create(
            TaskCreate {
                title: "Private".into(),
                ..Default::default()
            },
            &"a".repeat(64),
        )
        .await
        .unwrap();
    assert!(matches!(
        client.tasks().execute_delivery(&prepared, true).await,
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        client
            .tasks()
            .with_caller(TaskCaller {
                codex_thread_id: Some(THREAD.into()),
                as_assignee: true
            })
            .execute_delivery(&prepared, true)
            .await,
        Err(Error::Forbidden)
    ));
}
#[test]
fn reconciliation_requires_exact_commit_and_preserves_conflicts() {
    let raw = raw_task();
    let create = delivery(TaskMutationKind::Create, raw.clone());
    let mut later = raw.clone();
    later["version"] = json!(4);
    later["encrypted_title"] = json!("a later legitimate edit");
    assert!(accepted(&create, Some(&later)).unwrap());
    let update = delivery(
        TaskMutationKind::Update,
        json!({"version":1,"encrypted_title":"new ciphertext"}),
    );
    assert!(!accepted(&update, Some(&raw)).unwrap());
    let mut committed = raw;
    committed["version"] = json!(2);
    committed["encrypted_title"] = json!("new ciphertext");
    assert!(accepted(&update, Some(&committed)).unwrap());
    committed["version"] = json!(3);
    assert!(matches!(
        accepted(&update, Some(&committed)),
        Err(Error::Conflict)
    ));
    let overflow = delivery(TaskMutationKind::Complete, json!({"version":u64::MAX}));
    committed["version"] = json!(u64::MAX);
    assert!(matches!(
        accepted(&overflow, Some(&committed)),
        Err(Error::Protocol)
    ));
    let activity =
        json!({"entry_id":"a","encrypted_message":"cipher","embed_refs":[],"created_at":1});
    let mut tombstone = activity.clone();
    tombstone["kind"] = json!("tombstone");
    assert!(!same_activity(&activity, &tombstone));
}
#[tokio::test]
async fn activity_search_counts_all_pages_but_only_message_matches() {
    let raw = raw_task();
    let resolved = decrypt(raw.clone(), &[7; 32], &[7; 32], None).unwrap();
    let row = |id: &str, message: &str| {
        let mut row = activity_input(
            &resolved,
            &TaskActivityInput {
                message: message.into(),
                entry_id: Some(id.into()),
                ..Default::default()
            },
        )
        .unwrap();
        row["kind"] = json!("comment");
        row["actor_display_name"] = json!("needle");
        row
    };
    let (api,server)=mock(vec![json!({"task":raw}),json!({"entries":[row("one","Needle first"),row("two","irrelevant")],"next_cursor":"second"}),json!({"entries":[row("three","needle second")],"next_cursor":null})]).await;
    let result = client(&api)
        .tasks()
        .activity_history(
            TASK,
            TaskActivityQuery {
                query: Some("needle".into()),
                max_entries: Some(1),
                ..Default::default()
            },
        )
        .await
        .unwrap();
    assert_eq!(result["entries"].as_array().unwrap().len(), 1);
    assert_eq!(result["matched"], 2);
    assert_eq!(result["truncated"], true);
    assert!(result["next_cursor"].is_null());
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests[2].contains("cursor=second"));
    assert!(
        requests
            .iter()
            .all(|r| r.to_ascii_lowercase().contains("x-openmates-sdk: rust"))
    );
}
#[tokio::test]
async fn scheduled_delete_reconciles_inventory_before_retry() {
    let id = "workflow-schedule:trigger:123";
    let projection = json!({"source":"workflow_run","task_id":id,"projection_kind":"next_run","scheduled_at":123,"can_delete":true});
    let (api, server) = mock(vec![
        json!({"tasks":[projection],"next_cursor":null,"complete":true}),
        json!({"tasks":[],"next_cursor":null,"complete":true}),
    ])
    .await;
    let mut client = client(&api);
    let prepared = client
        .tasks()
        .prepare_delete(id, &"a".repeat(64), true)
        .await
        .unwrap();
    let result = client
        .tasks()
        .execute_delivery(&prepared, true)
        .await
        .unwrap();
    assert_eq!(result["deleted"], true);
    assert_eq!(result["task_id"], id);
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 2);
    assert!(
        requests
            .iter()
            .all(|r| r.starts_with("GET /v1/user-tasks?"))
    );
}
#[test]
fn sdk_identities_are_explicit_and_default_to_rust() {
    assert_eq!(ClientOptions::default().identity, ClientIdentity::Rust);
    for (identity, header) in [
        (ClientIdentity::Rust, "rust"),
        (ClientIdentity::Npm, "npm"),
        (ClientIdentity::Pip, "pip"),
        (ClientIdentity::Cli, "cli"),
    ] {
        assert_eq!(identity.header(), header);
    }
}

#[tokio::test]
async fn sdk_identity_never_claims_human_presence_and_ai_gate_precedes_network() {
    let mut client = client("https://api.example.org");
    client.set_interactive(true);
    for identity in [
        ClientIdentity::Rust,
        ClientIdentity::Npm,
        ClientIdentity::Pip,
    ] {
        client.set_identity(identity);
        assert_eq!(client.lifecycle()["interactive"], false);
        assert_eq!(client.lifecycle()["is_foreground"], true);
        assert_eq!(client.lifecycle()["client_type"], identity.header());
    }
    client.set_identity(ClientIdentity::Cli);
    assert_eq!(client.lifecycle()["interactive"], true);
    client.set_private_operation_gate(Some(std::sync::Arc::new(|| Err(Error::Forbidden))));
    assert!(matches!(
        client.tasks().start(TASK).await,
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        client
            .tasks()
            .ask("Prepare copy", TaskAskOptions::default())
            .await,
        Err(Error::Forbidden)
    ));
}

#[tokio::test]
async fn ai_task_creation_cannot_bypass_private_operation_policy() {
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    let denied = Arc::new(AtomicUsize::new(0));
    let observed = denied.clone();
    let mut client = client("https://api.example.invalid");
    client.set_private_operation_gate(Some(Arc::new(move || {
        observed.fetch_add(1, Ordering::SeqCst);
        Err(Error::Forbidden)
    })));
    let input = TaskCreate {
        title: "Private AI context".into(),
        description: "Private details".into(),
        assign: Some("openmates".into()),
        ..Default::default()
    };
    assert!(matches!(
        client.tasks().create(input.clone()).await,
        Err(Error::Forbidden)
    ));
    // Preparing caller-owned ciphertext cannot authorize later dispatch.
    let intent = client
        .tasks()
        .prepare_create(input, &"a".repeat(64))
        .await
        .unwrap();
    let wire = serde_json::to_string(&intent).unwrap();
    assert!(!wire.contains("Private AI context"));
    assert!(!wire.contains("Private details"));
    assert_eq!(denied.load(Ordering::SeqCst), 1);
    for uncertain in [false, true] {
        assert!(matches!(
            client.tasks().execute_delivery(&intent, uncertain).await,
            Err(Error::Forbidden)
        ));
    }
    assert_eq!(denied.load(Ordering::SeqCst), 3);
    client.set_private_operation_gate(None);
    client.set_privacy_options(crate::privacy::PrivacyOptions { enhanced: true });
    assert!(matches!(
        client.tasks().execute_delivery(&intent, false).await,
        Err(Error::Invalid(_))
    ));
}

#[tokio::test]
async fn canonical_master_wrapper_hydrates_cookie_and_api_key_inventory() {
    use base64::{Engine, engine::general_purpose::STANDARD};
    let mut raw = raw_task();
    let encrypted = raw
        .as_object_mut()
        .unwrap()
        .remove("encrypted_task_key")
        .unwrap();
    let wrappers =
        json!([{"key_type":"master","hashed_task_id":hash(TASK),"encrypted_task_key":encrypted}]);
    let (api, server) = mock(vec![json!({"task":raw}), json!({"key_wrappers":wrappers})]).await;
    let mut cookie = client(&api);
    assert_eq!(
        cookie.tasks().show(TASK).await.unwrap()["title"],
        "Private task"
    );
    let requests = server.await.unwrap();
    assert!(requests[1].starts_with(&format!("GET /v1/user-tasks/{TASK}/key-wrappers ")));

    let salt = [3; 16];
    let iv = [4; 12];
    let mut wrapping = zeroize::Zeroizing::new([0; 32]);
    let suffix = "s".repeat(32);
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>(suffix.as_bytes(), &salt, 100_000, &mut *wrapping);
    let encrypted_master = crypto::encrypt_aead(&[7; 32], &wrapping, &iv, &[]).unwrap();
    let session = json!({"key_wrapper":{"salt":STANDARD.encode(salt),"key_iv":STANDARD.encode(iv),"encrypted_key":STANDARD.encode(encrypted_master)}});
    let (api, server) = mock(vec![
        session,
        json!({"tasks":[raw],"complete":true}),
        json!({"key_wrappers":wrappers}),
    ])
    .await;
    let mut sdk = OpenMates::new(crate::SdkOptions {
        api_url: api,
        credentials: crate::SdkCredentials::ApiKey(
            crate::ApiKey::new(&format!("sk-api-{}.{}", "b".repeat(32), suffix)).unwrap(),
        ),
        device_id: "fixture".into(),
        client_options: Default::default(),
    })
    .unwrap();
    assert_eq!(
        sdk.tasks().show(TASK).await.unwrap()["title"],
        "Private task"
    );
    let requests = server.await.unwrap();
    assert!(requests[1].starts_with("GET /v1/user-tasks?"));
    assert!(requests[2].starts_with(&format!("GET /v1/user-tasks/{TASK}/key-wrappers ")));
    assert!(
        !requests
            .iter()
            .any(|request| request.starts_with(&format!("GET /v1/user-tasks/{TASK} ")))
    );
}

#[test]
fn canonical_task_wrappers_reject_ambiguity_wrong_object_and_scope() {
    let mut raw = raw_task();
    let encrypted = raw
        .as_object_mut()
        .unwrap()
        .remove("encrypted_task_key")
        .unwrap();
    let wrapper =
        json!({"key_type":"master","hashed_task_id":hash(TASK),"encrypted_task_key":encrypted});
    raw["key_wrappers"] = json!([wrapper]);
    assert_eq!(
        decrypt(raw.clone(), &[7; 32], &[7; 32], None)
            .unwrap()
            .public["title"],
        "Private task"
    );
    raw["key_wrappers"][0]["hashed_task_id"] = json!(hash(THREAD));
    assert!(matches!(
        decrypt(raw.clone(), &[7; 32], &[7; 32], None),
        Err(Error::Forbidden)
    ));
    raw["key_wrappers"] = json!([wrapper, wrapper]);
    assert!(matches!(
        decrypt(raw.clone(), &[7; 32], &[7; 32], None),
        Err(Error::Forbidden)
    ));
    raw["key_wrappers"] = json!([wrapper]);
    raw["hashed_team_id"] = json!(hash(THREAD));
    assert!(matches!(
        decrypt(raw.clone(), &[7; 32], &[7; 32], None),
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        decrypt(raw, &[7; 32], &[7; 32], Some(THREAD)),
        Err(Error::Forbidden)
    ));
}

#[tokio::test]
async fn cancelled_cookie_task_create_never_admits_a_new_write() {
    let mut client = client("http://127.0.0.1:1");
    let parent = tokio_util::sync::CancellationToken::new();
    client.set_operation_cancel(parent.clone());
    parent.cancel();
    assert_eq!(
        client
            .tasks()
            .create(TaskCreate {
                title: "Must never be dispatched".into(),
                ..Default::default()
            })
            .await,
        Err(Error::Cancelled)
    );
    assert!(parent.is_cancelled());
}


// contract-test: supporting surface=sdks.rust assertions=tasks.surface.semantic-parity
#[test]
fn task_move_omits_unset_fields_but_keeps_explicit_zero_and_status() {
    for (movement,expected) in [
        (TaskMove{position:Some(200),..Default::default()},json!({"position":200})),
        (TaskMove{position:Some(0),..Default::default()},json!({"position":0})),
        (TaskMove{before_task_id:Some(TASK.into()),..Default::default()},json!({"before_task_id":TASK})),
        (TaskMove{after_task_id:Some(TASK.into()),..Default::default()},json!({"after_task_id":TASK})),
        (TaskMove{status:Some("blocked".into()),position:Some(-1),..Default::default()},json!({"status":"blocked","position":-1})),
    ] { assert_eq!(serde_json::to_value(movement).unwrap(),expected); }
    assert_eq!(serde_json::to_value(TaskMove::default()).unwrap(),json!({}));
}
// contract-test: supporting surface=sdks.rust assertions=tasks.surface.semantic-parity
#[tokio::test]
async fn position_reorder_preserves_owner_version_and_absent_status_on_wire() {
    let raw=raw_task();let mut updated=raw.clone();updated["position"]=json!(200);updated["version"]=json!(2);
    let (api,server)=mock(vec![json!({"task":raw}),json!({"tasks":[updated]})]).await;
    let result=client(&api).tasks().reorder(TASK,TaskMove{position:Some(200),..Default::default()}).await.unwrap();
    assert_eq!(result.len(),1);assert_eq!(result[0]["status"],"todo");assert_eq!(result[0]["position"],200);
    let requests=server.await.unwrap();assert_eq!(requests.len(),2);
    assert!(requests[1].starts_with("POST /v1/user-tasks/reorder "));
    let body:Value=serde_json::from_str(requests[1].split_once("\r\n\r\n").unwrap().1).unwrap();
    assert_eq!(body,json!({"moves":[{"task_id":TASK,"version":1,"position":200}],"team_id":null}));
    assert!(requests.iter().all(|r|r.to_ascii_lowercase().contains("x-openmates-sdk: rust")));
}
// contract-test: supporting surface=sdks.rust assertions=tasks.surface.semantic-parity
#[tokio::test]
async fn anchored_reorder_omits_null_position_and_resolves_canonical_anchor() {
    let raw=raw_task();let mut anchor=raw.clone();anchor["task_id"]=json!(THREAD);
    let mut updated=raw.clone();updated["position"]=json!(499);updated["version"]=json!(2);
    let (api,server)=mock(vec![json!({"task":raw}),json!({"task":anchor}),json!({"tasks":[updated]})]).await;
    let result=client(&api).tasks().reorder(TASK,TaskMove{before_task_id:Some(THREAD.into()),..Default::default()}).await.unwrap();
    assert_eq!(result[0]["status"],"todo");assert_eq!(result[0]["position"],499);
    let requests=server.await.unwrap();assert_eq!(requests.len(),3);
    let body:Value=serde_json::from_str(requests[2].split_once("\r\n\r\n").unwrap().1).unwrap();
    assert_eq!(body,json!({"moves":[{"task_id":TASK,"version":1,"before_task_id":THREAD}],"team_id":null}));
}
