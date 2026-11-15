//! Turn-time remote command executor: approval gate, sealed prepare request,
//! event opening and the single origin completion.
// contract-test: supporting surface=sdks.rust assertions=projects.creation.machine-folder
use super::*;
use crate::remote_command_review::request_digest;

const KEY: [u8; 32] = [9; 32];

struct Keys {
    asked: usize,
}

impl CommandKeys for Keys {
    async fn command_project_key(&mut self, chat: &str, project_id: &str) -> Result<Key> {
        assert_eq!((chat, project_id), ("chat-1", "proj-1"));
        self.asked += 1;
        Ok(Key::new(KEY))
    }
}

fn review(mutate: impl FnOnce(&mut Value)) -> Value {
    let mut v = json!({"protocol_version": 1, "execution_id": "exec-1", "chat_id": "chat-1",
        "message_id": "m-1", "project_id": "proj-1", "source_id": "src-1",
        "state": "REVIEW_REQUIRED", "created_at": 100, "review_expires_at": 200,
        "review_token": "t".repeat(32), "approval_requirement": "one_run",
        "wait_for_completion": true,
        "command": {"argv": ["node", "--check", "web-app/src/services/storage.js"], "cwd": ".",
            "mode": "foreground", "source_access": "read_only", "deadline_ms": 30000,
            "writable_profiles": [], "network_profile": null, "credential_profiles": []},
        "explanation": {"summary": "Checks syntax", "effects": [], "risks": [], "uncertainty": []}});
    mutate(&mut v);
    v
}

fn event(sequence: i64, kind: &str, status: &str, text: Option<&str>) -> Value {
    let mut sealed = json!({"execution_id": "exec-1", "sequence": sequence,
        "event_kind": kind, "status": status});
    if let Some(text) = text {
        sealed["text"] = json!(text);
    }
    json!({"execution_id": "exec-1", "chat_id": "chat-1", "project_id": "proj-1",
        "source_id": "src-1", "sequence": sequence, "event_kind": kind, "status": status,
        "encrypted_event": crypto::encrypt_combined(&sealed.to_string(), &KEY).unwrap()})
}

async fn frames(
    keys: &mut Keys,
    kind: &str,
    frame: &Value,
    state: &mut RemoteCommandState,
) -> Vec<(&'static str, Value)> {
    command_frames(keys, kind, frame, "chat-1", 150, state)
        .await
        .unwrap()
}

#[tokio::test]
async fn an_approved_review_is_prepared_sealed_under_its_digest() {
    let (mut keys, mut state) = (Keys { asked: 0 }, RemoteCommandState::default());
    state.approve = true;
    let sent = frames(
        &mut keys,
        "remote_command_review_required",
        &review(|_| {}),
        &mut state,
    )
    .await;
    assert_eq!(sent.len(), 1);
    let (name, payload) = &sent[0];
    assert_eq!(*name, "remote_command_prepare");
    let parsed = review::parse_review(&review(|_| {}).to_string()).unwrap();
    let canonical = parsed.canonical_portable_request();
    assert_eq!(
        crypto::decrypt_combined(payload["encrypted_request"].as_str().unwrap(), &KEY).unwrap(),
        canonical
    );
    assert_eq!(
        payload["request_digest"],
        request_digest(&canonical, &KEY).unwrap()
    );
    assert_eq!(payload["review_token"], "t".repeat(32));
    assert!(
        !payload.to_string().contains("--check"),
        "the command travels sealed"
    );
    assert_eq!(
        state.take_notices(),
        ["Running on the machine: node --check web-app/src/services/storage.js"]
    );
    // A re-delivered review is not prepared twice.
    assert!(
        frames(
            &mut keys,
            "remote_command_review_required",
            &review(|_| {}),
            &mut state
        )
        .await
        .is_empty()
    );
    assert_eq!(keys.asked, 1);
}

