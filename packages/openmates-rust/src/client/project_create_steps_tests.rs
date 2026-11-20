//! Step API of assistant Project creation for socket-owning shells: a cloud
//! request is created once per request id; a machine request creates nothing.
// contract-test: supporting surface=sdks.rust assertions=projects.creation.assistant-inferred
use super::*;
use crate::work::{FIXTURE_REQUEST as REQUEST, request_event, rest_fixture, rest_handler};

#[tokio::test]
async fn a_cloud_request_step_returns_created_once_per_request_id() {
    let (api, log, _) = rest_fixture(rest_handler(true)).await;
    let mut c = super::super::tests::client(&api);
    let event = request_event(now_ms() / 1000);
    let sent = c
        .project_create_step("project_create_requested", &event)
        .await
        .unwrap()
        .expect("a created report");
    assert_eq!(
        (sent["status"].as_str(), sent["request_id"].as_str()),
        (Some("created"), Some(REQUEST))
    );
    assert!(sent["project_id"].is_string() && sent["focus_id"].is_string());
    // The state survives between steps, so a repeated frame creates nothing.
    let requests = log.lock().unwrap().len();
    assert!(
        c.project_create_step("project_create_requested", &event)
            .await
            .unwrap()
            .is_none()
    );
    assert_eq!(log.lock().unwrap().len(), requests);
}

#[tokio::test]
async fn a_machine_request_step_reports_failed_without_any_request() {
    let (api, log, _) = rest_fixture(rest_handler(true)).await;
    let mut c = super::super::tests::client(&api);
    let mut event = request_event(now_ms() / 1000);
    let action = &mut event["pending_client_action"];
    action["location"] = json!("machine");
    action["confirmation_required"] = json!(true);
    action["focus"]["activate"] = json!("after_confirmation");
    let sent = c
        .project_create_step("project_create_requested", &event)
        .await
        .unwrap()
        .expect("a failed report");
    assert_eq!(sent["status"], "failed");
    assert!(sent["error_code"].is_string());
    assert!(log.lock().unwrap().is_empty());
}

#[tokio::test]
async fn a_frame_without_chat_id_is_invalid() {
    let mut c = super::super::tests::client("http://127.0.0.1:9");
    assert!(matches!(
        c.project_create_step("project_create_requested", &json!({}))
            .await,
        Err(Error::Invalid(_))
    ));
}
