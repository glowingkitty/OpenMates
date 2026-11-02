// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use crate::work::tasks::tests::{client, mock};
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
const TEAM: &str = "ccbbccdd-1111-4111-8111-aabbccddeeff";
fn project(team: Option<&str>) -> Value {
    let mut raw = encode_create(
        &ProjectCreate {
            project_id: Some(PROJECT.into()),
            name: "Private Project".into(),
            write_mode: Some(ProjectWriteMode::AlwaysAsk),
            ..Default::default()
        },
        &[8; 32],
        if team.is_some() { &[9; 32] } else { &[7; 32] },
        team,
    )
    .unwrap();
    raw["hashed_user_id"] = if team.is_some() {
        Value::Null
    } else {
        json!(hash("owner"))
    };
    raw["hashed_team_id"] = team.map(hash).map(Value::String).unwrap_or(Value::Null);
    raw["mutation_permissions"] = json!({"manage_any_items":true,"manage_own_items":true});
    raw
}
fn detail(team: Option<&str>) -> Value {
    let scope = json!({"hashed_project_id":hash(PROJECT),"hashed_user_id":if team.is_some(){Value::Null}else{json!(hash("owner"))},"hashed_team_id":team.map(hash)});
    let mut folder = scope.clone();
    folder["folder_id"] = json!("folder-id");
    folder["encrypted_name"] = json!(crypto::encrypt_combined("Private folder", &[8; 32]).unwrap());
    folder["hashed_parent_folder_id"] = json!(hash("parent"));
    let mut item = scope;
    item["project_item_id"] = json!("link-id");
    item["item_type"] = json!("chat");
    item["target_id_encrypted"] =
        json!(crypto::encrypt_combined("exact-target", &[8; 32]).unwrap());
    item["target_id_hash"] = json!(hash("exact-target"));
    item["encrypted_display_name"] =
        json!(crypto::encrypt_combined("Private chat", &[8; 32]).unwrap());
    item["encrypted_note"] = json!("not exposed");
    item["ownership_label"] = json!("Attached by you");
    item["position"] = json!(4);
    json!({"project":project(team),"folders":[folder],"items":[item]})
}
fn resolved(raw: Value) -> ResolvedProject {
    decode(raw, zeroize::Zeroizing::new([8; 32])).unwrap()
}
#[test]
fn projection_decrypts_only_legacy_fields_and_preserves_identifiers_parent_hash_and_order() {
    let raw = detail(None);
    let project = resolved(raw["project"].clone());
    let result = decode_items(&raw, &project, None).unwrap();
    assert_eq!(
        result,
        json!({"project_id":PROJECT,"folders":[{"folder_id":"folder-id","parent_folder_id":hash("parent"),"name":"Private folder","position":0}],"items":[{"project_item_id":"link-id","type":"chat","target_id":"exact-target","display_name":"Private chat","ownership_label":"Attached by you","position":4}]})
    );
    assert!(!result.to_string().contains("encrypted_note"));
    let mut absent = raw.clone();
    absent["folders"][0]
        .as_object_mut()
        .unwrap()
        .remove("hashed_parent_folder_id");
    absent["items"][0]
        .as_object_mut()
        .unwrap()
        .remove("ownership_label");
    absent["items"][0]["encrypted_display_name"] = Value::Null;
    let result = decode_items(&absent, &project, None).unwrap();
    assert!(result["folders"][0]["parent_folder_id"].is_null());
    assert!(result["items"][0]["ownership_label"].is_null());
    assert_eq!(result["items"][0]["display_name"], "");
}
#[test]
fn cross_project_owner_team_target_and_ciphertext_never_release_plaintext() {
    let raw = detail(None);
    let project = resolved(raw["project"].clone());
    for (field, bad) in [
        ("hashed_project_id", json!(hash("other"))),
        ("hashed_user_id", json!(hash("other"))),
        ("hashed_team_id", json!(hash(TEAM))),
        ("target_id_hash", json!(hash("other"))),
        (
            "target_id_encrypted",
            json!(crypto::encrypt_combined("exact-target", &[6; 32]).unwrap()),
        ),
    ] {
        let mut badrow = raw.clone();
        badrow["items"][0][field] = bad;
        assert!(decode_items(&badrow, &project, None).is_err(), "{field}");
    }
    let mut duplicate = raw.clone();
    duplicate["items"]
        .as_array_mut()
        .unwrap()
        .push(raw["items"][0].clone());
    assert!(matches!(
        decode_items(&duplicate, &project, None),
        Err(Error::Protocol)
    ));
    let team = detail(Some(TEAM));
    let project = resolved(team["project"].clone());
    assert!(decode_items(&team, &project, Some(TEAM)).is_ok());
    assert!(decode_items(&team, &project, Some("other-team")).is_err());
    assert!(decode_items(&team, &project, None).is_err());
}
#[tokio::test]
async fn cookie_uuid_and_archived_slug_resolve_then_use_canonical_scoped_detail() {
    let data = detail(None);
    let (api, server) = mock(vec![data.clone()]).await;
    let mut c = client(&api);
    assert_eq!(
        c.projects().items(PROJECT).await.unwrap()["items"][0]["target_id"],
        "exact-target"
    );
    assert!(server.await.unwrap()[0].starts_with(&format!("GET /v1/projects/{PROJECT} ")));
    let (api, server) = mock(vec![json!({"projects":[data["project"]]}), data]).await;
    let mut c = client(&api);
    assert_eq!(
        c.projects().items("private-project").await.unwrap()["project_id"],
        PROJECT
    );
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("GET /v1/projects?include_archived=true "));
    assert_eq!(requests.len(), 2);
}
#[tokio::test]
async fn explicit_team_detail_uses_team_wrapper_without_changing_ambient_personal_context() {
    let data = detail(Some(TEAM));
    let wrapped = crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap();
    let (api, server) = mock(vec![
        data,
        json!({"team":{"team_id":TEAM,"encrypted_team_key":wrapped}}),
    ])
    .await;
    let mut c = client(&api);
    assert_eq!(
        c.projects()
            .with_filters(ProjectFilters {
                team_id: Some(TEAM.into()),
                ..Default::default()
            })
            .items(PROJECT)
            .await
            .unwrap()["items"][0]["display_name"],
        "Private chat"
    );
    assert!(c.session().unwrap().active_team_id.is_none());
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with(&format!("GET /v1/projects/{PROJECT}?team_id={TEAM} ")));
    assert!(requests[1].starts_with(&format!("GET /v1/teams/{TEAM} ")));
}
#[tokio::test]
async fn unlink_only_deletes_links_and_accepts_exact_idempotent_receipts_without_retry() {
    for (deleted, count) in [(true, 2), (false, 0)] {
        let (api, server) = mock(vec![
            json!({"project":project(None)}),
            json!({"deleted":deleted,"deleted_count":count}),
        ])
        .await;
        let mut c = client(&api);
        let value = c
            .projects()
            .unlink_item(PROJECT, ProjectItemType::Embed, "embed/界?&", true)
            .await
            .unwrap();
        assert_eq!(
            value,
            json!({"project_id":PROJECT,"target_id":"embed/界?&","deleted":deleted,"deleted_count":count})
        );
        let req = server.await.unwrap();
        assert_eq!(req.len(), 2);
        assert!(req[1].starts_with(&format!(
            "DELETE /v1/projects/{PROJECT}/items?item_type=embed&target_id=embed%2F%E7%95%8C%3F%26 "
        )));
        assert!(!req[1].contains("/v1/embeds"));
    }
    for receipt in [
        json!({}),
        json!({"deleted":true}),
        json!({"deleted":true,"deleted_count":0}),
        json!({"deleted":false,"deleted_count":1}),
        json!({"deleted":true,"deleted_count":-1}),
    ] {
        let (api, server) = mock(vec![json!({"project":project(None)}), receipt]).await;
        let mut c = client(&api);
        assert!(matches!(
            c.projects()
                .unlink_item(PROJECT, ProjectItemType::Chat, "exact-target", true)
                .await,
            Err(Error::Protocol)
        ));
        assert_eq!(server.await.unwrap().len(), 2);
    }
}
#[tokio::test]
async fn viewer_unknown_permissions_confirmation_and_cancel_are_not_mutation_authority() {
    for permissions in [
        json!({"manage_any_items":false,"manage_own_items":false}),
        Value::Null,
    ] {
        let mut project = project(None);
        project["mutation_permissions"] = permissions;
        let (api, server) = mock(vec![json!({"project":project})]).await;
        let mut c = client(&api);
        assert!(matches!(
            c.projects()
                .unlink_item(PROJECT, ProjectItemType::Chat, "target", true)
                .await,
            Err(Error::Forbidden)
        ));
        assert_eq!(server.await.unwrap().len(), 1);
    }
    let mut c = client("http://127.0.0.1:1");
    assert!(matches!(
        c.projects()
            .unlink_item(PROJECT, ProjectItemType::Chat, "target", false)
            .await,
        Err(Error::Invalid(_))
    ));
    let cancel = tokio_util::sync::CancellationToken::new();
    c.set_operation_cancel(cancel.clone());
    cancel.cancel();
    assert!(matches!(
        c.projects().items(PROJECT).await,
        Err(Error::Cancelled)
    ));
    assert!(matches!(
        c.projects()
            .unlink_item(PROJECT, ProjectItemType::Chat, "target", true)
            .await,
        Err(Error::Cancelled)
    ));
}
#[tokio::test]
async fn api_key_reads_canonical_detail_with_local_setup_secret_but_unlink_never_dispatches() {
    use base64::{Engine, engine::general_purpose::STANDARD};
    let salt = [5; 16];
    let iv = [4; 12];
    let secret = "s".repeat(32);
    let mut key = zeroize::Zeroizing::new([0; 32]);
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>(secret.as_bytes(), &salt, 100_000, &mut *key);
    // A limited Project grant unwraps this Project key, never the account master.
    let wrapped = crypto::encrypt_aead(&[8; 32], &key, &iv, &[]).unwrap();
    let grant = json!({"resource_type":"project","resource_id":PROJECT,"salt":STANDARD.encode(salt),"key_iv":STANDARD.encode(iv),"encrypted_key":STANDARD.encode(wrapped)});
    let (api, server) = mock(vec![detail(None), json!({"resource_key_grants":[grant]})]).await;
    let mut sdk = OpenMates::new(crate::SdkOptions {
        api_url: api,
        credentials: crate::SdkCredentials::ApiKey(
            crate::ApiKey::new(&format!("sk-api-{}.{}", "b".repeat(32), secret)).unwrap(),
        ),
        device_id: "fixture".into(),
        client_options: Default::default(),
    })
    .unwrap();
    assert_eq!(
        sdk.projects().items(PROJECT).await.unwrap()["items"][0]["target_id"],
        "exact-target"
    );
    assert!(matches!(
        sdk.projects()
            .unlink_item(PROJECT, ProjectItemType::Chat, "target", true)
            .await,
        Err(Error::Unavailable { .. })
    ));
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 2);
    assert!(requests[0].starts_with(&format!("GET /v1/projects/{PROJECT} ")));
    for request in requests {
        assert!(
            request
                .to_ascii_lowercase()
                .contains("authorization: bearer sk-api-")
        );
        assert!(!request.contains(&secret));
        assert!(!request.to_ascii_lowercase().contains("cookie:"));
    }
}
#[tokio::test]
async fn cancelled_delayed_detail_retains_rotated_cookie_without_publishing_plaintext() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let (headers_tx, headers_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut data = vec![];
        loop {
            let mut chunk = [0; 4096];
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            data.extend_from_slice(&chunk[..n]);
            if data.windows(4).any(|w| w == b"\r\n\r\n") {
                break;
            }
        }
        let body = detail(None).to_string();
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nSet-Cookie: auth_refresh_token=rotated-fixture; HttpOnly\r\nConnection: close\r\n\r\n",body.len()).as_bytes()).await.unwrap();
        headers_tx.send(()).unwrap();
        release_rx.await.unwrap();
        stream.write_all(body.as_bytes()).await.unwrap();
    });
    let mut c = client(&api);
    let before = c.ciphertext_snapshot();
    let cancel = tokio_util::sync::CancellationToken::new();
    c.set_operation_cancel(cancel.clone());
    let operation = async { c.projects().items(PROJECT).await };
    let (result, ()) = tokio::join!(operation, async {
        headers_rx.await.unwrap();
        cancel.cancel();
        release_tx.send(()).unwrap();
    });
    assert!(matches!(result, Err(Error::Cancelled)));
    assert_eq!(
        c.session()
            .unwrap()
            .cookies
            .get("auth_refresh_token")
            .map(String::as_str),
        Some("rotated-fixture")
    );
    assert_eq!(c.ciphertext_snapshot(), before);
    server.await.unwrap();
}