#[tokio::test]
async fn without_approval_the_review_is_rejected_and_no_key_is_read() {
    let (mut keys, mut state) = (Keys { asked: 0 }, RemoteCommandState::default());
    let sent = frames(
        &mut keys,
        "remote_command_review_required",
        &review(|_| {}),
        &mut state,
    )
    .await;
    assert_eq!(sent[0].0, "remote_command_reject");
    assert_eq!(sent[0].1["execution_id"], "exec-1");
    assert_eq!(keys.asked, 0);
    assert!(state.take_notices()[0].contains("--auto-approve"));
}

#[tokio::test]
async fn reviews_of_another_chat_or_expired_are_ignored() {
    let (mut keys, mut state) = (Keys { asked: 0 }, RemoteCommandState::default());
    state.approve = true;
    let other = review(|v| v["chat_id"] = json!("chat-2"));
    assert!(
        frames(
            &mut keys,
            "remote_command_review_required",
            &other,
            &mut state
        )
        .await
        .is_empty()
    );
    let expired = review(|v| v["review_expires_at"] = json!(120));
    assert!(
        frames(
            &mut keys,
            "remote_command_review_required",
            &expired,
            &mut state
        )
        .await
        .is_empty()
    );
    assert_eq!(keys.asked, 0);
}

#[tokio::test]
async fn events_fold_into_one_origin_completion() {
    let (mut keys, mut state) = (Keys { asked: 0 }, RemoteCommandState::default());
    state.approve = true;
    frames(
        &mut keys,
        "remote_command_review_required",
        &review(|_| {}),
        &mut state,
    )
    .await;
    let running = event(0, "status", "running", None);
    assert!(
        frames(&mut keys, "remote_command_event", &running, &mut state)
            .await
            .is_empty()
    );
    let output = event(1, "output", "running", Some("syntax ok\n"));
    assert!(
        frames(&mut keys, "remote_command_event", &output, &mut state)
            .await
            .is_empty()
    );
    let done = event(2, "terminal", "succeeded", None);
    let sent = frames(&mut keys, "remote_command_event", &done, &mut state).await;
    assert_eq!(sent[0].0, "remote_command_origin_completion");
    assert_eq!(sent[0].1["result_status"], "succeeded");
    assert_eq!(sent[0].1["model_text"], "syntax ok\n");
    // A replayed terminal event sends nothing more.
    assert!(
        frames(&mut keys, "remote_command_event", &done, &mut state)
            .await
            .is_empty()
    );
}

#[tokio::test]
async fn a_relabelled_event_is_a_protocol_error() {
    let (mut keys, mut state) = (Keys { asked: 0 }, RemoteCommandState::default());
    state.approve = true;
    frames(
        &mut keys,
        "remote_command_review_required",
        &review(|_| {}),
        &mut state,
    )
    .await;
    let mut relabelled = event(0, "status", "running", None);
    relabelled["sequence"] = json!(5);
    let error = command_frames(
        &mut keys,
        "remote_command_event",
        &relabelled,
        "chat-1",
        150,
        &mut state,
    )
    .await
    .unwrap_err();
    assert!(matches!(error, Error::Protocol));
    // Events of an unknown execution are not ours.
    let mut foreign = event(0, "status", "running", None);
    foreign["execution_id"] = json!("exec-9");
    assert!(
        frames(&mut keys, "remote_command_event", &foreign, &mut state)
            .await
            .is_empty()
    );
}

#[test]
fn debug_and_clone_never_carry_keys_or_commands() {
    let mut state = RemoteCommandState::default();
    state.runs.insert(
        "exec-1".into(),
        Run {
            review: review::parse_review(&review(|_| {}).to_string()).unwrap(),
            output: OutputState::new(),
            key: Key::new(KEY),
            completed: false,
        },
    );
    assert!(!format!("{state:?}").contains("node"));
    assert!(state.clone().runs.is_empty());
}
