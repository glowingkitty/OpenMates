use super::*;
use crate::work::HostedFileOperation;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const PROJECT: &str = "11111111-1111-4111-8111-111111111111";
const NOW: u64 = 1_800_000_000;

/// In-memory runner: counts executions and answers a fixed outcome.
struct Fake {
    focus: Option<Focus>,
    requires_approval: bool,
    outcome: HostedResult<Value>,
    executed: Vec<(String, bool)>,
}

impl Fake {
    fn new(requires_approval: bool) -> Self {
        Self {
            focus: Some(Focus {
                project_id: PROJECT.into(),
                team_id: None,
            }),
            requires_approval,
            outcome: Ok(json!({"path": "index.html", "revision": 1, "created": true})),
            executed: Vec::new(),
        }
    }
}

impl JobRunner for Fake {
    async fn focus(&mut self, _: &str) -> Result<Option<Focus>> {
        Ok(self.focus.clone())
    }
    async fn proposal(
        &mut self,
        _: &Focus,
        job: &HostedFileJob,
    ) -> HostedResult<Option<HostedProposal>> {
        if !job.operation.is_mutation() {
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
            },
            digest: "d".repeat(64),
            requires_approval: self.requires_approval,
        }))
    }
    async fn execute(
        &mut self,
        _: &Focus,
        job: HostedFileJob,
        approved: bool,
    ) -> HostedResult<Value> {
        self.executed.push((job.operation_id, approved));
        self.outcome.clone()
    }
}

fn request(operation: &str, expires: u64) -> Value {
    json!({"protocol_version": 1, "operation_id": "op-1", "chat_id": CHAT, "project_id": PROJECT,
        "source_id": null, "operation": operation, "arguments": {"path": "index.html", "content": "x"},
        "lease_token": "t".repeat(32), "lease_generation": 1, "lease_expires_at": expires})
}

async fn run(
    fake: &mut Fake,
    kind: &str,
    event: &Value,
    state: &mut FileJobState,
) -> Vec<(&'static str, Value)> {
    job_frames(fake, kind, event, CHAT, NOW, state)
        .await
        .unwrap()
}

const REQUEST: &str = "project_file_operation_request";

#[tokio::test]
async fn available_is_claimed_with_the_scope_and_a_request_completes_with_the_commitment() {
    let (mut fake, mut state) = (Fake::new(false), FileJobState::default());
    let claim = run(
        &mut fake,
        "project_file_operation_available",
        &request("create_file", NOW + 90),
        &mut state,
    )
    .await;
    assert_eq!(claim.len(), 1);
    assert_eq!(claim[0].0, "project_file_operation_claim");
    assert_eq!(
        claim[0].1,
        json!({"protocol_version": 1, "operation_id": "op-1", "chat_id": CHAT, "project_id": PROJECT})
    );
    let sent = run(
        &mut fake,
        REQUEST,
        &request("create_file", NOW + 90),
        &mut state,
    )
    .await;
    assert_eq!(sent.len(), 1);
    let (name, payload) = &sent[0];
    assert_eq!(*name, "project_file_operation_result");
    assert_eq!(
        (
            payload["status"].as_str(),
            payload["lease_generation"].as_u64()
        ),
        (Some("completed"), Some(1))
    );
    assert_eq!(payload["lease_token"], "t".repeat(32));
    assert_eq!(payload["result"]["proposal_commitment"], "d".repeat(64));
    assert!(payload["result"]["source_id"].is_null());
    assert_eq!(fake.executed, vec![("op-1".to_owned(), false)]);
    assert_eq!(
        state.take_notices(),
        vec!["Project file created: index.html".to_owned()]
    );
    // A repeated frame for a finished operation does nothing.
    assert!(
        run(
            &mut fake,
            REQUEST,
            &request("create_file", NOW + 90),
            &mut state
        )
        .await
        .is_empty()
    );
    assert_eq!(fake.executed.len(), 1);
}

#[tokio::test]
async fn reads_complete_without_a_commitment() {
    let mut fake = Fake::new(false);
    fake.outcome = Ok(json!({"files": []}));
    let sent = run(
        &mut fake,
        REQUEST,
        &request("list", NOW + 90),
        &mut FileJobState::default(),
    )
    .await;
    assert_eq!(sent[0].1["status"], "completed");
    assert!(sent[0].1["result"].get("proposal_commitment").is_none());
}

#[tokio::test]
async fn malformed_frames_and_leases_are_ignored() {
    let mut state = FileJobState::default();
    let mut fake = Fake::new(false);
    for mutate in [
        |v: &mut Value| v["protocol_version"] = json!(2),
        |v: &mut Value| v["chat_id"] = json!("other-chat"),
        |v: &mut Value| v["operation"] = json!("delete_everything"),
        |v: &mut Value| v["lease_token"] = json!("short"),
        |v: &mut Value| v["lease_generation"] = json!(0),
        |v: &mut Value| v["lease_expires_at"] = json!("soon"),
        |v: &mut Value| v["arguments"] = json!([]),
    ] {
        let mut event = request("create_file", NOW + 90);
        mutate(&mut event);
        assert!(
            run(&mut fake, REQUEST, &event, &mut state).await.is_empty(),
            "{event}"
        );
    }
    assert!(fake.executed.is_empty());
}

