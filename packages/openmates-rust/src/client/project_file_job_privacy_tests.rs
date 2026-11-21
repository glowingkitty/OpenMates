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
async fn an_interactive_step_without_a_privacy_layer_fails_closed_with_an_immediate_answer() {
    // The offline client proves nothing is read: any file access would need
    // the unreachable server. The job is still answered at once, so the
    // assistant gets a clear error instead of minutes of silence.
    let mut client = offline_client();
    let offered = client
        .project_file_job_step(
            "project_file_operation_available",
            &request("read_text"),
            true,
        )
        .await
        .expect("an offered job is claimed");
    assert_eq!(offered.frames.len(), 1);
    assert_eq!(offered.frames[0].name, "project_file_operation_claim");
    assert!(offered.frames[0].payload.get("result").is_none());
    let started = std::time::Instant::now();
    let answered = client
        .project_file_job_step(
            "project_file_operation_request",
            &request("read_text"),
            true,
        )
        .await
        .expect("a leased request is answered");
    assert!(started.elapsed() < std::time::Duration::from_secs(3));
    assert_eq!(answered.frames.len(), 1);
    let result = &answered.frames[0];
    assert_eq!(result.name, "project_file_operation_result");
    assert_eq!(result.payload["status"], "failed");
    assert_eq!(
        result.payload["result"],
        json!({"code": "pii_mapping_unavailable"})
    );
    assert!(answered.privacy.is_none() && answered.applied.is_empty());
    // One answer per operation: a replayed request stays silent.
    let replay = client
        .project_file_job_step(
            "project_file_operation_request",
            &request("read_text"),
            true,
        )
        .await
        .unwrap();
    assert!(replay.frames.is_empty());
}

