//! Memory write job state machine (claim, grant, write failure, notice, ack) and Undo decisions.
use super::*;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const NOW: u64 = 1_800_000_000;
const DOC: &str = "---\ntitle: Career profile\nwhen_to_use: When writing applications.\nload_mode: ask_first\n---\n\nSenior Rust engineer.\n";
const OLD: &str = "---\ntitle: Career profile\nwhen_to_use: When writing applications.\n---\n\nJunior Rust engineer.\n";

/// In-memory runner over one stored Memory list.
#[derive(Default)]
struct Fake {
    stored: BTreeMap<String, String>,
    fail_write: Option<MemoryDocumentError>,
    fail_notice: bool,
    notices: Vec<(String, String, String)>,
}

impl MemoryJobRunner for Fake {
    async fn write(
        &mut self,
        entry_id: &str,
        document: &str,
        mode: MemoryWriteMode,
    ) -> MemoryResult<Option<Zeroizing<String>>> {
        if let Some(error) = self.fail_write.take() {
            return Err(error);
        }
        let previous = self.stored.get(entry_id).cloned();
        match (mode, &previous) {
            (MemoryWriteMode::Create, Some(_)) => return Err(MemoryDocumentError::AlreadyExists),
            (MemoryWriteMode::Update, None) => return Err(MemoryDocumentError::NotFound),
            _ => {}
        }
        self.stored.insert(entry_id.into(), document.into());
        Ok(previous.map(Zeroizing::new))
    }
    async fn delete(&mut self, entry_id: &str) -> MemoryResult<()> {
        self.stored
            .remove(entry_id)
            .map(drop)
            .ok_or(MemoryDocumentError::NotFound)
    }
    async fn seal(&mut self, previous: &str) -> Result<String> {
        Ok(format!("sealed:{}", previous.len()))
    }
    async fn notice(
        &mut self,
        chat: &str,
        user_message: &str,
        message_id: &str,
        content: &str,
        _: Option<&[u8; 32]>,
    ) -> Result<()> {
        if self.fail_notice {
            return Err(Error::Offline);
        }
        assert_eq!((chat, user_message), (CHAT, "user-message"));
        self.notices
            .push((message_id.into(), content.into(), chat.into()));
        Ok(())
    }
}

fn job(action: &str, memory_id: &str) -> Value {
    json!({"protocol":1,"job_id":"memory-write-job-1","chat_id":CHAT,"message_id":"user-message",
        "action":action,"memory_id":memory_id,"title":"Career profile","document":DOC,"expires_at":NOW + 120})
}

fn grant(granted: bool) -> Value {
    json!({"job_id":"memory-write-job-1","chat_id":CHAT,"granted":granted,"reason":if granted {"granted"} else {"already_claimed"}})
}

async fn run(
    fake: &mut Fake,
    kind: &str,
    event: &Value,
    state: &mut MemoryJobState,
) -> Vec<(&'static str, Value)> {
    job_frames(fake, kind, event, CHAT, NOW, state)
        .await
        .unwrap()
}

async fn claimed(fake: &mut Fake, event: &Value, state: &mut MemoryJobState) {
    let claim = run(fake, AVAILABLE, event, state).await;
    assert_eq!(
        claim,
        vec![(
            CLAIM,
            json!({"protocol":1,"job_id":"memory-write-job-1","chat_id":CHAT})
        )]
    );
    // A repeated offer is not claimed twice.
    assert!(run(fake, AVAILABLE, event, state).await.is_empty());
}