#[tokio::test]
async fn an_expired_lease_fails_without_executing() {
    let mut fake = Fake::new(false);
    let sent = run(
        &mut fake,
        REQUEST,
        &request("create_file", NOW - 1),
        &mut FileJobState::default(),
    )
    .await;
    assert_eq!(
        (
            sent[0].1["status"].as_str(),
            sent[0].1["result"]["code"].as_str()
        ),
        (Some("failed"), Some("lease_expired"))
    );
    assert!(fake.executed.is_empty());
}

#[tokio::test]
async fn a_lease_that_runs_out_during_execution_is_failed() {
    struct Slow;
    impl JobRunner for Slow {
        async fn focus(&mut self, _: &str) -> Result<Option<Focus>> {
            Ok(Some(Focus {
                project_id: PROJECT.into(),
                team_id: None,
            }))
        }
        async fn proposal(
            &mut self,
            _: &Focus,
            _: &HostedFileJob,
        ) -> HostedResult<Option<HostedProposal>> {
            Ok(None)
        }
        async fn execute(&mut self, _: &Focus, _: HostedFileJob, _: bool) -> HostedResult<Value> {
            tokio::time::sleep(Duration::from_secs(30)).await;
            Ok(json!({}))
        }
    }
    let sent = job_frames(
        &mut Slow,
        REQUEST,
        &request("list", NOW + 1),
        CHAT,
        NOW,
        &mut FileJobState::default(),
    )
    .await
    .unwrap();
    assert_eq!(sent[0].1["result"]["code"], "lease_expired");
}

#[tokio::test]
async fn refusals_map_to_conflict_failed_and_waiting() {
    for (error, status, key, value) in [
        (
            HostedFileError::Refused("stale_base"),
            "conflict",
            "code",
            "stale_base",
        ),
        (
            HostedFileError::Refused("protected_path"),
            "failed",
            "code",
            "protected_path",
        ),
        (
            HostedFileError::Core(Error::Offline),
            "waiting_for_executor",
            "reason",
            "protocol_timeout",
        ),
    ] {
        let mut fake = Fake::new(false);
        fake.outcome = Err(error);
        let sent = run(
            &mut fake,
            REQUEST,
            &request("update_file", NOW + 90),
            &mut FileJobState::default(),
        )
        .await;
        assert_eq!(sent[0].1["status"], status);
        assert_eq!(sent[0].1["result"][key], value);
    }
}

#[tokio::test]
async fn a_missing_or_other_focus_is_refused() {
    let mut fake = Fake::new(false);
    fake.focus = None;
    let sent = run(
        &mut fake,
        REQUEST,
        &request("list", NOW + 90),
        &mut FileJobState::default(),
    )
    .await;
    assert_eq!(sent[0].1["result"]["code"], "project_focus_required");
    assert!(fake.executed.is_empty());
}

#[tokio::test]
async fn a_remote_source_job_waits_for_its_executor() {
    let mut fake = Fake::new(false);
    let mut event = request("read_text", NOW + 90);
    event["source_id"] = json!("source-1");
    let sent = run(&mut fake, REQUEST, &event, &mut FileJobState::default()).await;
    assert_eq!(
        (
            sent[0].1["status"].as_str(),
            sent[0].1["result"]["reason"].as_str()
        ),
        (Some("waiting_for_executor"), Some("source_offline"))
    );
    assert!(fake.executed.is_empty());
}

#[tokio::test]
async fn always_ask_is_declined_with_the_proposal_when_not_approved() {
    let (mut fake, mut state) = (Fake::new(true), FileJobState::default());
    let sent = run(
        &mut fake,
        REQUEST,
        &request("create_file", NOW + 90),
        &mut state,
    )
    .await;
    assert_eq!(sent.len(), 2);
    assert_eq!(sent[0].1["status"], "awaiting_approval");
    assert_eq!(sent[0].1["result"]["proposal_commitment"], "d".repeat(64));
    assert_eq!(sent[0].1["result"]["proposal"]["path"], "index.html");
    assert_eq!(
        sent[0].1["result"]["proposal"]["operation"],
        json!(HostedFileOperation::CreateFile)
    );
    assert_eq!(sent[1].0, "project_file_operation_reject");
    assert_eq!(
        sent[1].1,
        json!({"protocol_version": 1, "operation_id": "op-1", "chat_id": CHAT, "project_id": PROJECT})
    );
    assert!(fake.executed.is_empty());
    assert!(state.take_notices()[0].contains("--auto-approve"));
}

#[tokio::test]
async fn always_ask_runs_when_the_shell_approves() {
    let (mut fake, mut state) = (
        Fake::new(true),
        FileJobState {
            approve_writes: true,
            ..Default::default()
        },
    );
    let sent = run(
        &mut fake,
        REQUEST,
        &request("create_file", NOW + 90),
        &mut state,
    )
    .await;
    assert_eq!(sent.len(), 1);
    assert_eq!(sent[0].1["status"], "completed");
    assert_eq!(fake.executed, vec![("op-1".to_owned(), true)]);
}
