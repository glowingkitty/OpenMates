use super::*;
use crate::work::tasks::tests::{client, mock};
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
const TEAM: &str = "ccbbccdd-1111-4111-8111-aabbccddeeff";
fn input() -> ProjectSourceCreate {
    ProjectSourceCreate { source_id:"source / exact".into(),source_type:ProjectSourceType::LocalFolder,
        display_name:"Private folder".into(),metadata:serde_json::from_value(json!({"root":"/private/root","binding_root":"/private/root","legacy_extra":{"preserve":true}})).unwrap(),
        capabilities:vec![ProjectSourceCapability::Read,ProjectSourceCapability::RunCommand],status:ProjectSourceStatus::Offline,
        created_at:10,updated_at:11,last_indexed_at:None }
}
fn project(team: Option<&str>) -> Value {
    let mut row = encode_create(
        &ProjectCreate {
            name: "Project".into(),
            project_id: Some(PROJECT.into()),
            write_mode: Some(ProjectWriteMode::AlwaysAsk),
            ..Default::default()
        },
        &[8; 32],
        &[7; 32],
        team,
    )
    .unwrap();
    if let Some(team) = team {
        row["hashed_team_id"] = json!(hash(team));
    }
    row
}
fn ack(wire: Value, team: Option<&str>) -> Value {
    let mut row = wire;
    row["hashed_project_id"] = json!(hash(PROJECT));
    row["hashed_user_id"] = if team.is_none() {
        json!(hash("owner"))
    } else {
        Value::Null
    };
    row["hashed_team_id"] = team.map(|v| json!(hash(v))).unwrap_or(Value::Null);
    row
}
fn session() -> Value {
    json!({"success":true,"ws_token":"fixture","user":{"id":"owner"}})
}
#[test]
fn legacy_source_fields_encrypt_in_full_and_ack_is_scope_key_bound() {
    let input = input();
    let wire = source_create_wire(&input, &[8; 32]).unwrap();
    assert!(!wire.to_string().contains("/private/root"));
    assert!(!wire.to_string().contains("Private folder"));
    assert_eq!(
        crypto::decrypt_combined(wire["encrypted_metadata"].as_str().unwrap(), &[8; 32]).unwrap(),
        serde_json::to_string(&input.metadata).unwrap()
    );
    let mut raw = ack(wire, None);
    let decoded = source_decode(&raw, PROJECT, "owner", None, &[8; 32]).unwrap();
    assert_eq!(decoded.metadata, input.metadata);
    assert!(source_decode(&raw, PROJECT, "other", None, &[8; 32]).is_err());
    assert!(source_decode(&raw, PROJECT, "owner", Some(TEAM), &[8; 32]).is_err());
    assert!(source_decode(&raw, PROJECT, "owner", None, &[9; 32]).is_err());
    raw["hashed_project_id"] = json!(hash("other"));
    assert!(source_decode(&raw, PROJECT, "owner", None, &[8; 32]).is_err());
}
#[test]
fn source_bounds_and_capability_contract_reject_invalid_inputs() {
    for id in ["".into(), "x".repeat(129), "bad\nsource".into()] {
        let mut i = input();
        i.source_id = id;
        assert!(source_create_wire(&i, &[8; 32]).is_err());
    }
    assert!(source_capabilities(&[], true).is_err());
    assert!(
        source_capabilities(
            &[ProjectSourceCapability::Read, ProjectSourceCapability::Read],
            true
        )
        .is_err()
    );
    assert!(serde_json::from_value::<ProjectSourceCapability>(json!("terminal_admin")).is_err());
    let mut i = input();
    i.metadata
        .insert("oversize".into(), json!("x".repeat(128_000)));
    assert!(source_create_wire(&i, &[8; 32]).is_err());
    assert!(
        serde_json::from_value::<ProjectSourceCapabilitiesPatch>(
            json!({"capabilities":["read"],"updated_at":-1})
        )
        .is_err()
    );
}
#[tokio::test]
async fn capability_patch_mock_preserves_exact_personal_or_team_context_and_ciphertext() {
    for team in [None, Some(TEAM)] {
        let mut normal_input = input();
        normal_input.source_id = "source-normal".into();
        let mut raw = ack(source_create_wire(&normal_input, &[8; 32]).unwrap(), team);
        raw["capabilities"] = json!(["read", "search"]);
        raw["updated_at"] = json!(99);
        let mut responses = vec![session(), json!({"project":project(team)})];
        if team.is_some() {
            responses.push(json!({"team":{"team_id":TEAM,"encrypted_team_key":crypto::encrypt_bytes(&[7;32],&[7;32]).unwrap()}}));
        }
        responses.push(json!({"source":raw}));
        let (api, server) = mock(responses).await;
        let mut client = client(&api);
        let source = client
            .projects()
            .with_filters(ProjectFilters {
                personal: team.is_none(),
                team_id: team.map(str::to_owned),
                ..Default::default()
            })
            .update_source_capabilities(
                PROJECT,
                "source-normal",
                ProjectSourceCapabilitiesPatch {
                    capabilities: vec![
                        ProjectSourceCapability::Read,
                        ProjectSourceCapability::Search,
                    ],
                    updated_at: 99,
                },
            )
            .await
            .unwrap();
        assert_eq!(source.metadata, input().metadata);
        assert_eq!(source.updated_at, 99);
        assert!(client.session().unwrap().active_team_id.is_none());
        let requests = server.await.unwrap();
        let request = requests.last().unwrap();
        assert!(request.starts_with(&format!(
            "PATCH /v1/projects/{PROJECT}/sources/source-normal{} ",
            team.map(|t| format!("?team_id={t}")).unwrap_or_default()
        )));
        let body: Value = serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap();
        assert_eq!(
            body,
            json!({"capabilities":["read","search"],"updated_at":99})
        );
    }
}
#[tokio::test]
async fn create_rejects_unacknowledged_ciphertext_and_foreign_source_identity() {
    let raw = ack(source_create_wire(&input(), &[8; 32]).unwrap(), None);
    let (api, server) = mock(vec![
        session(),
        json!({"project":project(None)}),
        json!({"source":raw}),
    ])
    .await;
    let mut client = client(&api);
    // Independently encrypted same plaintext is not the exact acknowledged write.
    assert!(matches!(
        client.projects().create_source(PROJECT, input()).await,
        Err(Error::Forbidden)
    ));
    let requests = server.await.unwrap();
    let body: Value =
        serde_json::from_str(requests.last().unwrap().split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(
        crypto::decrypt_combined(body["encrypted_display_name"].as_str().unwrap(), &[8; 32])
            .unwrap(),
        "Private folder"
    );
    assert!(!body.to_string().contains("/private/root"));
}
#[tokio::test]
async fn api_key_source_authoring_is_explicitly_unavailable_without_transport() {
    let mut sdk = OpenMates::new(crate::SdkOptions {
        api_url: "http://127.0.0.1:1".into(),
        credentials: crate::SdkCredentials::ApiKey(
            crate::ApiKey::new(&format!("sk-api-{}.{}", "b".repeat(32), "c".repeat(32))).unwrap(),
        ),
        device_id: "fixture".into(),
        client_options: Default::default(),
    })
    .unwrap();
    for error in [
        sdk.projects()
            .create_source(PROJECT, input())
            .await
            .err()
            .unwrap(),
        sdk.projects()
            .update_source_capabilities(
                PROJECT,
                "source",
                ProjectSourceCapabilitiesPatch {
                    capabilities: vec![ProjectSourceCapability::Read],
                    updated_at: 10,
                },
            )
            .await
            .err()
            .unwrap(),
    ] {
        assert!(matches!(
            error,
            Error::Unavailable {
                code: "project_source_authoring_unavailable",
                reason: "PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION"
            }
        ));
    }
}

#[tokio::test]
async fn create_mock_ack_echoes_exact_encrypted_write_without_plaintext() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        for response in [
            Some(session()),
            Some(json!({"project":project(None)})),
            None,
        ] {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = vec![];
            let (end, size) = loop {
                let mut chunk = [0; 4096];
                let n = socket.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                buf.extend_from_slice(&chunk[..n]);
                if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                    let size = head
                        .lines()
                        .find_map(|l| {
                            l.strip_prefix("content-length:")
                                .and_then(|v| v.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if buf.len() >= end + 4 + size {
                        break (end, size);
                    }
                }
            };
            let response = match response {
                Some(value) => value,
                None => {
                    assert!(
                        String::from_utf8_lossy(&buf)
                            .starts_with(&format!("POST /v1/projects/{PROJECT}/sources "))
                    );
                    let wire: Value =
                        serde_json::from_slice(&buf[end + 4..end + 4 + size]).unwrap();
                    assert!(!wire.to_string().contains("Private folder"));
                    assert!(!wire.to_string().contains("/private/root"));
                    json!({"source":ack(wire,None)})
                }
            };
            let body = response.to_string();
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
    });
    let mut client = client(&api);
    let source = client
        .projects()
        .create_source(PROJECT, input())
        .await
        .unwrap();
    assert_eq!(source.metadata, input().metadata);
    assert_eq!(source.display_name, "Private folder");
    server.await.unwrap();
}
#[test]
fn legacy_create_allows_empty_or_duplicate_capabilities_while_patch_does_not() {
    assert!(source_capabilities(&[], false).is_ok());
    assert!(
        source_capabilities(
            &[ProjectSourceCapability::Read, ProjectSourceCapability::Read],
            false
        )
        .is_ok()
    );
    assert!(source_capabilities(&[ProjectSourceCapability::Read; 9], false).is_err());
}

#[test]
fn patch_route_uses_reqwest_url_normalization_without_aliasing_source_ids() {
    for id in ["/", "a/b", ".", ".."] {
        assert!(source_patch_segment(id).is_err());
    }
    for (id, encoded) in [
        ("source-normal", "source-normal"),
        ("%2F", "%252F"),
        ("%2e%2e", "%252e%252e"),
        ("a?#&=;", "a%3F%23%26%3D%3B"),
        ("a b", "a%20b"),
        ("a\\b", "a%5Cb"),
    ] {
        let segment = source_patch_segment(id).unwrap();
        assert_eq!(segment, encoded);
        let url = reqwest::Url::parse(&format!(
            "https://example.test/v1/projects/{PROJECT}/sources/{segment}?team_id={TEAM}"
        ))
        .unwrap();
        assert_eq!(
            url.path(),
            format!("/v1/projects/{PROJECT}/sources/{encoded}")
        );
        assert_eq!(url.query(), Some(format!("team_id={TEAM}").as_str()));
    }
}
#[tokio::test]
async fn patch_unrepresentable_legacy_ids_refuse_before_session_transport() {
    let mut client = client("http://127.0.0.1:1");
    for id in ["a/b", ".", ".."] {
        assert!(matches!(
            client
                .projects()
                .update_source_capabilities(
                    PROJECT,
                    id,
                    ProjectSourceCapabilitiesPatch {
                        capabilities: vec![ProjectSourceCapability::Read],
                        updated_at: 1
                    }
                )
                .await,
            Err(Error::Invalid(_))
        ));
        let mut create = input();
        create.source_id = id.into();
        assert!(source_create_wire(&create, &[8; 32]).is_ok());
    }
}

async fn source_status_peer(
    responses: Vec<(u16, Value)>,
    cancel_after_accepted: Option<tokio_util::sync::CancellationToken>,
) -> (String, tokio::task::JoinHandle<Vec<String>>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        let mut requests = vec![];
        let count = responses.len();
        for (index, (status, body)) in responses.into_iter().enumerate() {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = vec![];
            loop {
                let mut chunk = [0; 4096];
                let n = socket.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                buf.extend_from_slice(&chunk[..n]);
                if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                    let size = head
                        .lines()
                        .find_map(|l| {
                            l.strip_prefix("content-length:")
                                .and_then(|v| v.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if buf.len() >= end + 4 + size {
                        break;
                    }
                }
            }
            requests.push(String::from_utf8(buf).unwrap());
            // Simulate server acceptance before caller cancellation. The reply's
            // rotated credentials still need adoption even though ACK is hidden.
            if index + 1 == count
                && let Some(cancel) = &cancel_after_accepted
            {
                cancel.cancel();
            }
            let body = body.to_string();
            socket.write_all(format!("HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\nSet-Cookie: fixture_rotation=retained-{index}; Path=/\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    (api, handle)
}
#[tokio::test]
async fn source_backend_permission_and_write_mode_errors_propagate_without_retry() {
    for (status, detail, expected) in [
        (403, "TEAM_PERMISSION_DENIED", Error::Forbidden),
        (409, "PROJECT_WRITE_MODE_REQUIRED", Error::Conflict),
    ] {
        let (api, server) = source_status_peer(
            vec![
                (200, session()),
                (200, json!({"project":project(None)})),
                (status, json!({"detail":detail})),
            ],
            None,
        )
        .await;
        let mut client = client(&api);
        assert!(
            matches!(client.projects().create_source(PROJECT,input()).await,Err(error) if error==expected)
        );
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 3);
        assert!(requests[2].starts_with(&format!("POST /v1/projects/{PROJECT}/sources ")));
    }
}
#[tokio::test]
async fn source_cancellation_after_accepted_mutation_retains_rotated_credentials() {
    let cancel = tokio_util::sync::CancellationToken::new();
    let (api, server) = source_status_peer(
        vec![
            (200, session()),
            (200, json!({"project":project(None)})),
            (200, json!({"source":{}})),
        ],
        Some(cancel.clone()),
    )
    .await;
    let mut client = client(&api);
    let before = client.credential_snapshot().unwrap().revision;
    let mut projects = client.projects();
    projects.operation_cancel = cancel;
    assert!(matches!(
        projects.create_source(PROJECT, input()).await,
        Err(Error::Cancelled)
    ));
    drop(projects);
    let snapshot = client.credential_snapshot().unwrap();
    assert!(snapshot.revision > before);
    assert_eq!(
        snapshot
            .session
            .cookies
            .get("fixture_rotation")
            .map(String::as_str),
        Some("retained-2")
    );
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 3);
}
#[tokio::test]
async fn source_expiry_and_wrong_team_key_epoch_fail_without_source_write() {
    let api = "http://127.0.0.1:1";
    let mut expired = client(api);
    let mut expired_session = expired.clone_session().unwrap();
    expired_session.paired_session_expires_at = Some(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64
            + 1000,
    );
    expired.reset(api, Some(expired_session)).unwrap();
    tokio::time::sleep(std::time::Duration::from_millis(1100)).await;
    assert!(matches!(
        expired.projects().create_source(PROJECT, input()).await,
        Err(Error::Expired)
    ));
    let mut raw = project(Some(TEAM));
    raw["key_wrappers"][0]["team_key_epoch"] = json!(2);
    let (api,server)=mock(vec![session(),json!({"project":raw}),json!({"team":{"team_id":TEAM,"encrypted_team_key":crypto::encrypt_bytes(&[7;32],&[7;32]).unwrap()}})]).await;
    let mut client = client(&api);
    assert!(matches!(
        client
            .projects()
            .with_filters(ProjectFilters {
                team_id: Some(TEAM.into()),
                ..Default::default()
            })
            .create_source(PROJECT, input())
            .await,
        Err(Error::Forbidden)
    ));
    assert!(
        server
            .await
            .unwrap()
            .iter()
            .all(|request| !request.starts_with("POST /v1/projects/"))
    );
}

#[tokio::test]
async fn missing_or_nonobject_source_ack_is_protocol_for_both_mutations() {
    for response in [
        json!({}),
        json!({"source":null}),
        json!({"source":"invalid"}),
        json!({"source":[]}),
    ] {
        for patch in [false, true] {
            let (api, server) = mock(vec![
                session(),
                json!({"project":project(None)}),
                response.clone(),
            ])
            .await;
            let mut client = client(&api);
            let result = if patch {
                client
                    .projects()
                    .update_source_capabilities(
                        PROJECT,
                        "source-normal",
                        ProjectSourceCapabilitiesPatch {
                            capabilities: vec![ProjectSourceCapability::Read],
                            updated_at: 1,
                        },
                    )
                    .await
            } else {
                client.projects().create_source(PROJECT, input()).await
            };
            assert!(matches!(result, Err(Error::Protocol)));
            assert_eq!(server.await.unwrap().len(), 3);
        }
    }
}