#[tokio::test]
async fn unlink_preserves_authoritative_denials_and_uncertain_or_cancelled_admission_receipts() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    for (status, truncated, cancel_after_submit) in [
        (403, false, false),
        (409, false, false),
        (200, true, false),
        (200, false, true),
    ] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let cancel = tokio_util::sync::CancellationToken::new();
        let peer_cancel = cancel.clone();
        let server = tokio::spawn(async move {
            let mut requests = vec![];
            for index in 0..2 {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut data = vec![];
                loop {
                    let mut buf = [0; 4096];
                    let n = stream.read(&mut buf).await.unwrap();
                    assert!(n > 0);
                    data.extend_from_slice(&buf[..n]);
                    if data.windows(4).any(|w| w == b"\r\n\r\n") {
                        break;
                    }
                }
                requests.push(String::from_utf8(data).unwrap());
                let body = if index == 0 {
                    json!({"project":project(None)}).to_string()
                } else if status == 200 {
                    json!({"deleted":true,"deleted_count":1}).to_string()
                } else {
                    json!({"detail":"private backend reason"}).to_string()
                };
                if index == 1 && cancel_after_submit {
                    peer_cancel.cancel();
                }
                let length = body.len() + if index == 1 && truncated { 100 } else { 0 };
                let code = if index == 0 { 200 } else { status };
                stream.write_all(format!("HTTP/1.1 {code} Fixture\r\nContent-Type: application/json\r\nContent-Length: {length}\r\nConnection: close\r\n\r\n{body}").as_bytes()).await.unwrap();
            }
            requests
        });
        let mut c = client(&api);
        c.set_operation_cancel(cancel.clone());
        let result = c
            .projects()
            .unlink_item(PROJECT, ProjectItemType::Chat, "target", true)
            .await;
        match (status, truncated) {
            (403, _) => assert!(matches!(result, Err(Error::Forbidden))),
            (409, _) => assert!(matches!(result, Err(Error::Conflict))),
            (_, true) => assert!(matches!(result, Err(Error::Offline))),
            _ => {
                assert!(cancel.is_cancelled());
                assert_eq!(result.unwrap()["deleted_count"], 1);
            }
        }
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 2);
        assert!(requests[1].starts_with(&format!(
            "DELETE /v1/projects/{PROJECT}/items?item_type=chat&target_id=target "
        )));
    }
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn link_item_encrypts_target_name_note_and_metadata_with_the_project_key() {
    let (api, server) = mock(vec![
        json!({"project":project(None)}),
        json!({"item":{"project_item_id":"server-link"}}),
    ])
    .await;
    let mut c = client(&api);
    let value = c
        .projects()
        .link_item(
            PROJECT,
            ProjectLink {
                item_type: ProjectItemType::Chat,
                target_id: "exact-chat".into(),
                display_name: "Private chat title".into(),
                folder_id: Some("folder-id".into()),
                metadata: json!({"storage":"save_only_in_openmates","source":"cli_add_to_project"}),
            },
        )
        .await
        .unwrap();
    assert_eq!(
        value,
        json!({"project_id":PROJECT,"item":{"project_item_id":"server-link"}})
    );
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 2);
    assert!(requests[1].starts_with(&format!("POST /v1/projects/{PROJECT}/items ")));
    assert!(!requests[1].contains("Private chat title"));
    let body: Value = serde_json::from_str(requests[1].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body["item_type"], "chat");
    assert_eq!(body["target_id"], "exact-chat");
    assert_eq!(body["folder_id"], "folder-id");
    assert!(uuid::Uuid::parse_str(body["project_item_id"].as_str().unwrap()).is_ok());
    let open =
        |field: &str| crypto::decrypt_combined(body[field].as_str().unwrap(), &[8; 32]).unwrap();
    assert_eq!(open("target_id_encrypted"), "exact-chat");
    assert_eq!(open("encrypted_display_name"), "Private chat title");
    assert_eq!(open("encrypted_note"), "");
    assert_eq!(
        serde_json::from_str::<Value>(&open("encrypted_metadata")).unwrap(),
        json!({"storage":"save_only_in_openmates","source":"cli_add_to_project"})
    );
    assert_eq!(body["created_at"], body["position"]);
    // Invalid input and malformed receipts never become implicit successes.
    let mut c = client("http://127.0.0.1:1");
    let invalid = ProjectLink {
        item_type: ProjectItemType::Embed,
        target_id: String::new(),
        display_name: String::new(),
        folder_id: None,
        metadata: json!({}),
    };
    assert!(matches!(
        c.projects().link_item(PROJECT, invalid).await,
        Err(Error::Invalid(_))
    ));
    let (api, server) = mock(vec![json!({"project":project(None)}), json!({"ok":true})]).await;
    let mut c = client(&api);
    let link = ProjectLink {
        item_type: ProjectItemType::Embed,
        target_id: "embed".into(),
        display_name: "Embed".into(),
        folder_id: None,
        metadata: json!({}),
    };
    assert!(matches!(
        c.projects().link_item(PROJECT, link).await,
        Err(Error::Protocol)
    ));
    assert_eq!(server.await.unwrap().len(), 2);
}