#[tokio::test]
async fn granted_create_stores_the_memory_writes_the_assistant_notice_and_reports_applied() {
    let (mut fake, mut state) = (Fake::default(), MemoryJobState::default());
    claimed(&mut fake, &job("create", "abc"), &mut state).await;
    let sent = run(&mut fake, CLAIM_RESULT, &grant(true), &mut state).await;
    assert_eq!(
        sent,
        vec![(
            RESULT,
            json!({"protocol":1,"job_id":"memory-write-job-1","chat_id":CHAT,"status":"applied","memory_id":"abc"})
        )]
    );
    assert_eq!(
        fake.stored.get("personal:abc").map(String::as_str),
        Some(DOC)
    );
    let (message_id, content, _) = &fake.notices[0];
    assert_eq!(message_id, "context-entry-memory-write-job-1");
    let event = parse_context_entry_event(content).unwrap();
    assert_eq!(event.entry_id, "personal:abc");
    assert_eq!(event.action, ContextEntryAction::Created);
    assert_eq!(event.source, Some(ContextEntrySource::Assistant));
    let undo = event.undo.as_ref().unwrap();
    assert_eq!(undo.action, RecommendationAction::Create);
    assert_eq!(undo.written_document_sha256, document_sha256(DOC));
    assert!(undo.encrypted_previous_document.is_none());
    assert_eq!(
        state.take_notices(),
        ["Memory created by the assistant: Career profile"]
    );
    // The ack is recorded on the job record.
    run(
        &mut fake,
        RESULT_ACK,
        &json!({"job_id":"memory-write-job-1","chat_id":CHAT,"accepted":true,"reason":"accepted"}),
        &mut state,
    )
    .await;
    let record = &state.records()[0];
    assert_eq!(record["status"], "applied");
    assert_eq!(record["accepted"], true);
    assert_eq!(record["undoAvailable"], true);
    assert_eq!(record["entryId"], "personal:abc");
}

#[tokio::test]
async fn granted_update_seals_the_previous_document_for_undo() {
    let (mut fake, mut state) = (Fake::default(), MemoryJobState::default());
    fake.stored.insert("personal:abc".into(), OLD.into());
    claimed(&mut fake, &job("update", "personal:abc"), &mut state).await;
    let sent = run(&mut fake, CLAIM_RESULT, &grant(true), &mut state).await;
    assert_eq!(sent[0].1["status"], "applied");
    assert_eq!(sent[0].1["memory_id"], "personal:abc");
    let event = parse_context_entry_event(&fake.notices[0].1).unwrap();
    assert_eq!(event.action, ContextEntryAction::Updated);
    let previous = event.undo.unwrap().encrypted_previous_document;
    assert_eq!(previous, Some(format!("sealed:{}", OLD.len())));
}

#[tokio::test]
async fn a_claim_that_is_not_granted_applies_nothing() {
    let (mut fake, mut state) = (Fake::default(), MemoryJobState::default());
    claimed(&mut fake, &job("create", "abc"), &mut state).await;
    assert!(
        run(&mut fake, CLAIM_RESULT, &grant(false), &mut state)
            .await
            .is_empty()
    );
    assert!(fake.stored.is_empty() && fake.notices.is_empty());
    let record = &state.records()[0];
    assert_eq!(record["status"], "not_granted");
    assert_eq!(record["reason"], "already_claimed");
    // A late grant for a finished job is ignored.
    assert!(
        run(&mut fake, CLAIM_RESULT, &grant(true), &mut state)
            .await
            .is_empty()
    );
}

#[tokio::test]
async fn a_write_failure_reports_failed_with_the_web_error_code() {
    let (mut fake, mut state) = (Fake::default(), MemoryJobState::default());
    fake.fail_write = Some(MemoryDocumentError::CatalogLimit);
    claimed(&mut fake, &job("create", "abc"), &mut state).await;
    let sent = run(&mut fake, CLAIM_RESULT, &grant(true), &mut state).await;
    assert_eq!(sent[0].1["status"], "failed");
    assert_eq!(sent[0].1["error_code"], "rule_catalog_limit");
    assert!(fake.notices.is_empty());
    assert_eq!(
        state.take_notices(),
        ["Memory not saved (rule_catalog_limit): Career profile"]
    );
}

#[tokio::test]
async fn an_update_of_a_missing_memory_fails_without_writing() {
    let (mut fake, mut state) = (Fake::default(), MemoryJobState::default());
    claimed(&mut fake, &job("update", "personal:gone"), &mut state).await;
    let sent = run(&mut fake, CLAIM_RESULT, &grant(true), &mut state).await;
    assert_eq!(sent[0].1["error_code"], "rule_not_found");
    assert!(fake.stored.is_empty());
}

#[tokio::test]
async fn a_failed_notice_rolls_the_write_back_and_reports_failed() {
    let (mut fake, mut state) = (Fake::default(), MemoryJobState::default());
    fake.fail_notice = true;
    fake.stored.insert("personal:abc".into(), OLD.into());
    claimed(&mut fake, &job("update", "personal:abc"), &mut state).await;
    let sent = run(&mut fake, CLAIM_RESULT, &grant(true), &mut state).await;
    assert_eq!(sent[0].1["error_code"], "history_notice_failed");
    assert_eq!(
        fake.stored.get("personal:abc").map(String::as_str),
        Some(OLD)
    );
}

