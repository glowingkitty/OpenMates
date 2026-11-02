use super::*;
use crate::work::tasks::tests::{client, mock};
const FLOW: &str = "dbaaccdd-1111-4111-8111-aabbccddeeff";
const TEAM: &str = "ccaaccdd-1111-4111-8111-aabbccddeeff";
#[test]
fn typed_graph_matches_wire_edges_and_rejects_ambiguous_ids() {
    assert_eq!(
        serde_json::to_value(WorkflowRetention::default()).unwrap(),
        "last_5"
    );
    let mut graph:WorkflowGraph=serde_json::from_value(json!({"version":2,"nodes":[{"id":"start","type":"manual_trigger"},{"id":"end","type":"end"}],"trigger_node_id":"start","edges":[{"from":"start","to":"end"}]})).unwrap();
    validate_graph(&graph).unwrap();
    assert_eq!(
        serde_json::to_value(&graph).unwrap()["edges"][0]["from"],
        "start"
    );
    graph.nodes[1].id = "start".into();
    assert!(validate_graph(&graph).is_err());
    assert!(
        serde_json::from_value::<WorkflowCreate>(json!({"title":"test","provider":"custom"}))
            .is_err()
    );
}
#[tokio::test]
async fn run_has_stable_idempotency_and_no_invented_routing() {
    let (api, server) = mock(vec![json!({"run":{"run_id":"run-1","status":"queued"}})]).await;
    let mut client = client(&api);
    let result = client
        .workflows()
        .run(
            FLOW,
            WorkflowRunOptions {
                idempotency_key: "immutable-intent-1".into(),
                input: BTreeMap::from([("topic".into(), json!("fixture"))]),
                ..Default::default()
            },
        )
        .await
        .unwrap();
    assert_eq!(result["run_id"], "run-1");
    let requests = server.await.unwrap();
    assert!(
        requests[0]
            .to_lowercase()
            .contains("idempotency-key: immutable-intent-1")
    );
    assert!(requests[0].starts_with(&format!("POST /v1/workflows/{FLOW}/run ")));
    let body: Value = serde_json::from_str(requests[0].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(
        body,
        json!({"mode":"manual","input":{"topic":"fixture"},"message_destination_overrides":{},"return_outputs":{}})
    );
}
#[tokio::test]
async fn unsupported_team_destructive_and_privacy_operations_precede_dispatch() {
    let mut client = client("http://127.0.0.1:1");
    let filters = WorkflowFilters {
        team_id: Some(TEAM.into()),
        ..Default::default()
    };
    assert!(matches!(
        client
            .workflows()
            .with_filters(filters)
            .run(
                FLOW,
                WorkflowRunOptions {
                    idempotency_key: "intent".into(),
                    ..Default::default()
                }
            )
            .await,
        Err(Error::Unavailable {
            reason: "TEAM_WORKFLOW_OPERATION_UNAVAILABLE",
            ..
        })
    ));
    assert!(matches!(
        client.workflows().delete(FLOW, false).await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        client.workflows().run(FLOW, Default::default()).await,
        Err(Error::Invalid(_))
    ));
    client.set_private_operation_gate(Some(std::sync::Arc::new(|| Err(Error::Forbidden))));
    assert!(matches!(
        client
            .workflows()
            .create(WorkflowCreate {
                title: "fixture".into(),
                ..Default::default()
            })
            .await,
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        client
            .workflows()
            .start_input(WorkflowInputOptions {
                text: Some("fixture".into()),
                ..Default::default()
            })
            .await,
        Err(Error::Forbidden)
    ));
}
#[tokio::test]
async fn encrypted_slug_resolves_without_display_pagination() {
    let encrypted = crypto::encrypt_combined("weekly-review", &[7; 32]).unwrap();
    let row = json!({"id":FLOW,"title":"Weekly Review","encrypted_slug":encrypted,"slug_lookup_hash":"private-index","graph":{"nodes":[],"edges":[]}});
    let (api, server) = mock(vec![json!({"workflows":[row]}), json!({"workflow":row})]).await;
    let mut client = client(&api);
    let result = client
        .workflows()
        .with_filters(WorkflowFilters {
            offset: Some(10),
            limit: Some(1),
            ..Default::default()
        })
        .get("weekly-review")
        .await
        .unwrap();
    assert_eq!(result["slug"], "weekly-review");
    assert!(result.get("encrypted_slug").is_none());
    assert!(server.await.unwrap()[0].starts_with("GET /v1/workflows "));
}
#[tokio::test]
async fn opaque_ids_are_encoded_and_session_operations_keep_exact_scope() {
    let (api, server) = mock(vec![json!({"events":[{"event_id":4}]})]).await;
    let mut client = client(&api);
    let result = client
        .workflows()
        .with_filters(WorkflowFilters {
            team_id: Some(TEAM.into()),
            ..Default::default()
        })
        .input_events("session/a", 3)
        .await
        .unwrap();
    assert_eq!(result[0]["event_id"], 4);
    assert!(server.await.unwrap()[0].starts_with(&format!(
        "GET /v1/workflows/input/session%2Fa/events?team_id={TEAM}&after_event_id=3 "
    )));
}
