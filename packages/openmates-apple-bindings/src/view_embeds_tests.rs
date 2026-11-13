//! Embed versions, Enhance and embed-updated events on `ViewModelCore` against a loopback API: history pages with provenance, job reads and failures as typed errors, the pending-notice reconcile, cancellation, signed-out refusal, error mapping and the timeline grouping.
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{core, read_request, session};
use crate::*;
use openmates_sdk::Error;
use openmates_sdk::client::embed_user_revision::UserRevisionError;
use openmates_sdk::client::image_enhance::ImageEnhanceError;
use serde_json::{Value, json};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::AsyncWriteExt;

/// Request lines in arrival order.
type Log = Arc<Mutex<Vec<String>>>;

const EMBED: &str = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d";
const CHAT: &str = "9a8b7c6d-5e4f-4321-8765-0fedcba98765";
const PENDING_JOB: &str = "11111111-2222-4333-8444-555555555555";
const FAILED_JOB: &str = "66666666-7777-4888-8999-aaaaaaaaaaaa";
const HANGING_EMBED: &str = "00000000-0000-4000-8000-000000000000";

fn reply(body: &Value) -> String {
    let body = body.to_string();
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
}

fn job(operation_id: &str, state: &str) -> Value {
    json!({"operation_id": operation_id, "embed_id": EMBED, "state": state,
        "base_version": 2, "target_version": 3, "credits": 5, "charged": state != "failed",
        "created_at": 1_700_000_000, "expires_at": 1_700_086_400,
        "error_code": if state == "failed" { json!("provider_error") } else { Value::Null }})
}

/// Admission; two version pages; an Enhance job that stays pending and one
/// that failed; an empty pending-notice list; a version list that hangs.
async fn api() -> (String, Log) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let log: Log = Arc::default();
    let requests = log.clone();
    tokio::spawn(async move {
        while let Ok((mut stream, _)) = listener.accept().await {
            let requests = requests.clone();
            tokio::spawn(async move {
                let raw = read_request(&mut stream).await;
                let line = raw.lines().next().unwrap_or_default().to_owned();
                requests.lock().unwrap().push(line.clone());
                let versions = format!("GET /v1/embeds/{EMBED}/versions?");
                let body = if line.starts_with("POST /v1/auth/session ") {
                    json!({"success": true, "ws_token": "synthetic-ws",
                        "user": {"id": "synthetic-user", "username": "Synthetic Tester"}})
                } else if line.starts_with(&versions) && line.contains("cursor=0&") {
                    json!({"embed_id": EMBED, "current_version": 3, "next_cursor": 2,
                        "versions": [
                            {"version_number": 1, "created_at": 1_700_000_000,
                                "revision_origin": "assistant", "revision_action": null},
                            {"version_number": 2, "created_at": 1_700_000_100,
                                "revision_origin": "user", "revision_action": "edit"}]})
                } else if line.starts_with(&versions) && line.contains("cursor=2&") {
                    json!({"embed_id": EMBED, "current_version": 3, "next_cursor": null,
                        "versions": [{"version_number": 3, "created_at": 1_700_000_200,
                            "revision_origin": "user", "revision_action": "enhance"}]})
                } else if line.starts_with(&format!("GET /v1/images/enhance/{PENDING_JOB} ")) {
                    job(PENDING_JOB, "pending")
                } else if line.starts_with(&format!("GET /v1/images/enhance/{FAILED_JOB} ")) {
                    job(FAILED_JOB, "failed")
                } else if line.starts_with(&format!("GET /v1/chats/{CHAT}/pending-embed-notices")) {
                    json!({"chat_id": CHAT, "notices": []})
                } else if line.starts_with(&format!("GET /v1/embeds/{HANGING_EMBED}/versions")) {
                    tokio::time::sleep(Duration::from_secs(30)).await;
                    return;
                } else {
                    return;
                };
                let _ = stream.write_all(reply(&body).as_bytes()).await;
            });
        }
    });
    (url, log)
}

async fn signed_in() -> (tempfile::TempDir, Log, Arc<ViewModelCore>) {
    let dir = private_dir();
    let (url, log) = api().await;
    let stored = session(&url, "synthetic-session-1");
    let (keychain, events) = (
        Keychain::holding(&stored, true),
        Arc::new(Events::default()),
    );
    let core = core(dir.path(), &url, &keychain, &events);
    core.start(None).await.unwrap();
    (dir, log, core)
}

