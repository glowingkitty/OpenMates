use super::*;
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
const PLAN: &str = "aabbccdd-1111-4111-8111-aabbccddeeff";
fn input() -> PlanCreate {
    PlanCreate {
        plan_id: Some(PLAN.into()),
        title: "Private title".into(),
        goal: "Private accepted goal".into(),
        linked_project_ids: vec![PROJECT.into()],
        ..Default::default()
    }
}
fn raw() -> Value {
    let mut raw = encode_create(&input(), &[8; 32], &[7; 32]).unwrap();
    raw["key_wrappers"] = json!([{"key_type":"master","encrypted_plan_key":crypto::encrypt_bytes(&[8;32],&[7;32]).unwrap()}]);
    raw
}
#[test]
fn plan_codec_encrypts_private_fields_and_keeps_server_approval_read_only() {
    let raw = raw();
    let encoded = raw.to_string();
    assert!(!encoded.contains("Private title"));
    assert!(!encoded.contains("Private accepted goal"));
    assert!(raw.get("approval_state").is_none());
    assert!(serde_json::from_value::<PlanCreate>(json!({"approval_state":"approved"})).is_err());
    let plan = decode(raw, &[7; 32]).unwrap();
    assert_eq!(plan.public["title"], "Private title");
    assert_eq!(plan.public["goal"], "Private accepted goal");
    assert_eq!(plan.public["linked_project_ids"], json!([PROJECT]));
    let patch: PlanPatch =
        serde_json::from_value(json!({"primary_chat_id":null,"planner_focus_id":null})).unwrap();
    let patch = encode_patch(&plan, &patch, &[7; 32]).unwrap();
    assert!(patch.get("primary_chat_id").unwrap().is_null());
    assert!(patch.get("planner_focus_id").unwrap().is_null());
    assert!(patch.get("approval_state").is_none());
}
#[test]
fn team_and_ambiguous_master_wrappers_never_fall_back() {
    let mut raw = raw();
    let duplicate = raw["key_wrappers"][0].clone();
    raw["key_wrappers"].as_array_mut().unwrap().push(duplicate);
    assert!(matches!(decode(raw, &[7; 32]), Err(Error::Forbidden)));
    let mut raw = super::tests::raw();
    raw["key_wrappers"][0]["key_type"] = json!("team");
    assert!(matches!(decode(raw, &[7; 32]), Err(Error::Forbidden)));
}
#[test]
fn evidence_rejects_path_escape_insecure_urls_and_invalid_line_ranges() {
    let flow = |reference| PlanFlow {
        flow_id: "flow".into(),
        title: "Flow".into(),
        actor: None,
        steps: vec![PlanFlowStep {
            step_id: "step".into(),
            text: "Step".into(),
            references: vec![reference],
        }],
        expected_outcome: "Expected".into(),
        linked_task_ids: vec![],
        linked_criterion_ids: vec![],
    };
    for reference in [
        PlanEvidence::Url {
            url: "http://example.org".into(),
        },
        PlanEvidence::File {
            path: "../private".into(),
            start_line: None,
            end_line: None,
        },
        PlanEvidence::File {
            path: "docs/readme.md".into(),
            start_line: Some(5),
            end_line: Some(2),
        },
    ] {
        assert!(validate_flows(&[flow(reference)]).is_err());
    }
    assert!(
        validate_flows(&[flow(PlanEvidence::Url {
            url: "https://example.org/evidence".into()
        })])
        .is_ok()
    );
}
#[tokio::test]
async fn create_resolves_fresh_project_wrapper_before_ciphertext_post() {
    let project_key = [9; 32];
    let wrapped = crypto::encrypt_bytes(&project_key, &[7; 32]).unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let mut requests = vec![];
        for step in 0..2 {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = vec![];
            loop {
                let mut bytes = [0; 4096];
                let n = socket.read(&mut bytes).await.unwrap();
                assert!(n > 0);
                buf.extend_from_slice(&bytes[..n]);
                if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                    let len = head
                        .lines()
                        .find_map(|l| {
                            l.strip_prefix("content-length:")
                                .and_then(|s| s.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if buf.len() >= end + 4 + len {
                        break;
                    }
                }
            }
            let request = String::from_utf8(buf).unwrap();
            let response = if step == 0 {
                json!({"project":{"project_id":PROJECT,"encrypted_project_key":wrapped}})
            } else {
                let value: Value =
                    serde_json::from_str(request.split_once("\r\n\r\n").unwrap().1).unwrap();
                assert!(value.get("title").is_none());
                assert!(value.get("goal").is_none());
                let wrappers = value["key_wrappers"].as_array().unwrap();
                assert_eq!(wrappers.len(), 2);
                let project = wrappers
                    .iter()
                    .find(|w| w["key_type"] == "project")
                    .unwrap();
                assert_eq!(project["hashed_project_id"], hash(PROJECT));
                let key = crypto::decrypt_bytes(
                    project["encrypted_plan_key"].as_str().unwrap(),
                    &project_key,
                )
                .unwrap();
                assert_eq!(key.len(), 32);
                let master = crypto::decrypt_bytes(
                    wrappers[0]["encrypted_plan_key"].as_str().unwrap(),
                    &[7; 32],
                )
                .unwrap();
                assert_eq!(&*key, &*master);
                json!({"plan":value})
            };
            requests.push(request);
            let body = response.to_string();
            socket
                .write_all(
                    format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                        body.len()
                    )
                    .as_bytes(),
                )
                .await
                .unwrap();
        }
        requests
    });
    let mut client = super::super::tasks::tests::client(&api);
    let result = client.plans().create(input()).await.unwrap();
    assert_eq!(result["goal"], "Private accepted goal");
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with(&format!("GET /v1/projects/{PROJECT} ")));
    assert!(requests[1].starts_with("POST /v1/user-plans "));
}
