//! User-revision request building (chat and Project scope), CAS hash, conflicts, base-snapshot and lost-answer retries, restore, cache-after-receipt and refusal classification.
use super::refusal::classify;
use super::*;
use crate::client::embed_updated_event::{
    EmbedKind, build_embed_updated_event, parse_embed_updated_event,
};
use crate::client::embed_write::keys::decrypt_text;

const EMBED: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const PROJECT: &str = "33333333-3333-4333-8333-333333333333";
const KEY: [u8; 32] = [7; 32];
const NOW_MS: i64 = 1_800_000_000_000;

struct CountingNonces(u8);
impl NonceSource for CountingNonces {
    fn next_nonce(&mut self) -> crate::error::Result<[u8; 12]> {
        self.0 += 1;
        Ok([self.0; 12])
    }
}

fn head() -> EmbedHead {
    let mut nonces = CountingNonces(200);
    EmbedHead {
        embed_id: EMBED.into(),
        version: 2,
        encrypted_content: encrypt_text(
            "title: Kitchen plan\nversion_number: 2",
            &KEY,
            None,
            &mut nonces,
        )
        .expect("seal"),
        created_at: 1_700_000_000,
        hashed_chat_id: Some(hash_id(CHAT)),
    }
}

fn chat_scope() -> RevisionScope {
    RevisionScope::Chat {
        chat_id: CHAT.into(),
        team_id: None,
    }
}

fn edit(scope: RevisionScope) -> UserRevisionRequest {
    UserRevisionRequest {
        head: head(),
        scope,
        action: EmbedUpdateAction::Edit,
        content: Zeroizing::new("title: Kitchen plan v3\nversion_number: 3".into()),
        text_preview: Some(Zeroizing::new("Kitchen plan v3".into())),
        restored_from: None,
        files: None,
        media_index: None,
        operation_id: Some("op-1".into()),
    }
}

fn prepare(request: &UserRevisionRequest) -> PreparedUserRevision {
    prepare_user_revision(request, &KEY, NOW_MS, &mut CountingNonces(0)).expect("prepare")
}

fn committed_response(prepared: &PreparedUserRevision, idempotent: bool) -> Value {
    json!({"status": "committed", "operation_id": prepared.operation_id(), "embed_id": EMBED,
        "current_revision": prepared.version(), "current_content_hash": hash_id(&prepared.head_ciphertext),
        "revision_origin": "user", "revision_action": "edit", "idempotent": idempotent,
        "pending_notice": true, "media_index_repointed": false})
}

/// Scripted server: one answer per POST, records bodies and cache writes.
struct Fake {
    answers: Vec<RevisionResult<Value>>,
    posted: Vec<Value>,
    stored: Vec<CommittedUserRevision>,
    fail_store: bool,
}

impl Fake {
    fn new(answers: Vec<RevisionResult<Value>>) -> Self {
        Self {
            answers,
            posted: Vec::new(),
            stored: Vec::new(),
            fail_store: false,
        }
    }
}