#[tokio::test]
async fn invalid_or_expired_jobs_are_claimed_then_failed_and_foreign_ones_ignored() {
    let (mut fake, mut state) = (Fake::default(), MemoryJobState::default());
    let mut bad = job("create", "abc");
    bad["document"] = json!("not a memory");
    claimed(&mut fake, &bad, &mut state).await;
    let sent = run(&mut fake, CLAIM_RESULT, &grant(true), &mut state).await;
    assert_eq!(sent[0].1["error_code"], "invalid_rule_document");
    let mut other_chat = job("create", "abc");
    other_chat["chat_id"] = json!("other");
    other_chat["job_id"] = json!("memory-write-job-2");
    assert!(
        run(&mut fake, AVAILABLE, &other_chat, &mut state)
            .await
            .is_empty()
    );
    let mut expired = job("create", "abc");
    expired["job_id"] = json!("memory-write-job-3");
    expired["expires_at"] = json!(NOW);
    assert!(
        run(&mut fake, AVAILABLE, &expired, &mut state)
            .await
            .is_empty()
    );
    let mut wrong_protocol = job("create", "abc");
    wrong_protocol["protocol"] = json!(2);
    wrong_protocol["job_id"] = json!("memory-write-job-4");
    assert!(
        run(&mut fake, AVAILABLE, &wrong_protocol, &mut state)
            .await
            .is_empty()
    );
}

fn assistant_event(action: RecommendationAction, written: &str) -> ContextEntryHistoryEvent {
    let update = action == RecommendationAction::Update;
    ContextEntryHistoryEvent {
        schema_version: 1,
        event_type: CONTEXT_ENTRY_TYPE.into(),
        kind: RecommendationKind::Memory,
        action: if update {
            ContextEntryAction::Updated
        } else {
            ContextEntryAction::Created
        },
        entry_id: "personal:abc".into(),
        title: "Career profile".into(),
        created_at: NOW as i64,
        source: Some(ContextEntrySource::Assistant),
        undo: Some(ContextEntryUndo {
            job_id: "memory-write-job-1".into(),
            action,
            written_document_sha256: document_sha256(written),
            encrypted_previous_document: update.then(|| "sealed".into()),
        }),
    }
}

fn current(document: &str) -> PersonalMemoryDocument {
    PersonalMemoryDocument {
        id: "personal:abc".into(),
        document: Zeroizing::new(document.into()),
    }
}

#[test]
fn undo_deletes_a_created_memory_and_restores_an_updated_one() {
    let created = assistant_event(RecommendationAction::Create, DOC);
    assert_eq!(
        undo_decision(&created, Some(&current(DOC))),
        Ok(MemoryUndoOutcome::Deleted)
    );
    let updated = assistant_event(RecommendationAction::Update, DOC);
    assert_eq!(
        undo_decision(&updated, Some(&current(DOC))),
        Ok(MemoryUndoOutcome::Restored)
    );
    // The event survives the system-message codec unchanged.
    let text = build_context_entry_event(&updated).unwrap();
    assert_eq!(parse_context_entry_event(&text), Some(updated));
}

#[test]
fn undo_refuses_edited_missing_and_user_saved_memories() {
    let created = assistant_event(RecommendationAction::Create, DOC);
    assert_eq!(
        undo_decision(&created, Some(&current(OLD))),
        Err(MemoryDocumentError::Changed)
    );
    assert_eq!(
        undo_decision(&created, None),
        Err(MemoryDocumentError::NotFound)
    );
    let mut user_saved = created.clone();
    user_saved.source = None;
    assert_eq!(
        undo_decision(&user_saved, Some(&current(DOC))),
        Err(MemoryDocumentError::NotUndoable)
    );
    // An update without the sealed previous document is not a valid event.
    let mut broken = assistant_event(RecommendationAction::Update, DOC);
    broken.undo.as_mut().unwrap().encrypted_previous_document = None;
    assert!(parse_context_entry_event(&serde_json::to_string(&broken).unwrap()).is_none());
    assert_eq!(
        undo_decision(&broken, Some(&current(DOC))),
        Err(MemoryDocumentError::NotUndoable)
    );
}
