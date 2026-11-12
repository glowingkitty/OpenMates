//! Request/reply handling of assistant-initiated Project creation against an
//! in-process REST server: created, expired, duplicate, failure, rejection, undo.
// contract-test: supporting surface=sdks.rust assertions=projects.creation.assistant-inferred
use super::*;
use crate::Session;
use crate::work::{
    FIXTURE_CHAT as CHAT, FIXTURE_REQUEST as REQUEST, request_event, rest_fixture, rest_handler,
};

pub(super) fn client(api: &str) -> Client {
    Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: "fixture".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "fixture-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}

const NOW: u64 = 1_800_000_000;

async fn report(
    c: &mut Client,
    kind: &str,
    event: &Value,
    state: &mut ProjectCreateState,
) -> Option<Value> {
    c.project_create_report(kind, event, CHAT, NOW, state)
        .await
        .unwrap()
}

#[tokio::test]
async fn a_request_creates_the_project_once_and_reports_created() {
    let (api, log, _) = rest_fixture(rest_handler(true)).await;
    let (mut c, mut state) = (client(&api), ProjectCreateState::default());
    let event = request_event(NOW);
    let sent = report(&mut c, "project_create_requested", &event, &mut state)
        .await
        .unwrap();
    assert_eq!(sent["status"], "created");
    assert_eq!(sent["request_id"], REQUEST);
    assert!(sent["project_id"].is_string() && sent["focus_id"].is_string());
    // A duplicate event for the same request id sends nothing and creates nothing.
    assert!(
        report(&mut c, "project_create_requested", &event, &mut state)
            .await
            .is_none()
    );
    assert_eq!(log.lock().unwrap().len(), 2);
    let card = &state.cards()[0];
    assert_eq!(
        (card["name"].as_str(), card["subfolder"].as_str()),
        (Some("Recipe Manager"), Some("web-app"))
    );
    assert_eq!(
        (card["undoAvailable"].clone(), card["confirmed"].clone()),
        (json!(true), json!(false))
    );
    report(
        &mut c,
        "project_create_confirmed",
        &json!({"request_id":REQUEST,"status":"created"}),
        &mut state,
    )
    .await;
    assert_eq!(state.cards()[0]["confirmed"], true);
}

#[tokio::test]
async fn an_expired_request_creates_nothing_and_reports_failed() {
    let (api, log, _) = rest_fixture(rest_handler(true)).await;
    let (mut c, mut state) = (client(&api), ProjectCreateState::default());
    let event = request_event(NOW - 3_600);
    let sent = report(&mut c, "project_create_requested", &event, &mut state)
        .await
        .unwrap();
    assert_eq!(
        (sent["status"].as_str(), sent["error_code"].as_str()),
        (Some("failed"), Some("PROJECT_CREATE_REQUEST_EXPIRED"))
    );
    assert!(log.lock().unwrap().is_empty());
}

#[tokio::test]
async fn a_failed_creation_is_reported_with_a_code_and_leaves_no_project() {
    let (api, _, stored) = rest_fixture(rest_handler(false)).await;
    let (mut c, mut state) = (client(&api), ProjectCreateState::default());
    let sent = report(
        &mut c,
        "project_create_requested",
        &request_event(NOW),
        &mut state,
    )
    .await
    .unwrap();
    assert_eq!(sent["status"], "failed");
    assert_eq!(sent["error_code"], "PROJECT_CREATE_FAILED");
    assert!(sent.get("project_id").is_none());
    assert!(stored.lock().unwrap().is_none());
    assert_eq!(state.cards()[0]["status"], "failed");
}

#[tokio::test]
async fn a_server_rejection_rolls_the_project_back_and_reports_failed_once() {
    let (api, _, stored) = rest_fixture(rest_handler(true)).await;
    let (mut c, mut state) = (client(&api), ProjectCreateState::default());
    report(
        &mut c,
        "project_create_requested",
        &request_event(NOW),
        &mut state,
    )
    .await
    .unwrap();
    let error = json!({"request_id":REQUEST,"code":"PROJECT_FOCUS_REQUIRED","chat_id":CHAT});
    let sent = report(&mut c, "project_create_error", &error, &mut state)
        .await
        .unwrap();
    assert_eq!(
        (sent["status"].as_str(), sent["error_code"].as_str()),
        (Some("failed"), Some("PROJECT_FOCUS_REQUIRED"))
    );
    assert!(
        stored.lock().unwrap().is_none(),
        "the rejected Project is deleted"
    );
    assert!(
        report(&mut c, "project_create_error", &error, &mut state)
            .await
            .is_none()
    );
}

#[tokio::test]
async fn undo_while_the_request_is_open_deletes_the_project_and_reports_undone() {
    let (api, _, stored) = rest_fixture(rest_handler(true)).await;
    let (mut c, mut state) = (client(&api), ProjectCreateState::default());
    report(
        &mut c,
        "project_create_requested",
        &request_event(NOW),
        &mut state,
    )
    .await
    .unwrap();
    let sent = c
        .project_create_undo_report(CHAT, REQUEST, &mut state)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(sent["status"], "undone");
    assert!(stored.lock().unwrap().is_none());
    assert_eq!(state.cards()[0]["undoAvailable"], false);
}

#[tokio::test]
async fn undo_after_confirmation_sends_no_message() {
    let (api, _, stored) = rest_fixture(rest_handler(true)).await;
    let (mut c, mut state) = (client(&api), ProjectCreateState::default());
    report(
        &mut c,
        "project_create_requested",
        &request_event(NOW),
        &mut state,
    )
    .await
    .unwrap();
    report(
        &mut c,
        "project_create_confirmed",
        &json!({"request_id":REQUEST}),
        &mut state,
    )
    .await;
    assert!(
        c.project_create_undo_report(CHAT, REQUEST, &mut state)
            .await
            .unwrap()
            .is_none()
    );
    assert!(stored.lock().unwrap().is_none());
}

// contract-test: supporting surface=sdks.rust assertions=projects.creation.assistant-inferred
#[tokio::test]
async fn the_activation_frame_persists_the_created_focus_and_marks_the_card() {
    let (api, _, _) = rest_fixture(rest_handler(true)).await;
    let (mut c, mut state) = (client(&api), ProjectCreateState::default());
    let sent = report(
        &mut c,
        "project_create_requested",
        &request_event(NOW),
        &mut state,
    )
    .await
    .unwrap();
    let focus = sent["focus_id"].as_str().unwrap().to_owned();
    assert_eq!(
        state.cards()[0]["focusPersisted"],
        false,
        "creation itself never writes the active focus"
    );
    // The server's `focus_mode_activated` frame names the bound default focus id.
    let key = [11; 32];
    let mut previous = json!({});
    let frame = json!({"chat_id": CHAT, "focus_id": focus});
    let mut plan = super::super::focus::FocusPersistencePlan::prepare(
        "focus_mode_activated",
        &frame,
        CHAT,
        &key,
        &mut previous,
    )
    .unwrap();
    let (kind, payload, ack) = plan
        .next_effect(&key, || Ok(None))
        .unwrap()
        .unwrap()
        .into_wire();
    assert_eq!(kind, "update_encrypted_active_focus_id");
    assert!(ack.is_none());
    assert_eq!(
        crypto::decrypt_combined(payload["encrypted_active_focus_id"].as_str().unwrap(), &key)
            .unwrap(),
        focus
    );
    assert!(plan.next_effect(&key, || Ok(None)).unwrap().is_none());
    state.mark_focus_persisted("33333333-3333-4333-8333-333333333333");
    assert_eq!(
        state.cards()[0]["focusPersisted"],
        false,
        "another focus never marks the card"
    );
    state.mark_focus_persisted(&focus);
    assert_eq!(state.cards()[0]["focusPersisted"], true);
}

// contract-test: supporting surface=sdks.rust assertions=projects.creation.assistant-inferred
#[tokio::test]
async fn a_failed_creation_is_never_marked_focus_persisted() {
    let (api, _, _) = rest_fixture(rest_handler(false)).await;
    let (mut c, mut state) = (client(&api), ProjectCreateState::default());
    report(
        &mut c,
        "project_create_requested",
        &request_event(NOW),
        &mut state,
    )
    .await
    .unwrap();
    state.mark_focus_persisted("");
    assert_eq!(state.cards()[0]["focusPersisted"], false);
}
