//! Web-mode privacy of file jobs: restore, redaction, sealed blob, fail-closed steps.
//! Web-mode privacy of Project file jobs: restore, redact, sealed persistence.
use super::approvals_tests::{interactive, request, run, Runner, CHAT, PROJECT};
use super::privacy::PrivacyLayer;
use super::steps::ProjectFileJobFrame;
use super::FileJobState;
use crate::crypto::Key;
use crate::privacy::file_privacy::{open_mappings, seal_mappings};
use crate::Error;
use serde_json::{json, Value};

const TOKEN: &str = "[OM_PII_0123456789ABCDEF0123456789ABCDEF]";
const EMAIL: &str = "jane.doe@example.org";

fn key() -> Key {
    Key::new([7; 32])
}

fn layer() -> PrivacyLayer {
    let mapping = json!({"placeholder": TOKEN, "original": "Jane Doe", "type": "NAME"});
    PrivacyLayer::open(CHAT, PROJECT, true, Vec::new(), None, &[mapping], key()).unwrap()
}

fn state() -> FileJobState {
    let mut state = interactive();
    state.privacy = Some(layer());
    state
}

fn to_frames(frames: Vec<(&'static str, Value)>) -> Vec<ProjectFileJobFrame> {
    frames
        .into_iter()
        .map(|(name, payload)| ProjectFileJobFrame {
            name: name.to_owned(),
            payload,
        })
        .collect()
}

fn write_request(content: &str) -> Value {
    let mut event = request("create_file");
    event["arguments"] = json!({"path": "notes.txt", "content": content});
    event
}

#[tokio::test]
async fn restored_arguments_reach_the_runner() {
    let (mut r, mut st) = (Runner::new(), state());
    r.digest = "a".repeat(64);
    let mut read = request("read_text");
    read["arguments"] = json!({"path": format!("{TOKEN}.txt")});
    run(&mut r, &read, &mut st).await;
    assert_eq!(r.seen[0]["path"], "Jane Doe.txt");
    let mut write = write_request(&format!("hello {TOKEN}"));
    write["operation_id"] = json!("op-2");
    run(&mut r, &write, &mut st).await;
    st.approvals.decide("op-2", true);
    run(&mut r, &write, &mut st).await;
    assert!(r.seen.iter().any(|a| a["content"] == "hello Jane Doe"));
}

#[tokio::test]
async fn completed_read_is_redacted_and_the_step_carries_a_sealed_blob() {
    let (mut r, mut st) = (Runner::new(), state());
    r.output = json!({"path": "a.txt", "content": format!("mail {EMAIL}"),
        "content_hash": "h", "source_id": null});
    let frames = run(&mut r, &request("read_text"), &mut st).await;
    let mut frames = to_frames(frames);
    let blob = st
        .privacy
        .as_mut()
        .unwrap()
        .redact_frames(&mut frames)
        .unwrap();
    let body = frames[0].payload["result"].to_string();
    assert!(!body.contains(EMAIL) && body.contains("[OM_PII_"));
    assert_eq!(frames[0].payload["result"]["content_hash"], "h");
    let saved = open_mappings(CHAT, PROJECT, &blob.ciphertext, &key()).unwrap();
    assert!(saved.iter().any(|m| m["original"] == EMAIL));
    assert_eq!(
        (blob.chat_id.as_str(), blob.project_id.as_str()),
        (CHAT, PROJECT)
    );
}

#[tokio::test]
async fn proposal_is_redacted_while_the_prompt_keeps_the_real_value() {
    let (mut r, mut st) = (Runner::new(), state());
    let frames = run(&mut r, &write_request(&format!("write {EMAIL}")), &mut st).await;
    let mut frames = to_frames(frames);
    // The test runner proposes fixed content; inject a real value into it.
    frames[0].payload["result"]["proposal"]["content"] = json!(format!("keep {EMAIL}"));
    st.approvals.take_prompts();
    st.privacy.as_mut().unwrap().redact_frames(&mut frames);
    let shown = frames[0].payload["result"].to_string();
    assert!(!shown.contains(EMAIL));
    assert_eq!(
        frames[0].payload["result"]["proposal_commitment"],
        "a".repeat(64)
    );
}

#[tokio::test]
async fn prompts_keep_real_values() {
    let (mut r, mut st) = (Runner::new(), state());
    let mut event = write_request("x");
    event["arguments"]["path"] = json!(format!("{TOKEN}.txt"));
    run(&mut r, &event, &mut st).await;
    let prompts = st.approvals.take_prompts();
    assert_eq!(prompts[0]["kind"], "write");
}

#[tokio::test]
async fn cli_path_without_a_layer_is_unredacted() {
    let (mut r, mut st) = (Runner::new(), interactive());
    r.output = json!({"content": EMAIL});
    let frames = run(&mut r, &request("read_text"), &mut st).await;
    assert_eq!(frames[0].1["result"]["content"], EMAIL);
}

#[test]
fn wrong_chat_or_project_blob_is_refused_as_unavailable() {
    let blob = seal_mappings("other-chat", PROJECT, &[], &key()).unwrap();
    let opened = PrivacyLayer::open(CHAT, PROJECT, true, Vec::new(), Some(&blob), &[], key());
    assert!(matches!(
        opened,
        Err(Error::Unavailable {
            code: "pii_mapping_unavailable",
            ..
        })
    ));
    let junk = PrivacyLayer::open(CHAT, PROJECT, true, Vec::new(), Some("junk"), &[], key());
    assert!(matches!(
        junk,
        Err(Error::Unavailable {
            code: "pii_mapping_unavailable",
            ..
        })
    ));
}

/// An offline Client: no request ever reaches a server in these tests.
fn offline_client() -> crate::Client {
    let endpoint = "http://127.0.0.1:9";
    let session = serde_json::from_value(json!({"api_url": endpoint, "session_id": "synthetic",
        "cookies": {}, "ws_token": null,
        "master_key": "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
        "hashed_email": "synthetic", "user_email_salt": "synthetic",
        "email_encryption_key": null, "created_at": 1,
        "paired_session_expires_at": null, "active_team_id": null}))
    .expect("synthetic session fixture is valid");
    crate::Client::new(endpoint, Some(session)).expect("offline client builds")
}

#[tokio::test]
async fn an_interactive_step_without_a_privacy_layer_runs_nothing() {
    let mut client = offline_client();
    let outcome = client
        .project_file_job_step(
            "project_file_operation_request",
            &request("read_text"),
            true,
        )
        .await;
    assert!(matches!(
        outcome,
        Err(Error::Unavailable {
            code: "pii_mapping_unavailable",
            ..
        })
    ));
}
