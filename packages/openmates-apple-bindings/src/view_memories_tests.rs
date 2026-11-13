//! Memories through `ViewModelCore` against a loopback API that keeps the encrypted account settings: create, list, read, update, delete and the expiry sweep round-trip only ciphertext, refusals carry the web codes, signed-out and cancelled calls are typed, and chat notices parse.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{core, session};
use crate::*;
use serde_json::{Value, json};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

/// The stored `encrypted_settings` and the settings write bodies.
#[derive(Default)]
struct Settings {
    ciphertext: Mutex<Option<String>>,
    writes: Mutex<Vec<String>>,
    refuse: AtomicBool,
}

/// Admission returns the stored settings; a settings write stores them
/// (or is refused with `success: false`); logout answers.
async fn api(settings: Arc<Settings>) -> LoopbackApi {
    serve(move |line, body| {
        if line.starts_with("POST /v1/auth/session ") {
            let stored = settings.ciphertext.lock().unwrap().clone();
            return Reply::Json(json!({"success": true, "ws_token": "synthetic-ws",
                "user": {"id": "synthetic-user", "username": "Synthetic Tester",
                    "encrypted_settings": stored}}));
        }
        if line.starts_with("POST /v1/settings/encrypted-account ") {
            if settings.refuse.load(Ordering::SeqCst) {
                return Reply::Json(json!({"success": false}));
            }
            let ciphertext = body["encrypted_settings"]
                .as_str()
                .unwrap_or_default()
                .to_owned();
            settings.writes.lock().unwrap().push(body.to_string());
            *settings.ciphertext.lock().unwrap() = Some(ciphertext);
            return Reply::Json(json!({"success": true}));
        }
        if line.starts_with("POST /v1/auth/logout ") {
            return Reply::Json(json!({"success": true}));
        }
        Reply::Close
    })
    .await
}

async fn signed_in() -> (
    tempfile::TempDir,
    LoopbackApi,
    Arc<Settings>,
    Arc<ViewModelCore>,
) {
    let (dir, settings) = (private_dir(), Arc::new(Settings::default()));
    let api = api(settings.clone()).await;
    let stored = session(&api.url, "synthetic-session-1");
    let (keychain, events) = (
        Keychain::holding(&stored, true),
        Arc::new(Events::default()),
    );
    let core = core(dir.path(), &api.url, &keychain, &events);
    core.start(None).await.unwrap();
    (dir, api, settings, core)
}

fn fields(title: &str, body: &str) -> MemoryFieldsRecord {
    MemoryFieldsRecord {
        title: title.into(),
        description: None,
        when_to_use: "When writing applications.".into(),
        body: body.into(),
        load_mode: Some(MemoryLoadModeRecord::AskFirst),
        valid_from: None,
        valid_until: None,
        references: vec!["synthetic-embed".into()],
        app_id: Some("jobs".into()),
    }
}

