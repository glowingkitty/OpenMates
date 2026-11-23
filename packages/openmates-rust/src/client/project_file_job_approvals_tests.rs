//! Interactive Project file-job approvals: write and ignored-read prompts,
//! accept/decline decisions, applied events and unchanged CLI frames.
use super::FileJobState;
use super::frames::{Focus, JobRunner, job_frames};
use crate::work::{
    HostedFileError, HostedFileJob, HostedFileMutation, HostedProposal, HostedResult,
    ProjectRequesterError,
};
use crate::{Error, Result};
use serde_json::{Value, json};

pub(super) const CHAT: &str = "22222222-2222-4222-8222-222222222222";
pub(super) const PROJECT: &str = "11111111-1111-4111-8111-111111111111";
pub(super) const NOW: u64 = 1_800_000_000;
pub(super) const REQUEST: &str = "project_file_operation_request";

/// Runner with a configurable digest and an optional ignored-read refusal.
pub(super) struct Runner {
    pub(super) digest: String,
    pub(super) refuse_ignored: bool,
    pub(super) executed: Vec<(String, bool, bool)>,
    /// Result body of `execute`.
    pub(super) output: Value,
    /// Arguments of every executed job.
    pub(super) seen: Vec<Value>,
}

impl Runner {
    pub(super) fn new() -> Self {
        Self {
            digest: "a".repeat(64),
            refuse_ignored: false,
            executed: Vec::new(),
            output: json!({"path": "index.html", "created": true}),
            seen: Vec::new(),
        }
    }
}

impl JobRunner for Runner {
    async fn focus(&mut self, _: &str) -> Result<Option<Focus>> {
        Ok(Some(Focus {
            project_id: PROJECT.into(),
            team_id: None,
        }))
    }
    async fn proposal(
        &mut self,
        _: &Focus,
        job: &HostedFileJob,
    ) -> HostedResult<Option<HostedProposal>> {
        // Like the real runner: reads and command batches have no proposal.
        if !job.operation.is_mutation()
            || job.operation == crate::work::HostedFileOperation::ApplyChanges
        {
            return Ok(None);
        }
        Ok(Some(HostedProposal {
            mutation: HostedFileMutation {
                operation: job.operation,
                operation_id: job.operation_id.clone(),
                path: "index.html".into(),
                expected_base: None,
                content: Some("<h1>Recipes</h1>".into()),
                patch: None,
                new_path: None,
            },
            digest: self.digest.clone(),
            requires_approval: true,
        }))
    }
    async fn execute(
        &mut self,
        _: &Focus,
        job: HostedFileJob,
        approved: bool,
        read: bool,
    ) -> HostedResult<Value> {
        self.seen.push(job.arguments.clone());
        self.executed.push((job.operation_id, approved, read));
        if self.refuse_ignored && !read {
            return Err(HostedFileError::Refused("ignored_path_requires_approval"));
        }
        Ok(self.output.clone())
    }
    async fn commit(&mut self, _: &Focus, _: &str, _: String) -> HostedResult<Value> {
        Err(HostedFileError::Refused("unsupported"))
    }
    async fn snapshot(&mut self, _: &Focus, _: Option<String>) -> HostedResult<Value> {
        Err(HostedFileError::Refused("unsupported"))
    }
    async fn execute_remote(
        &mut self,
        _: &Focus,
        _: &str,
        _: &HostedFileJob,
        _: Option<HostedFileMutation>,
    ) -> std::result::Result<Value, ProjectRequesterError> {
        Err(ProjectRequesterError::Core(Error::Cancelled))
    }
    async fn commit_remote(
        &mut self,
        _: &Focus,
        _: &str,
        _: &str,
        _: &str,
        _: &str,
    ) -> std::result::Result<Value, ProjectRequesterError> {
        Err(ProjectRequesterError::Core(Error::Cancelled))
    }
}

pub(super) fn request(operation: &str) -> Value {
    json!({"protocol_version": 1, "operation_id": "op-1", "chat_id": CHAT, "project_id": PROJECT,
        "source_id": null, "operation": operation, "arguments": {"path": "index.html", "content": "x"},
        "lease_token": "t".repeat(32), "lease_generation": 1, "lease_expires_at": NOW + 90})
}

