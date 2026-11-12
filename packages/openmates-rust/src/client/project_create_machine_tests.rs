//! Machine Project requests: nothing is created before the user decides; the
//! confirm path order, rollback on a machine failure, decline and unchanged cloud requests.
use super::*;
use crate::work::{
    FIXTURE_CHAT as CHAT, FIXTURE_REQUEST as REQUEST, RemoteOpCode, request_event, rest_fixture,
    rest_handler,
};
use std::sync::{Arc, Mutex};

const NOW: u64 = 1_800_000_000;
const HOST: &str = "abababababababababababababababababababababababababababababababab";

fn machine_event() -> Value {
    let mut event = request_event(NOW);
    let action = &mut event["pending_client_action"];
    *action = json!({
        "contract": action["contract"], "version": 1, "request_id": REQUEST, "action": "create",
        "origin": "preprocessor", "chat_id": CHAT, "message_id": "m", "team_id": null,
        "name": "Recipe Manager", "description": "", "kind": null, "subfolder": null,
        "write_mode": "apply_and_show", "location": "machine", "confirmation_required": true,
        "machine_hint": "work laptop", "focus": {"activate": "after_confirmation", "countdown_seconds": 0},
        "undo": {"available": true}, "created_at": NOW, "expires_at": NOW + 600, "notification_queued": false,
    });
    event
}

fn idle() -> Client {
    super::super::tests::client("http://127.0.0.1:9")
}

/// Records the order of the steps; `fail_create` makes the folder step fail.
struct Fake {
    log: Arc<Mutex<Vec<String>>>,
    hosts: Vec<MachineHost>,
    fail_create: Option<RemoteOpCode>,
}

impl Fake {
    fn new(fail_create: Option<RemoteOpCode>) -> Self {
        Self {
            log: Arc::default(),
            hosts: vec![host()],
            fail_create,
        }
    }
    fn note(&self, step: &str) {
        self.log.lock().unwrap().push(step.to_owned());
    }
}

fn host() -> MachineHost {
    MachineHost {
        host_device_hash: HOST.into(),
        source_names: vec!["repo".into()],
    }
}

impl MachineSteps for Fake {
    async fn hosts(&mut self) -> std::result::Result<Vec<MachineHost>, RemoteOpError> {
        Ok(self.hosts.clone())
    }
    async fn create_project(
        &mut self,
        request: &ProjectCreateRequest,
    ) -> Result<CreatedProjectRecord> {
        self.note("project+focus");
        Ok(CreatedProjectRecord {
            request_id: request.request_id.clone(),
            chat_id: request.chat_id.clone(),
            project_id: "11111111-1111-4111-8111-111111111111".into(),
            focus_id: "22222222-2222-4222-8222-222222222222".into(),
            name: request.name.clone(),
            kind: request.kind.clone(),
            subfolder: request.subfolder.clone(),
            team_id: None,
            undo_available: true,
        })
    }
    async fn undo_project(&mut self, _: &CreatedProjectRecord) -> Result<()> {
        self.note("undo");
        Ok(())
    }
    async fn propose(
        &mut self,
        _: &str,
        host: &str,
        name: &str,
    ) -> std::result::Result<String, RemoteOpError> {
        assert_eq!((host, name), (HOST, "Recipe Manager"));
        self.note("placeholder");
        Ok("source-1".into())
    }
    async fn create(
        &mut self,
        _: &str,
        source: &str,
        chat: &str,
        operation: &str,
        name: &str,
    ) -> std::result::Result<CreatedMachineSource, RemoteOpError> {
        assert_eq!((source, chat, name), ("source-1", CHAT, "Recipe Manager"));
        assert!(!operation.is_empty());
        self.note("create");
        match &self.fail_create {
            Some(code) => Err(RemoteOpError::Host {
                code: code.clone(),
                message: "no".into(),
            }),
            None => Ok(CreatedMachineSource {
                path: "/home/me/Projects/recipe-manager".into(),
                folder_name: "recipe-manager".into(),
                head: "abc".into(),
                branch: "main".into(),
            }),
        }
    }
}