impl UserRevisionIo for Fake {
    async fn post_user_revision(&mut self, embed_id: &str, body: &Value) -> RevisionResult<Value> {
        assert_eq!(embed_id, EMBED);
        self.posted.push(body.clone());
        assert!(!self.answers.is_empty(), "unexpected extra POST");
        self.answers.remove(0)
    }
    async fn store_committed(
        &mut self,
        committed: &CommittedUserRevision,
    ) -> crate::error::Result<()> {
        if self.fail_store {
            return Err(Error::Io);
        }
        self.stored.push(committed.clone());
        Ok(())
    }
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.edit.next-version,embed-user-edits.history.one-per-embed
#[test]
fn builds_the_chat_scope_body_with_the_cached_head_hash() {
    let request = edit(chat_scope());
    let prepared = prepare(&request);
    let body = prepared.body();
    assert_eq!(body["scope"], json!({"kind": "chat", "chat_id": CHAT}));
    assert_eq!(body["operation_id"], "op-1");
    assert_eq!(body["action"], "edit");
    assert_eq!(body["expected_revision"], 2);
    assert_eq!(
        body["expected_content_hash"],
        hash_id(&request.head.encrypted_content)
    );
    assert!(
        body.get("restored_from").is_none()
            && body.get("files").is_none()
            && body.get("media_index").is_none()
    );
    let head_ct = body["head"]["encrypted_content"].as_str().expect("head");
    assert_eq!(
        decrypt_text(head_ct, &KEY, None).expect("open").as_str(),
        "title: Kitchen plan v3\nversion_number: 3"
    );
    let preview = body["head"]["encrypted_text_preview"]
        .as_str()
        .expect("preview");
    assert_eq!(
        decrypt_text(preview, &KEY, None).expect("open").as_str(),
        "Kitchen plan v3"
    );
    assert_eq!(body["head"]["content_hash"], hash_id(head_ct));
    assert_eq!(body["head"]["status"], "finished");
    assert_eq!(body["head"]["updated_at"], NOW_MS / 1000);
    // Only version N+1; its snapshot is the new head ciphertext.
    assert_eq!(
        body["history_rows"],
        json!([{"version_number": 3, "encrypted_snapshot": head_ct, "created_at": NOW_MS / 1000}])
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.history.one-per-embed
#[test]
fn builds_the_project_scope_body_with_team() {
    let scope = RevisionScope::Project {
        project_id: PROJECT.into(),
        team_id: Some("team-1".into()),
    };
    let prepared = prepare(&edit(scope));
    assert_eq!(
        prepared.body()["scope"],
        json!({"kind": "project", "project_id": PROJECT, "team_id": "team-1"})
    );
    assert_eq!(prepared.surface, EmbedUpdateSurface::Project);
}

#[test]
fn refuses_requests_the_server_would_refuse() {
    let code = |request: UserRevisionRequest| {
        prepare_user_revision(&request, &KEY, NOW_MS, &mut CountingNonces(0))
            .err()
            .map(|e| e.code())
    };
    let mut restore_without_source = edit(chat_scope());
    restore_without_source.action = EmbedUpdateAction::Restore;
    assert_eq!(code(restore_without_source), Some("invalid_restored_from"));
    let mut edit_with_source = edit(chat_scope());
    edit_with_source.restored_from = Some(1);
    assert_eq!(code(edit_with_source), Some("invalid_restored_from"));
    let mut files_without_index = edit(chat_scope());
    files_without_index.files = Some(RevisionFiles::HeadFileKeys(vec![FileRef {
        bucket: "chatfiles".into(),
        key: "a".into(),
    }]));
    assert_eq!(code(files_without_index), Some("media_index_required"));
    let mut enhance_without_files = edit(chat_scope());
    enhance_without_files.action = EmbedUpdateAction::Enhance;
    assert_eq!(code(enhance_without_files), Some("file_source_required"));
    let mut bad_operation = edit(chat_scope());
    bad_operation.operation_id = Some("has space".into());
    assert_eq!(code(bad_operation), Some("invalid_operation_id"));
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.edit.next-version
#[tokio::test]
async fn commits_then_updates_the_cache_from_the_receipt() {
    let prepared = prepare(&edit(chat_scope()));
    let mut fake = Fake::new(vec![Ok(committed_response(&prepared, false))]);
    let commit = commit_prepared(&mut fake, prepared).await.expect("commit");
    assert!(commit.cache_synchronized);
    assert_eq!(fake.stored.len(), 1);
    let stored = &fake.stored[0];
    assert_eq!(
        (
            stored.version,
            stored.base_version,
            stored.idempotent,
            stored.pending_notice
        ),
        (3, 2, false, true)
    );
    assert_eq!(stored.history_rows.len(), 1);
    assert_eq!(stored.history_rows[0].id, format!("{EMBED}_v3"));
    let mut row = json!({"embed_id": EMBED, "version_number": 2, "encrypted_content": "old", "encrypted_type": "kept"});
    stored.apply_to_cached_row(&mut row).expect("apply");
    assert_eq!(
        (
            row["version_number"].as_i64(),
            row["encrypted_type"].as_str()
        ),
        (Some(3), Some("kept"))
    );
    assert_eq!(
        row["encrypted_content"].as_str(),
        Some(stored.encrypted_content.as_str())
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.edit.next-version
#[tokio::test]
async fn a_stale_head_is_refused_and_the_cache_is_untouched() {
    let prepared = prepare(&edit(chat_scope()));
    let conflict = UserRevisionError::VersionConflict {
        current_revision: Some(4),
        current_content_hash: Some("a".repeat(64)),
    };
    let mut fake = Fake::new(vec![Err(conflict.clone())]);
    assert_eq!(commit_prepared(&mut fake, prepared).await, Err(conflict));
    assert!(fake.stored.is_empty());
    assert_eq!(fake.posted.len(), 1);
}

#[tokio::test]
async fn a_receipt_for_another_version_is_a_protocol_error() {
    let prepared = prepare(&edit(chat_scope()));
    let mut wrong = committed_response(&prepared, false);
    wrong["current_content_hash"] = json!("b".repeat(64));
    let mut fake = Fake::new(vec![Ok(wrong)]);
    assert_eq!(
        commit_prepared(&mut fake, prepared).await,
        Err(UserRevisionError::Transport(Error::Protocol))
    );
    assert!(fake.stored.is_empty());
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.history.one-per-embed
#[tokio::test]
async fn sends_the_base_snapshot_only_when_the_server_asks() {
    let request = edit(chat_scope());
    let prepared = prepare(&request);
    let response = committed_response(&prepared, false);
    let mut fake = Fake::new(vec![
        Err(UserRevisionError::BaseSnapshotRequired),
        Ok(response),
    ]);
    let commit = commit_prepared(&mut fake, prepared).await.expect("commit");
    assert_eq!(
        fake.posted[0]["history_rows"].as_array().map(Vec::len),
        Some(1)
    );
    let rows = fake.posted[1]["history_rows"].as_array().expect("rows");
    assert_eq!(rows.len(), 2);
    assert_eq!(
        rows[0],
        json!({"version_number": 2, "encrypted_snapshot": request.head.encrypted_content, "created_at": 1_700_000_000})
    );
    assert_eq!(rows[1]["version_number"], 3);
    assert_eq!(
        fake.posted[0]["operation_id"],
        fake.posted[1]["operation_id"]
    );
    assert_eq!(commit.committed.history_rows.len(), 2);
}

#[tokio::test]
async fn asks_for_the_base_snapshot_at_most_once() {
    let prepared = prepare(&edit(chat_scope()));
    let mut fake = Fake::new(vec![
        Err(UserRevisionError::BaseSnapshotRequired),
        Err(UserRevisionError::BaseSnapshotRequired),
    ]);
    assert_eq!(
        commit_prepared(&mut fake, prepared).await,
        Err(UserRevisionError::BaseSnapshotRequired)
    );
    assert_eq!(fake.posted.len(), 2);
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.edit.next-version
#[tokio::test]
async fn a_lost_answer_is_resent_byte_identical_and_accepted_idempotently() {
    let prepared = prepare(&edit(chat_scope()));
    let response = committed_response(&prepared, true);
    let mut fake = Fake::new(vec![
        Err(UserRevisionError::Transport(Error::Offline)),
        Ok(response),
    ]);
    let commit = commit_prepared(&mut fake, prepared).await.expect("commit");
    assert_eq!(fake.posted[0], fake.posted[1]);
    assert!(commit.committed.idempotent);
    assert_eq!(fake.stored.len(), 1);
}

#[tokio::test]
async fn gives_up_after_one_resend_without_touching_the_cache() {
    let prepared = prepare(&edit(chat_scope()));
    let offline = || Err(UserRevisionError::Transport(Error::Offline));
    let mut fake = Fake::new(vec![offline(), offline()]);
    assert_eq!(
        commit_prepared(&mut fake, prepared).await,
        Err(UserRevisionError::Transport(Error::Offline))
    );
    assert!(fake.stored.is_empty());
}

#[tokio::test]
async fn reports_a_durable_commit_whose_cache_write_failed() {
    let prepared = prepare(&edit(chat_scope()));
    let mut fake = Fake::new(vec![Ok(committed_response(&prepared, false))]);
    fake.fail_store = true;
    let commit = commit_prepared(&mut fake, prepared).await.expect("commit");
    assert!(!commit.cache_synchronized);
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.restore.creates-version
#[tokio::test]
async fn restore_commits_version_k_content_as_the_next_version() {
    let keys = vec![FileRef {
        bucket: "chatfiles".into(),
        key: "images/v1-full.webp".into(),
    }];
    let index = json!({"files": {"full": {"s3_key": "images/v1-full.webp"}}, "aes_nonce": "n", "vault_wrapped_aes_key": "vault:v1:x"});
    let request = UserRevisionRequest::restore(
        head(),
        chat_scope(),
        1,
        Zeroizing::new("title: Kitchen plan\nversion_number: 1".into()),
        None,
        Some((keys, index.clone())),
    );
    let prepared = prepare(&request);
    let body = prepared.body().clone();
    assert_eq!(
        (body["action"].as_str(), body["restored_from"].as_i64()),
        (Some("restore"), Some(1))
    );
    assert_eq!(
        body["files"],
        json!({"head_file_keys": [{"bucket": "chatfiles", "key": "images/v1-full.webp"}]})
    );
    assert_eq!(body["media_index"], index);
    let mut fake = Fake::new(vec![Ok(committed_response(&prepared, false))]);
    let commit = commit_prepared(&mut fake, prepared).await.expect("commit");
    // A new version 3 that equals version 1; version 2 stays in history.
    assert_eq!(
        (commit.committed.version, commit.committed.restored_from),
        (3, Some(1))
    );
    let event = commit.committed.event(&EmbedEventIdentity {
        embed_ref: "kitchen-plan-a1b".into(),
        embed_kind: EmbedKind::Image,
    });
    let content = build_embed_updated_event(&event).expect("valid restore event");
    let parsed = parse_embed_updated_event(&content).expect("parse");
    assert_eq!(
        (parsed.version, parsed.restored_from, parsed.action),
        (3, Some(1), EmbedUpdateAction::Restore)
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.assistant.knows-current-version
#[test]
fn the_event_of_a_commit_names_the_new_current_version() {
    let prepared = prepare(&edit(chat_scope()));
    let committed = receipt(&prepared, &committed_response(&prepared, false)).expect("receipt");
    let event = committed.event(&EmbedEventIdentity {
        embed_ref: "kitchen-plan-a1b".into(),
        embed_kind: EmbedKind::Document,
    });
    assert_eq!(
        (event.version, event.base_version, event.surface),
        (3, Some(2), EmbedUpdateSurface::Chat)
    );
    assert_eq!(event.message_id(), format!("embed-updated-{EMBED}-v3"));
    assert!(build_embed_updated_event(&event).is_ok());
}

#[test]
fn classifies_route_refusals_into_typed_errors() {
    let path = format!("/v1/embeds/{EMBED}/user-revisions");
    let conflict = json!({"detail": {"code": "embed_version_conflict", "current_revision": 4, "current_content_hash": "c".repeat(64)}});
    assert_eq!(
        classify(&path, 409, conflict.to_string().as_bytes()).map(|r| r.into_error()),
        Some(UserRevisionError::VersionConflict {
            current_revision: Some(4),
            current_content_hash: Some("c".repeat(64))
        })
    );
    let detail = |code: &str| json!({"detail": code}).to_string();
    let error = |status: u16, code: &str| {
        classify(&path, status, detail(code).as_bytes()).map(|r| r.into_error())
    };
    assert_eq!(
        error(409, "base_snapshot_required"),
        Some(UserRevisionError::BaseSnapshotRequired)
    );
    assert_eq!(
        error(403, "project_context_required"),
        Some(UserRevisionError::ProjectContextRequired)
    );
    assert_eq!(
        error(403, "project_access_denied"),
        Some(UserRevisionError::AccessDenied {
            code: "project_access_denied"
        })
    );
    assert_eq!(
        error(400, "media_index_required"),
        Some(UserRevisionError::Validation {
            code: "media_index_required"
        })
    );
    assert_eq!(
        error(409, "operation_payload_mismatch"),
        Some(UserRevisionError::Refused {
            code: "operation_payload_mismatch"
        })
    );
    assert_eq!(error(409, "some_future_code"), None);
    assert_eq!(
        classify(
            "/v1/projects/x/items",
            403,
            detail("project_context_required").as_bytes()
        ),
        None
    );
    assert_eq!(
        classify(&path, 200, detail("base_snapshot_required").as_bytes()),
        None
    );
}

#[test]
fn reads_the_head_from_a_cached_row() {
    let row = json!({"embed_id": EMBED, "encrypted_content": "ct", "updated_at": 1_700_000_000_000_i64, "hashed_chat_id": "h"});
    let head = EmbedHead::from_cached_row(EMBED, &row, 5).expect("head");
    assert_eq!(
        (
            head.version,
            head.created_at,
            head.hashed_chat_id.as_deref()
        ),
        (1, 1_700_000_000, Some("h"))
    );
    let other = json!({"embed_id": "another", "encrypted_content": "ct"});
    assert!(EmbedHead::from_cached_row(EMBED, &other, 5).is_err());
}

#[test]
fn scope_reads_the_wire_form_it_writes() {
    for scope in [
        chat_scope(),
        RevisionScope::Project {
            project_id: PROJECT.into(),
            team_id: Some("team-1".into()),
        },
    ] {
        let parsed: RevisionScope = serde_json::from_value(scope.wire()).expect("scope");
        assert_eq!(parsed, scope);
    }
    for bad in [
        json!({"kind": "team", "chat_id": CHAT}),
        json!({"chat_id": CHAT}),
        json!({"kind": "project", "chat_id": CHAT}),
    ] {
        assert!(
            serde_json::from_value::<RevisionScope>(bad.clone()).is_err(),
            "{bad}"
        );
    }
}

#[test]
fn content_edit_is_a_file_less_edit_of_the_head() {
    let request = UserRevisionRequest::content_edit(
        head(),
        chat_scope(),
        Zeroizing::new("title: Kitchen plan v3".into()),
        None,
        Some("op-7".into()),
    );
    assert_eq!(request.action, EmbedUpdateAction::Edit);
    assert!(request.files.is_none() && request.media_index.is_none());
    assert!(request.restored_from.is_none());
    let prepared = prepare(&request);
    assert_eq!(prepared.body()["operation_id"], "op-7");
    assert_eq!(prepared.body()["action"], "edit");
    assert_eq!(prepared.version(), 3);
    assert!(
        prepared.body()["head"]
            .get("encrypted_text_preview")
            .is_none()
    );
}

#[test]
fn a_content_edit_of_an_older_version_is_a_version_conflict() {
    let head = head();
    assert_eq!(head.require_version(2), Ok(()));
    let refused = head.require_version(1).expect_err("stale base");
    assert_eq!(refused.code(), "embed_version_conflict");
    assert_eq!(
        refused,
        UserRevisionError::VersionConflict {
            current_revision: Some(2),
            current_content_hash: None
        }
    );
}

#[test]
fn transport_failures_keep_a_specific_stable_code_without_detail() {
    let cases = [
        (Error::Offline, "offline"),
        (Error::Expired, "session_expired"),
        (Error::Cancelled, "cancelled"),
        (Error::Crypto, "encryption_failed"),
        (Error::Forbidden, "forbidden"),
        (Error::Protocol, "protocol"),
        (Error::Conflict, "conflict"),
        (Error::Io, "io_failed"),
        (Error::Authentication, "authentication_failed"),
        (Error::VerificationRequired, "verification_required"),
        (
            Error::Invalid("secret detail: embed 1234"),
            "invalid_request",
        ),
        (
            Error::Unavailable {
                code: "browser_offline_read_only",
                reason: "LOCAL_PROFILE_DOES_NOT_GRANT_SERVER_OR_STREAM_AUTHORITY",
            },
            "browser_offline_read_only",
        ),
        (
            Error::Unavailable {
                code: "Not A Code",
                reason: "X",
            },
            "transport_failed",
        ),
    ];
    for (error, code) in cases {
        assert_eq!(UserRevisionError::Transport(error).code(), code);
    }
}
