//! Sans-IO memory write job driver (effects, rollback through effects), the
//! web undo step and the persisted undone marker.
use super::*;
use crate::client::memory_documents::read_memory_documents;
use crate::client::memory_write_jobs::{
    MemoryUndoOutcome, build_memory_write_undone_event, memory_write_undone_message_id,
    parse_memory_write_undone_event, prepare_memory_undo,
};
use crate::client::recommendations::{ContextEntryHistoryEvent, parse_context_entry_event};
use serde_json::json;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const NOW: u64 = 1_800_000_000;
const DOC: &str = "---\ntitle: Favourite colour\nwhen_to_use: When colours matter.\n---\n\nTeal.\n";

fn master() -> MasterCapability {
    MasterCapability::from_native(Zeroizing::new([7u8; 32]))
}

fn available() -> Value {
    json!({"protocol":1,"job_id":"memory-write-job-1","chat_id":CHAT,"message_id":"user-message",
        "action":"create","memory_id":"abc","title":"Favourite colour","document":DOC,"expires_at":NOW + 120})
}

fn granted() -> Value {
    json!({"job_id":"memory-write-job-1","chat_id":CHAT,"granted":true,"reason":"granted"})
}

/// Runs one frame, answering effects with `answer`; returns the effects seen.
async fn drive(
    desk: &mut MemoryJobDesk,
    ciphertext: Option<String>,
    kind: &str,
    event: Value,
    mut answer: impl FnMut(&MemoryJobEffect) -> MemoryEffectOutcome,
) -> Vec<MemoryJobEffect> {
    let (run, mut driver) = desk.start(master(), ciphertext, kind, event, NOW, Vec::new());
    let local = tokio::task::LocalSet::new();
    local
        .run_until(async move {
            tokio::task::spawn_local(run);
            let mut seen = Vec::new();
            loop {
                let effect = driver.next().await.unwrap();
                let done = matches!(effect, MemoryJobEffect::Done { .. });
                if !done {
                    driver.resume(answer(&effect)).unwrap();
                }
                seen.push(effect);
                if done {
                    return seen;
                }
            }
        })
        .await
}

fn frames(effect: &MemoryJobEffect) -> Vec<String> {
    match effect {
        MemoryJobEffect::Done { frames } => frames.iter().map(|(name, _)| name.clone()).collect(),
        other => panic!("not done: {other:?}"),
    }
}

#[tokio::test]
async fn a_granted_create_posts_settings_then_the_notice_then_reports_applied() {
    let mut desk = MemoryJobDesk::default();
    let claim = drive(
        &mut desk,
        None,
        "memory_write_job_available",
        available(),
        |_| None,
    )
    .await;
    assert_eq!(frames(&claim[0]), ["memory_write_job_claim"]);
    // A repeated offer of the same job is not claimed again.
    let again = drive(
        &mut desk,
        None,
        "memory_write_job_available",
        available(),
        |_| None,
    )
    .await;
    assert!(frames(&again[0]).is_empty());

    let steps = drive(
        &mut desk,
        None,
        "memory_write_job_claim_result",
        granted(),
        |_| None,
    )
    .await;
    let MemoryJobEffect::PostSettings { encrypted_settings } = &steps[0] else {
        panic!("first effect must post the settings");
    };
    let stored = read_memory_documents(&master(), Some(encrypted_settings))
        .await
        .unwrap();
    assert_eq!(stored[0].id, "personal:abc");
    let MemoryJobEffect::Notice {
        message_id,
        content,
        user_message_id,
        ..
    } = &steps[1]
    else {
        panic!("second effect must store the notice");
    };
    assert_eq!(message_id, "context-entry-memory-write-job-1");
    assert_eq!(user_message_id, "user-message");
    let notice = parse_context_entry_event(content).unwrap();
    assert!(notice.undo.is_some());
    assert_eq!(frames(&steps[2]), ["memory_write_job_result"]);
    let MemoryJobEffect::Done { frames } = &steps[2] else {
        unreachable!()
    };
    assert_eq!(frames[0].1["status"], "applied");
}

#[tokio::test]
async fn a_failed_notice_rolls_the_create_back_through_a_second_post() {
    let mut desk = MemoryJobDesk::default();
    drive(
        &mut desk,
        None,
        "memory_write_job_available",
        available(),
        |_| None,
    )
    .await;
    let steps = drive(
        &mut desk,
        None,
        "memory_write_job_claim_result",
        granted(),
        |effect| matches!(effect, MemoryJobEffect::Notice { .. }).then(|| "offline".to_owned()),
    )
    .await;
    let MemoryJobEffect::PostSettings { encrypted_settings } = &steps[2] else {
        panic!("rollback must post the settings again");
    };
    assert!(
        read_memory_documents(&master(), Some(encrypted_settings))
            .await
            .unwrap()
            .is_empty()
    );
    let MemoryJobEffect::Done { frames } = &steps[3] else {
        panic!("done expected")
    };
    assert_eq!(frames[0].1["error_code"], "history_notice_failed");
}