fn code(result: Result<impl Sized, CoreError>) -> String {
    match result {
        Err(CoreError::Memory { code }) => code,
        Err(other) => panic!("not a Memory refusal: {other:?}"),
        Ok(_) => panic!("not refused"),
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn create_list_update_and_delete_round_trip_only_ciphertext() {
    let (_dir, _api, settings, core) = signed_in().await;
    let created = core
        .create_memory_document(fields("Career profile", "Senior Rust engineer."), None)
        .await
        .unwrap();
    assert!(created.id.starts_with("personal:"));
    let read = created.fields.clone().unwrap();
    assert_eq!(read.title, "Career profile");
    assert_eq!(read.load_mode, Some(MemoryLoadModeRecord::AskFirst));
    assert_eq!(read.references, ["synthetic-embed"]);
    assert_eq!(created.created_at, created.updated_at);
    assert!(created.created_at.is_some() && !created.expired);
    // The server only ever sees master-key ciphertext.
    let writes = settings.writes.lock().unwrap().clone();
    assert_eq!(writes.len(), 1);
    assert!(!writes[0].contains("Career") && !writes[0].contains("memory_documents"));

    let listed = core.list_memory_documents(None).await.unwrap();
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].id, created.id);
    assert_eq!(listed[0].document, created.document);

    let updated = core
        .update_memory_document(
            created.id.clone(),
            fields("Career profile", "Staff Rust engineer."),
            None,
        )
        .await
        .unwrap();
    assert_eq!(updated.fields.unwrap().body, "Staff Rust engineer.");
    assert_eq!(updated.created_at, created.created_at);
    let one = core
        .memory_document(created.id.clone(), None)
        .await
        .unwrap();
    assert_eq!(one.document, updated.document);

    core.delete_memory_document(created.id.clone(), None)
        .await
        .unwrap();
    assert!(core.list_memory_documents(None).await.unwrap().is_empty());
    assert_eq!(
        code(core.memory_document(created.id, None).await),
        "rule_not_found"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn refusals_carry_the_web_codes_and_invalid_fields_write_nothing() {
    let (_dir, _api, settings, core) = signed_in().await;
    assert_eq!(
        code(
            core.update_memory_document("personal:missing".into(), fields("T", "B"), None)
                .await
        ),
        "rule_not_found"
    );
    assert_eq!(
        code(
            core.create_memory_document(fields("  ", "Body"), None)
                .await
        ),
        "invalid_rule_document"
    );
    let mut bad_date = fields("T", "B");
    bad_date.valid_until = Some("tomorrow".into());
    assert_eq!(
        code(core.create_memory_document(bad_date, None).await),
        "invalid_rule_document"
    );
    assert!(settings.writes.lock().unwrap().is_empty());
    settings.refuse.store(true, Ordering::SeqCst);
    assert_eq!(
        code(core.create_memory_document(fields("T", "B"), None).await),
        "rule_save_failed"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn the_expiry_sweep_deletes_only_expired_memories() {
    let (_dir, _api, _settings, core) = signed_in().await;
    let mut expired = fields("Old offer", "Expired.");
    expired.valid_until = Some("2020-01-31T23:59:59.000Z".into());
    let expired = core.create_memory_document(expired, None).await.unwrap();
    assert!(expired.expired);
    let kept = core
        .create_memory_document(fields("Kept", "Still valid."), None)
        .await
        .unwrap();
    assert_eq!(core.delete_expired_memory_documents(None).await.unwrap(), 1);
    let left: Vec<String> = core
        .list_memory_documents(None)
        .await
        .unwrap()
        .into_iter()
        .map(|record| record.id)
        .collect();
    assert_eq!(left, [kept.id]);
}

#[tokio::test(flavor = "multi_thread")]
async fn signed_out_and_cancelled_calls_are_typed() {
    let dir = private_dir();
    let api = api(Arc::default()).await;
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let signed_out = core(dir.path(), &api.url, &keychain, &events);
    assert!(matches!(
        signed_out.list_memory_documents(None).await,
        Err(CoreError::Authentication)
    ));
    let (_dir, _api, settings, core) = signed_in().await;
    let cancellation = CoreCancellation::new();
    cancellation.cancel();
    assert!(matches!(
        core.create_memory_document(fields("T", "B"), Some(cancellation))
            .await,
        Err(CoreError::Cancelled)
    ));
    assert!(settings.writes.lock().unwrap().is_empty());
    // The session is kept after a cancel.
    assert!(core.list_memory_documents(None).await.unwrap().is_empty());
}

#[tokio::test(flavor = "multi_thread")]
async fn the_assistant_write_opt_in_is_off_until_swift_switches_it_on() {
    let (_dir, _api, _settings, core) = signed_in().await;
    assert!(!core.shared.memory_write_jobs.load(Ordering::SeqCst));
    core.set_assistant_memory_writes(true);
    assert!(core.shared.memory_write_jobs.load(Ordering::SeqCst));
}

#[test]
fn chat_notices_parse_with_their_undo_job() {
    let event: Value = json!({"schema_version": 1, "type": "context_entry", "kind": "memory",
        "action": "created", "entry_id": "personal:synthetic", "title": "Career profile",
        "created_at": 1_762_000_000, "source": "assistant",
        "undo": {"job_id": "memory-write-job-1", "action": "create",
            "written_document_sha256": "0".repeat(64)}});
    let notice = context_entry_notice(event.to_string()).unwrap();
    assert_eq!(notice.kind, ContextEntryKindRecord::Memory);
    assert_eq!(notice.action, ContextEntryActionRecord::Created);
    assert_eq!(notice.entry_id, "personal:synthetic");
    assert!(notice.from_assistant);
    assert_eq!(notice.undo_job_id.as_deref(), Some("memory-write-job-1"));
    assert!(context_entry_notice("Plain system text".into()).is_none());
}