fn chat_scope() -> EmbedScopeRecord {
    EmbedScopeRecord::Chat {
        chat_id: CHAT.into(),
        team_id: None,
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn version_history_reads_every_page_with_who_made_each_version() {
    let (_dir, log, core) = signed_in().await;
    let history = core
        .embed_version_history(EMBED.into(), Some(chat_scope()), None)
        .await
        .unwrap();
    assert_eq!(history.embed_id, EMBED);
    assert_eq!(history.current_version, 3);
    let summary: Vec<_> = history
        .versions
        .iter()
        .map(|v| (v.version, v.origin, v.action, v.is_current))
        .collect();
    assert_eq!(
        summary,
        vec![
            (1, EmbedRevisionOriginRecord::Assistant, None, false),
            (
                2,
                EmbedRevisionOriginRecord::User,
                Some(EmbedUpdateActionRecord::Edit),
                false
            ),
            (
                3,
                EmbedRevisionOriginRecord::User,
                Some(EmbedUpdateActionRecord::Enhance),
                true
            ),
        ]
    );
    assert_eq!(history.versions[2].created_at, Some(1_700_000_200));
    let pages: Vec<String> = log
        .lock()
        .unwrap()
        .iter()
        .filter(|line| line.contains("/versions?"))
        .cloned()
        .collect();
    assert_eq!(pages.len(), 2);
    assert!(pages[0].contains(&format!("chat_id={CHAT}")));
    assert!(pages[1].contains("order=asc"));
}

#[tokio::test(flavor = "multi_thread")]
async fn enhance_job_reads_come_back_as_records_and_typed_failures() {
    let (_dir, _log, core) = signed_in().await;
    let pending = core
        .image_enhance_status(PENDING_JOB.into(), None)
        .await
        .unwrap();
    assert_eq!(pending.state, ImageEnhanceStateRecord::Pending);
    assert_eq!((pending.base_version, pending.target_version), (2, 3));
    assert!(pending.charged);
    let failed = core
        .wait_image_enhance(
            FAILED_JOB.into(),
            Some(5_000),
            Some(ImageEnhanceWaker::new()),
            None,
        )
        .await;
    assert_eq!(
        failed,
        Err(EmbedEditError::EnhanceFailed {
            operation_id: FAILED_JOB.into(),
            code: "provider_error".into()
        })
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_pending_wait_ends_as_a_timeout_that_names_the_job() {
    let (_dir, _log, core) = signed_in().await;
    let waited = core
        .wait_image_enhance(PENDING_JOB.into(), Some(300), None, None)
        .await;
    assert_eq!(
        waited,
        Err(EmbedEditError::EnhanceTimeout {
            operation_id: PENDING_JOB.into()
        })
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn reconcile_without_pending_notices_writes_nothing() {
    let (_dir, _log, core) = signed_in().await;
    let report = core
        .reconcile_embed_update_notices(CHAT.into(), None)
        .await
        .unwrap();
    assert_eq!(
        report,
        EmbedNoticeReconcileRecord {
            written: 0,
            already_present: 0,
            unresolved_message_ids: vec![],
            deferred_code: None,
        }
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_cancelled_history_read_settles_as_cancelled_and_keeps_the_session() {
    let (_dir, _log, core) = signed_in().await;
    let cancellation = CoreCancellation::new();
    let cancel = cancellation.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(200)).await;
        cancel.cancel();
    });
    let outcome = tokio::time::timeout(
        Duration::from_secs(10),
        core.embed_version_history(HANGING_EMBED.into(), None, Some(cancellation)),
    )
    .await
    .expect("the cancelled read settles");
    assert_eq!(outcome, Err(EmbedEditError::Cancelled));
    let history = core
        .embed_version_history(EMBED.into(), Some(chat_scope()), None)
        .await;
    assert!(history.is_ok());
}

#[tokio::test(flavor = "multi_thread")]
async fn signed_out_embed_commands_are_refused_before_any_request() {
    let dir = private_dir();
    let (url, log) = api().await;
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), &url, &keychain, &events);
    assert_eq!(
        core.embed_version_history(EMBED.into(), None, None).await,
        Err(EmbedEditError::Authentication)
    );
    assert_eq!(
        core.restore_embed_version(EMBED.into(), chat_scope(), 1, None)
            .await,
        Err(EmbedEditError::Authentication)
    );
    assert!(log.lock().unwrap().is_empty());
}

#[test]
fn core_refusals_map_to_stable_typed_errors() {
    assert_eq!(
        EmbedEditError::from(UserRevisionError::VersionConflict {
            current_revision: Some(4),
            current_content_hash: None,
        }),
        EmbedEditError::VersionConflict {
            current_version: Some(4)
        }
    );
    assert_eq!(
        EmbedEditError::from(UserRevisionError::Refused {
            code: "restore_source_missing"
        }),
        EmbedEditError::Refused {
            code: "restore_source_missing".into()
        }
    );
    assert_eq!(
        EmbedEditError::from(UserRevisionError::Transport(Error::Offline)),
        EmbedEditError::Offline
    );
    assert_eq!(
        EmbedEditError::from(ImageEnhanceError::InsufficientCredits),
        EmbedEditError::InsufficientCredits
    );
    assert_eq!(
        EmbedEditError::from(ImageEnhanceError::Revision(
            UserRevisionError::ProjectContextRequired
        )),
        EmbedEditError::ProjectContextRequired
    );
    assert_eq!(
        EmbedEditError::from(ImageEnhanceError::Transport(Error::Expired)),
        EmbedEditError::SessionExpired
    );
}

#[test]
fn a_waker_wakes_only_on_enhance_frames_and_refuses_non_json() {
    let waker = ImageEnhanceWaker::new();
    let payload = json!({"operation_id": PENDING_JOB, "embed_id": EMBED}).to_string();
    assert!(
        waker
            .notify_frame("image_enhance_ready".into(), payload.clone())
            .unwrap()
    );
    assert!(!waker.notify_frame("chat_message".into(), payload).unwrap());
    assert!(matches!(
        waker.notify_frame("image_enhance_ready".into(), "{".into()),
        Err(CoreError::Invalid { .. })
    ));
}

fn event(version: i64, action: &str) -> String {
    let mut value = json!({"schema_version": 1, "type": "embed_updated", "embed_id": "embed-a",
        "embed_ref": "sunset-photo", "embed_kind": "image", "version": version,
        "base_version": version - 1, "action": action, "surface": "chat",
        "created_at": 1_700_000_000 + version});
    if action == "restore" {
        value["restored_from"] = json!(1);
    }
    value.to_string()
}

fn row(id: &str, role: MessageRoleRecord, content: String) -> EmbedTimelineRowRecord {
    EmbedTimelineRowRecord {
        message_id: id.into(),
        role,
        content,
    }
}

#[test]
fn consecutive_events_of_one_embed_fold_into_one_timeline_notice() {
    let rows = vec![
        row("m1", MessageRoleRecord::User, "Make it brighter".into()),
        row("e2", MessageRoleRecord::System, event(2, "enhance")),
        row("e3", MessageRoleRecord::System, event(3, "restore")),
        row("m4", MessageRoleRecord::Assistant, "Done.".into()),
        // A user message with an event payload stays an ordinary message.
        row("m5", MessageRoleRecord::User, event(4, "edit")),
    ];
    let items = embed_update_timeline(rows);
    assert_eq!(items.len(), 4);
    assert_eq!(
        items[0],
        EmbedTimelineItemRecord::Message {
            index: 0,
            message_id: "m1".into()
        }
    );
    let EmbedTimelineItemRecord::EmbedUpdated { group } = &items[1] else {
        panic!("expected a folded run, got {:?}", items[1]);
    };
    assert_eq!(group.embed_kind, EmbedKindRecord::Image);
    assert_eq!(group.change_count, 2);
    assert_eq!(group.latest_version, 3);
    assert_eq!(group.latest_action, EmbedUpdateActionRecord::Restore);
    assert_eq!(group.restored_from, Some(1));
    assert_eq!(group.surface, EmbedUpdateSurfaceRecord::Chat);
    assert_eq!(group.message_ids, vec!["e2".to_owned(), "e3".to_owned()]);
    assert_eq!(
        items[3],
        EmbedTimelineItemRecord::Message {
            index: 4,
            message_id: "m5".into()
        }
    );
}