#[tokio::test]
async fn a_refused_settings_post_reports_failed_without_a_notice() {
    let mut desk = MemoryJobDesk::default();
    drive(
        &mut desk,
        None,
        "memory_write_job_available",
        available(),
        |_| None,
    )
    .await;
    let steps = drive(
        &mut desk,
        None,
        "memory_write_job_claim_result",
        granted(),
        |_| Some("rule_save_failed".into()),
    )
    .await;
    assert_eq!(steps.len(), 2);
    let MemoryJobEffect::Done { frames } = &steps[1] else {
        panic!("done expected")
    };
    assert_eq!(frames[0].1["error_code"], "rule_save_failed");
}

#[tokio::test]
async fn frames_of_other_protocols_finish_with_nothing_to_send() {
    let mut desk = MemoryJobDesk::default();
    let steps = drive(
        &mut desk,
        None,
        "chat_message_added",
        json!({"chat_id": CHAT}),
        |_| None,
    )
    .await;
    assert!(frames(&steps[0]).is_empty());
}

/// The notice of an applied create, and the settings holding its Memory.
async fn applied_create() -> (ContextEntryHistoryEvent, String) {
    let mut desk = MemoryJobDesk::default();
    drive(
        &mut desk,
        None,
        "memory_write_job_available",
        available(),
        |_| None,
    )
    .await;
    let steps = drive(
        &mut desk,
        None,
        "memory_write_job_claim_result",
        granted(),
        |_| None,
    )
    .await;
    let (
        MemoryJobEffect::PostSettings { encrypted_settings },
        MemoryJobEffect::Notice { content, .. },
    ) = (&steps[0], &steps[1])
    else {
        panic!("post then notice expected");
    };
    (
        parse_context_entry_event(content).unwrap(),
        encrypted_settings.clone(),
    )
}

#[tokio::test]
async fn web_undo_deletes_the_created_memory_and_refuses_after_an_edit() {
    let (notice, settings) = applied_create().await;
    let (outcome, prepared) = prepare_memory_undo(&master(), Some(&settings), &notice)
        .await
        .unwrap();
    assert_eq!(outcome, MemoryUndoOutcome::Deleted);
    assert!(
        read_memory_documents(&master(), Some(&prepared.encrypted_settings))
            .await
            .unwrap()
            .is_empty()
    );

    let edited = crate::client::memory_documents::prepare_memory_write(
        &master(),
        Some(&settings),
        "personal:abc",
        &DOC.replace("Teal", "Orange"),
        MemoryWriteMode::Update,
    )
    .await
    .unwrap();
    assert!(matches!(
        prepare_memory_undo(&master(), Some(&edited.encrypted_settings), &notice).await,
        Err(MemoryDocumentError::Changed)
    ));
}

#[tokio::test]
async fn the_undone_marker_round_trips_and_is_not_a_context_entry() {
    let (notice, _) = applied_create().await;
    let content = build_memory_write_undone_event(&notice, 1_800_000_100).unwrap();
    let marker = parse_memory_write_undone_event(&content).unwrap();
    assert_eq!(marker.job_id, "memory-write-job-1");
    assert_eq!(marker.entry_id, "personal:abc");
    assert_eq!(
        memory_write_undone_message_id(&marker.job_id),
        "context-entry-undone-memory-write-job-1"
    );
    assert!(parse_context_entry_event(&content).is_none());
    assert!(parse_memory_write_undone_event(r#"{"schema_version":1,"type":"memory_write_undone","job_id":"x y","entry_id":"a","undone_at":1}"#).is_none());
    let mut user_saved = notice.clone();
    user_saved.undo = None;
    user_saved.source = None;
    assert!(build_memory_write_undone_event(&user_saved, 1).is_err());
}

#[tokio::test]
async fn a_start_with_mappings_restores_the_placeholder_in_the_stored_document() {
    let mut desk = MemoryJobDesk::default();
    let mut event = available();
    event["document"] = json!(event["document"]
        .as_str()
        .unwrap()
        .replace("Teal.", "Mail [EMAIL_1]."));
    let mappings = vec![json!({"placeholder":"[EMAIL_1]","original":"ada@example.org"})];
    let start = |desk: &mut MemoryJobDesk, kind: &str, event: Value| {
        desk.start(master(), None, kind, event, NOW, mappings.clone())
    };
    let local = tokio::task::LocalSet::new();
    local
        .run_until(async {
            let (run, mut driver) = start(&mut desk, "memory_write_job_available", event);
            tokio::task::spawn_local(run);
            while !matches!(driver.next().await.unwrap(), MemoryJobEffect::Done { .. }) {}
            let (run, mut driver) = start(&mut desk, "memory_write_job_claim_result", granted());
            tokio::task::spawn_local(run);
            let MemoryJobEffect::PostSettings { encrypted_settings } = driver.next().await.unwrap()
            else {
                panic!("first effect must post the settings");
            };
            let stored = read_memory_documents(&master(), Some(&encrypted_settings))
                .await
                .unwrap();
            assert!(stored[0].document.contains("Mail ada@example.org."));
        })
        .await;
}