const RECIPE_APP: &str = r#"<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Recipe Box</title>
<style>
body { font-family: sans-serif; background: #fafafa; margin: 0 auto; max-width: 640px; }
input[type="text"], [data-role="recipe"] { padding: 4px 8px; }
li[data-done="true"] { text-decoration: line-through; }
</style></head><body>
<h1>Recipe Box</h1>
<input type="text" id="title" placeholder="Recipe name"><button id="add">Add</button>
<ul id="list"></ul>
<script>
const recipes = [{ name: "Pancakes", ingredients: ["2 cups flour", "1 egg", "350 ml milk"], minutes: 20 }];
const ID_1 = 0;
function render() {
  const list = document.querySelector('[data-x], #list');
  list.innerHTML = "";
  for (let i = 0; i < recipes.length; i++) {
    const li = document.createElement("li");
    li.textContent = recipes[i].name + " (" + recipes[i].ingredients[ID_1] + ")";
    li.dataset.role = "recipe";
    list.appendChild(li);
  }
  const arr = [A, B]; const items = []; const index = 0; items[index] = arr[ID_1];
}
document.getElementById("add").addEventListener("click", () => {
  recipes.push({ name: document.getElementById("title").value, ingredients: [], minutes: 10 });
  localStorage.setItem("recipes", JSON.stringify(recipes)); render();
});
render();
</script></body></html>
"#;

fn web_memories() -> Vec<Value> {
    vec![json!({"app_id": "privacy", "item_type": "personal_data_entry",
        "data": {"enabled": true, "textToHide": "Jane Doe", "replaceWith": "NAME_1"}})]
}

#[tokio::test]
async fn recipe_app_create_file_is_proposed_and_completed_without_refusal() {
    let mapping = json!({"placeholder": TOKEN, "original": "Jane Doe", "type": "NAME"});
    let layer =
        PrivacyLayer::open(CHAT, PROJECT, true, web_memories(), None, &[mapping], key()).unwrap();
    let mut st = interactive();
    st.privacy = Some(layer);
    let mut r = Runner::new();
    let event = write_request(RECIPE_APP);
    let restored = st
        .privacy
        .as_ref()
        .unwrap()
        .restore(crate::work::HostedFileJob {
            operation_id: "op-1".into(),
            chat_id: CHAT.into(),
            operation: serde_json::from_value(json!("create_file")).unwrap(),
            arguments: event["arguments"].clone(),
        })
        .expect("ordinary JS and CSS brackets are not placeholders");
    assert_eq!(restored.arguments["content"], RECIPE_APP);
    let frames = run(&mut r, &event, &mut st).await;
    let mut frames = to_frames(frames);
    frames[0].payload["result"]["proposal"]["content"] = json!(RECIPE_APP);
    let blob = st.privacy.as_mut().unwrap().redact_frames(&mut frames);
    assert_eq!(frames[0].payload["status"], "awaiting_approval");
    assert_eq!(frames[0].payload["result"]["proposal"]["content"], RECIPE_APP);
    assert!(blob.is_none());
    // The completed result of the approved write.
    r.output = json!({"path": "index.html", "created": true, "content_hash": "h",
        "content": RECIPE_APP});
    st.approvals.decide("op-1", true);
    let frames = run(&mut r, &event, &mut st).await;
    let mut frames = to_frames(frames);
    st.privacy.as_mut().unwrap().redact_frames(&mut frames);
    let result = frames.iter().find(|f| f.name == "project_file_operation_result").unwrap();
    assert_eq!(result.payload["status"], "completed", "{}", result.payload["result"]);
}

#[tokio::test]
async fn recipe_app_with_detected_values_seals_and_reopens_the_layer() {
    let content = format!(
        "{RECIPE_APP}<footer>Contact chef@example.org or +49 170 1234567, key sk-abcdefghijklmnopqrstuv0123456789, ip 192.168.0.12, id 123e4567-e89b-12d3-a456-426614174000</footer>"
    );
    let mut st = interactive();
    st.privacy = Some(layer());
    let mut r = Runner::new();
    let event = write_request(&content);
    let frames = run(&mut r, &event, &mut st).await;
    let mut frames = to_frames(frames);
    frames[0].payload["result"]["proposal"]["content"] = json!(content);
    let blob = st.privacy.as_mut().unwrap().redact_frames(&mut frames);
    assert_eq!(frames[0].payload["status"], "awaiting_approval", "{}", frames[0].payload);
    let blob = blob.expect("detected values mint sealed mappings");
    let reopened = PrivacyLayer::open(
        CHAT, PROJECT, true, web_memories(), Some(&blob.ciphertext), &[], key(),
    )
    .expect("the sealed blob reopens on the next step");
    st.privacy = Some(reopened);
    r.output = json!({"path": "index.html", "created": true, "content_hash": "h"});
    st.approvals.decide("op-1", true);
    let frames = run(&mut r, &event, &mut st).await;
    let mut frames = to_frames(frames);
    st.privacy.as_mut().unwrap().redact_frames(&mut frames);
    let result = frames.iter().find(|f| f.name == "project_file_operation_result").unwrap();
    assert_eq!(result.payload["status"], "completed", "{}", result.payload["result"]);
}

#[test]
fn redaction_failures_name_their_stage_instead_of_pii_mapping_unavailable() {
    use super::privacy::{refusal_code, stage};
    let seal = stage(Error::Crypto, "pii_seal_failed");
    assert_eq!(refusal_code(&seal), "pii_seal_failed");
    let detect = stage(Error::Invalid("regex"), "pii_detection_failed");
    assert_eq!(refusal_code(&detect), "pii_detection_failed");
    let limit = Error::Unavailable { code: "pii_mapping_limit", reason: "x" };
    assert_eq!(refusal_code(&stage(limit, "pii_seal_failed")), "pii_mapping_limit");
    assert_eq!(refusal_code(&Error::Crypto), "pii_redaction_failed");
}

#[tokio::test]
async fn unknown_generated_token_in_a_write_is_refused_with_its_own_code() {
    let (mut r, mut st) = (Runner::new(), state());
    let unknown = "[OM_PII_FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF]";
    let frames = run(&mut r, &write_request(&format!("hi {unknown}")), &mut st).await;
    assert_eq!(frames[0].1["status"], "failed");
    assert_eq!(frames[0].1["result"]["code"], "pii_mapping_unavailable");
    assert!(r.executed.is_empty());
}