pub(super) async fn run(
    r: &mut Runner,
    event: &Value,
    state: &mut FileJobState,
) -> Vec<(&'static str, Value)> {
    job_frames(r, REQUEST, event, CHAT, NOW, state)
        .await
        .unwrap()
}

pub(super) fn interactive() -> FileJobState {
    let mut state = FileJobState::default();
    state.approvals.interactive = true;
    state
}

#[tokio::test]
async fn interactive_write_prompts_without_reject_and_stays_unfinished() {
    let (mut r, mut state) = (Runner::new(), interactive());
    let frames = run(&mut r, &request("create_file"), &mut state).await;
    assert_eq!(frames.len(), 1);
    assert_eq!(frames[0].1["status"], "awaiting_approval");
    assert_eq!(frames[0].1["result"]["proposal_commitment"], "a".repeat(64));
    assert!(state.finished.is_empty() && state.take_notices().is_empty());
    let prompts = state.approvals.take_prompts();
    assert_eq!(prompts.len(), 1);
    assert_eq!(prompts[0]["kind"], "write");
    assert_eq!(prompts[0]["mutation"]["path"], "index.html");
    assert_eq!(prompts[0]["chat_id"], CHAT);
    assert!(r.executed.is_empty());
}

#[tokio::test]
async fn accept_reclaims_and_the_next_lease_executes_approved_with_an_applied_event() {
    let (mut r, mut state) = (Runner::new(), interactive());
    run(&mut r, &request("create_file"), &mut state).await;
    let (name, scope, finished) = state.approvals.decide("op-1", true).unwrap();
    assert_eq!((name, finished), ("project_file_operation_claim", false));
    assert_eq!(scope["operation_id"], "op-1");
    let frames = run(&mut r, &request("create_file"), &mut state).await;
    assert_eq!(frames[0].1["status"], "completed");
    assert_eq!(r.executed, vec![("op-1".to_owned(), true, false)]);
    let applied = state.approvals.take_applied();
    assert_eq!(applied.len(), 1);
    let mut event = applied[0].clone();
    // The restored mutation travels with the event for the local diff card.
    let mutation = event
        .as_object_mut()
        .and_then(|e| e.remove("mutation"))
        .expect("applied event carries the mutation");
    assert_eq!(mutation["operation"], "create_file");
    assert_eq!(mutation["path"], "index.html");
    assert_eq!(
        event,
        json!({"project_id": PROJECT, "chat_id": CHAT,
        "operation": "create_file", "path": "index.html"})
    );
    assert!(!state.approvals.write_approved("op-1", &"a".repeat(64)));
}

#[tokio::test]
async fn a_changed_proposal_after_accept_prompts_again() {
    let (mut r, mut state) = (Runner::new(), interactive());
    run(&mut r, &request("create_file"), &mut state).await;
    state.approvals.decide("op-1", true).unwrap();
    r.digest = "b".repeat(64);
    let frames = run(&mut r, &request("create_file"), &mut state).await;
    assert_eq!(frames[0].1["status"], "awaiting_approval");
    assert!(r.executed.is_empty());
}

#[tokio::test]
async fn decline_rejects_and_unknown_operations_are_ignored() {
    let (mut r, mut state) = (Runner::new(), interactive());
    run(&mut r, &request("create_file"), &mut state).await;
    assert!(state.approvals.decide("other", false).is_none());
    let (name, _, finished) = state.approvals.decide("op-1", false).unwrap();
    assert_eq!((name, finished), ("project_file_operation_reject", true));
}