async fn pending(c: &mut Client, state: &mut ProjectCreateState) {
    let sent = c
        .project_create_report(
            "project_create_requested",
            &machine_event(),
            CHAT,
            NOW,
            state,
        )
        .await
        .unwrap();
    assert!(
        sent.is_none(),
        "a machine request answers nothing until the user decides"
    );
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[tokio::test]
async fn a_machine_request_creates_nothing_and_yields_a_confirmation_card() {
    let (api, log, stored) = rest_fixture(rest_handler(true)).await;
    let (mut c, mut state) = (
        super::super::tests::client(&api),
        ProjectCreateState::default(),
    );
    pending(&mut c, &mut state).await;
    assert!(log.lock().unwrap().is_empty() && stored.lock().unwrap().is_none());
    let card = &state.cards()[0];
    assert_eq!(card["status"], "confirmation_required");
    assert_eq!(
        (card["requestId"].as_str(), card["name"].as_str()),
        (Some(REQUEST), Some("Recipe Manager"))
    );
    assert_eq!(card["machineHint"], "work laptop");
    assert_eq!(card["undoAvailable"], false);
    let invalid = |mutate: &dyn Fn(&mut Value)| {
        let mut event = machine_event();
        mutate(&mut event);
        ProjectCreateRequest::parse(&event, CHAT, NOW).is_err()
    };
    assert!(invalid(
        &|e| e["pending_client_action"]["location"] = json!("moon")
    ));
    assert!(invalid(
        &|e| e["pending_client_action"]["confirmation_required"] = json!(false)
    ));
    assert!(invalid(
        &|e| e["pending_client_action"]["focus"]["activate"] = json!("immediate")
    ));
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[tokio::test]
async fn confirming_creates_project_focus_placeholder_folder_then_reports_confirmed() {
    let (mut c, mut state) = (idle(), ProjectCreateState::default());
    pending(&mut c, &mut state).await;
    let mut fake = Fake::new(None);
    let decision = MachineProjectDecision::Confirm {
        host_device_hash: None,
    };
    let sent = decide(&mut fake, CHAT, REQUEST, decision, &mut state)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        *fake.log.lock().unwrap(),
        ["project+focus", "placeholder", "create"]
    );
    assert_eq!(sent["status"], "confirmed");
    assert_eq!(sent["source_id"], "source-1");
    assert_eq!(sent["path"], "/home/me/Projects/recipe-manager");
    assert_eq!(sent["folder_name"], "recipe-manager");
    assert!(sent["project_id"].is_string() && sent["focus_id"].is_string());
    let card = &state.cards()[0];
    assert_eq!(
        (card["status"].as_str(), card["undoAvailable"].clone()),
        (Some("created"), json!(false))
    );
    assert_eq!(card["machine"]["folderName"], "recipe-manager");
    assert!(
        decide(
            &mut fake,
            CHAT,
            REQUEST,
            MachineProjectDecision::Decline,
            &mut state
        )
        .await
        .unwrap()
        .is_none()
    );
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[tokio::test]
async fn a_machine_failure_undoes_the_project_and_reports_the_code() {
    let (mut c, mut state) = (idle(), ProjectCreateState::default());
    pending(&mut c, &mut state).await;
    let mut fake = Fake::new(Some(RemoteOpCode::TargetExists));
    let decision = MachineProjectDecision::Confirm {
        host_device_hash: Some(HOST.into()),
    };
    let sent = decide(&mut fake, CHAT, REQUEST, decision, &mut state)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        *fake.log.lock().unwrap(),
        ["project+focus", "placeholder", "create", "undo"]
    );
    assert_eq!(
        (sent["status"].as_str(), sent["error_code"].as_str()),
        (Some("failed"), Some("target_exists"))
    );
    assert!(sent.get("project_id").is_none());
    assert_eq!(state.cards()[0]["status"], "failed");
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[tokio::test]
async fn no_machine_unavailable_and_decline_create_nothing() {
    let (mut c, mut state) = (idle(), ProjectCreateState::default());
    pending(&mut c, &mut state).await;
    let mut fake = Fake::new(None);
    fake.hosts.clear();
    let confirm = MachineProjectDecision::Confirm {
        host_device_hash: None,
    };
    let sent = decide(&mut fake, CHAT, REQUEST, confirm, &mut state)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        (sent["status"].as_str(), sent["error_code"].as_str()),
        (Some("failed"), Some("no_machine_host"))
    );
    assert!(fake.log.lock().unwrap().is_empty());

    let mut state = ProjectCreateState::default();
    pending(&mut c, &mut state).await;
    let declined = decide(
        &mut fake,
        CHAT,
        REQUEST,
        MachineProjectDecision::Decline,
        &mut state,
    )
    .await;
    assert_eq!(
        declined.unwrap().unwrap(),
        json!({"chat_id": CHAT, "request_id": REQUEST, "status": "declined"})
    );
    assert_eq!(state.cards()[0]["status"], "declined");
    assert!(fake.log.lock().unwrap().is_empty());
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[tokio::test]
async fn a_cloud_request_is_still_created_immediately() {
    let (api, _, stored) = rest_fixture(rest_handler(true)).await;
    let (mut c, mut state) = (
        super::super::tests::client(&api),
        ProjectCreateState::default(),
    );
    let sent = c
        .project_create_report(
            "project_create_requested",
            &request_event(NOW),
            CHAT,
            NOW,
            &mut state,
        )
        .await
        .unwrap()
        .unwrap();
    assert_eq!(sent["status"], "created");
    assert!(stored.lock().unwrap().is_some());
    assert_eq!(state.cards()[0]["status"], "created");
}