#[tokio::test]
async fn ignored_read_prompts_then_accept_reclaims_and_executes_with_the_read_flag() {
    let (mut r, mut state) = (Runner::new(), interactive());
    r.refuse_ignored = true;
    let frames = run(&mut r, &request("read_text"), &mut state).await;
    assert_eq!(frames[0].1["status"], "awaiting_approval");
    assert_eq!(
        frames[0].1["result"],
        json!({"reason": "ignored_path_requires_approval", "path": "index.html"})
    );
    assert!(state.finished.is_empty());
    let prompts = state.approvals.take_prompts();
    assert_eq!(prompts[0]["kind"], "read");
    assert_eq!(prompts[0]["path"], "index.html");
    assert!(prompts[0]["source_id"].is_null());
    let (name, _, _) = state.approvals.decide("op-1", true).unwrap();
    assert_eq!(name, "project_file_operation_claim");
    let frames = run(&mut r, &request("read_text"), &mut state).await;
    assert_eq!(frames[0].1["status"], "completed");
    assert_eq!(
        r.executed.last().unwrap(),
        &("op-1".to_owned(), false, true)
    );
}

#[tokio::test]
async fn non_interactive_frames_stay_awaiting_then_reject() {
    let (mut r, mut state) = (Runner::new(), FileJobState::default());
    let frames = run(&mut r, &request("create_file"), &mut state).await;
    assert_eq!(frames.len(), 2);
    assert_eq!(frames[0].1["status"], "awaiting_approval");
    assert_eq!(frames[1].0, "project_file_operation_reject");
    assert!(state.finished.contains("op-1"));
    assert!(state.approvals.take_prompts().is_empty());
}

#[test]
fn per_chat_states_are_bounded() {
    let mut chats = super::FileJobChats::default();
    for i in 0..20 {
        let chat = format!("chat-{i}");
        let state = chats.take(&chat, true);
        chats.put(&chat, state);
    }
    let mut kept = 0;
    for i in 0..20 {
        let chat = format!("chat-{i}");
        let state = chats.take(&chat, true);
        kept += usize::from(state.approvals.interactive);
    }
    assert_eq!(kept, 20, "taken states are always usable");
}

#[tokio::test]
async fn an_applied_command_batch_records_one_diff_card_per_written_file() {
    let (mut r, mut state) = (Runner::new(), interactive());
    r.output = json!({"origin": "command", "execution_id": "exec-1", "applied": 3, "refused": 1,
    "results": [
        {"path": "web-app/package-lock.json", "kind": "create", "status": "applied", "created": true},
        {"path": "web-app/package.json", "kind": "update", "status": "applied",
         "applied_diff": "--- a/web-app/package.json\n+++ b/web-app/package.json\n"},
        {"path": "web-app/README.md", "kind": "update", "status": "applied", "idempotent": true},
        {"path": "web-app/.env", "kind": "create", "status": "refused", "reason": "private_path"},
    ]});
    let mut event = request("apply_changes");
    event["arguments"] = json!({"origin": "command", "execution_id": "exec-1", "changes": [
        {"path": "web-app/package-lock.json", "kind": "create", "expected_base": null, "content": "{\"lockfileVersion\": 3}\n"},
        {"path": "web-app/package.json", "kind": "update", "expected_base": "b".repeat(64), "content": "{}\n"},
        {"path": "web-app/README.md", "kind": "update", "expected_base": "c".repeat(64), "content": "same\n"},
        {"path": "web-app/.env", "kind": "create", "expected_base": null, "content": "SECRET=x\n"},
    ]});
    let frames = run(&mut r, &event, &mut state).await;
    assert_eq!(frames[0].1["status"], "completed");
    let applied = state.approvals.take_applied();
    let cards: Vec<(&str, &str)> = applied
        .iter()
        .map(|e| {
            (
                e["operation"].as_str().unwrap(),
                e["path"].as_str().unwrap(),
            )
        })
        .collect();
    assert_eq!(
        cards,
        vec![
            ("create_file", "web-app/package-lock.json"),
            ("update_file", "web-app/package.json")
        ]
    );
    assert_eq!(
        applied[0]["mutation"]["content"],
        "{\"lockfileVersion\": 3}\n"
    );
    assert_eq!(applied[0]["mutation"]["operation_id"], "op-1:0");
    assert_eq!(
        applied[1]["mutation"]["patch"],
        "--- a/web-app/package.json\n+++ b/web-app/package.json\n"
    );
    assert_eq!(
        state.take_notices(),
        vec![
            "Project file created: web-app/package-lock.json".to_owned(),
            "Project file updated: web-app/package.json".to_owned(),
        ]
    );
}
