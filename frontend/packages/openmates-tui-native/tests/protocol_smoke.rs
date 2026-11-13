//! Real product protocol evidence is admitted only by isolated GitHub CI using
//! a disposable core fixture account. No inference or model selection occurs.
use futures_util::{SinkExt, StreamExt};
use openmates_sdk::{
    ApiKey, ClientOptions, OpenMates, SdkCredentials, SdkOptions,
    account::{ApiKeyCreateConfirmation, ApiKeyRevokeConfirmation},
    work::{ProjectCreate, ProjectItemType, ProjectPatch, TaskCreate, TaskPatch},
};
use openmates::{
    client::Client,
    error::Error,
    model::{Mutation, Workspace},
};
use serde_json::json;

fn workflow_fixture() -> Result<Mutation, Error> {
    // Workflow deletion keeps a tombstone that reserves its encrypted slug.
    // Retries share the disposable owner, so each run needs its own slug.
    let slug = openmates_sdk::crypto::normalize_object_slug(&format!(
        "native-fixture-workflow-{}",
        uuid::Uuid::new_v4().simple()
    ))?;
    Ok(Mutation::Create {
        workspace: Workspace::Workflows,
        fields: json!({"title":"Native fixture workflow","slug":slug,"enabled":false,
            "graph":{"version":1,"trigger_node_id":null,"nodes":[],"edges":[]}}),
    })
}

#[test]
fn workflow_fixture_repeated_titles_have_distinct_canonical_payload_slugs() {
    let payload = || {
        let Mutation::Create { workspace, fields } = workflow_fixture().unwrap() else {
            panic!("workflow fixture must construct the creation mutation");
        };
        assert_eq!(workspace, Workspace::Workflows);
        fields
    };
    let mut first = payload();
    let mut second = payload();
    assert_eq!(first["title"], "Native fixture workflow");
    assert_eq!(second["title"], first["title"]);
    assert_ne!(first["slug"], second["slug"]);
    for fields in [&first, &second] {
        let slug = fields["slug"]
            .as_str()
            .expect("explicit slug in actual creation payload");
        assert_eq!(
            openmates_sdk::crypto::normalize_object_slug(slug).unwrap(),
            slug
        );
        let unique = slug.strip_prefix("native-fixture-workflow-").unwrap();
        assert_eq!(uuid::Uuid::parse_str(unique).unwrap().get_version_num(), 4);
    }
    first.as_object_mut().unwrap().remove("slug");
    second.as_object_mut().unwrap().remove("slug");
    assert_eq!(first, second);
    assert_eq!(
        first,
        json!({"title":"Native fixture workflow","enabled":false,
        "graph":{"version":1,"trigger_node_id":null,"nodes":[],"edges":[]}})
    );
}

// Create an owned saved empty chat through the same encrypted WS metadata
// contract used by normal clients. This seeds no AI turn and uses no new API.
async fn seed_saved_rename_chat(client: &mut Client) -> Result<String, Error> {
    use tokio_tungstenite::tungstenite::{Message, client::IntoClientRequest};
    client.validate_session().await?;
    let session = client.session().ok_or(Error::Authentication)?;
    if session.active_team_id.is_some() {
        return Err(Error::Forbidden);
    }
    let id = uuid::Uuid::new_v4().to_string();
    let key = openmates_sdk::crypto::random_key();
    let mut url = url::Url::parse(&session.api_url).map_err(|_| Error::Protocol)?;
    url.set_scheme(if url.scheme() == "https" { "wss" } else { "ws" })
        .map_err(|_| Error::Protocol)?;
    url.set_path("/v1/ws");
    url.query_pairs_mut()
        .append_pair(
            "token",
            session.ws_token.as_deref().ok_or(Error::Authentication)?,
        )
        .append_pair("sessionId", &uuid::Uuid::new_v4().to_string());
    let mut request = url
        .as_str()
        .into_client_request()
        .map_err(|_| Error::Protocol)?;
    let cookie = zeroize::Zeroizing::new(
        session
            .cookies
            .iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join("; "),
    );
    let app_origin = client.application_url();
    for (name, value) in [
        ("Cookie", cookie.as_str()),
        ("Origin", app_origin.as_str()),
        ("X-OpenMates-SDK", "rust"),
    ] {
        request
            .headers_mut()
            .insert(name, value.parse().map_err(|_| Error::Protocol)?);
    }
    let operation = async {
        let (mut ws, _) = tokio_tungstenite::connect_async(request)
            .await
            .map_err(|_| Error::Offline)?;
        for frame in [
            json!({"type":"native_client_lifecycle","payload":{"client_type":"rust","is_foreground":true,"interactive":false}}),
            json!({"type":"encrypted_chat_metadata","payload":{"chat_id":id,"created_at":std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_err(|_|Error::Protocol)?.as_secs(),
                "encrypted_chat_key":openmates_sdk::crypto::encrypt_bytes(&*key,&session.master_key)?,
                "encrypted_title":openmates_sdk::crypto::encrypt_combined("Saved rename fixture",&key)?,
                "encrypted_slug":openmates_sdk::crypto::encrypt_combined("native-authentic-slug-readback",&key)?,
                "slug_lookup_hash":openmates_sdk::crypto::object_slug_lookup_hash("native-authentic-slug-readback",&session.master_key)?,
                "encrypted_icon":openmates_sdk::crypto::encrypt_combined("text",&key)?,
                "encrypted_chat_category":openmates_sdk::crypto::encrypt_combined("general_knowledge",&key)?,
                "versions":{"messages_v":0,"title_v":0,"metadata_v":0}}}),
        ] {
            ws.send(Message::Text(frame.to_string().into()))
                .await
                .map_err(|_| Error::Offline)?;
        }
        while let Some(frame) = ws.next().await {
            match frame.map_err(|_| Error::Offline)? {
                Message::Text(text) => {
                    let frame: serde_json::Value =
                        serde_json::from_str(&text).map_err(|_| Error::Protocol)?;
                    if frame["type"] == "error" {
                        return Err(Error::Protocol);
                    }
                    if frame["type"] == "force_logout" {
                        return Err(Error::Expired);
                    }
                    if frame["type"] == "encrypted_metadata_stored"
                        && frame["payload"]["chat_id"] == id
                    {
                        if frame["payload"]["status"] != "queued_for_storage"
                            || frame["payload"]["versions"]["messages_v"] != 0
                        {
                            return Err(Error::Protocol);
                        }
                        let _ = ws.close(None).await;
                        return Ok(id);
                    }
                }
                Message::Ping(data) => ws
                    .send(Message::Pong(data))
                    .await
                    .map_err(|_| Error::Offline)?,
                Message::Close(_) => return Err(Error::Offline),
                _ => {}
            }
        }
        Err(Error::Offline)
    };
    tokio::time::timeout(std::time::Duration::from_secs(20), operation)
        .await
        .map_err(|_| Error::Offline)?
}

async fn saved_rename_lifecycle(client: &mut Client) {
    let id = stage(
        "seed_saved_rename_chat",
        Some(Workspace::Chats),
        seed_saved_rename_chat(client),
    )
    .await;
    let chat = stage(
        "open_saved_rename_chat",
        Some(Workspace::Chats),
        client.open_chat(&id),
    )
    .await;
    assert!(chat.messages.is_empty());
    // Actual native dispatch and genuine server metadata read; no AI request,
    // selector-derived slug or benchmark ledger is involved. Isolated CI only.
    let parsed=openmates::cli::parse_from(["openmates","chats","show",id.as_str(),"--json"]).expect("parse full read");
    let output=openmates::cli::execute(&parsed.invocation.expect("show invocation"),client,tokio_util::sync::CancellationToken::new()).await.unwrap_or_else(|_| panic!("native full metadata dispatch"));
    assert_eq!(output.exit_code,0);assert!(output.stderr.is_empty());
    let public:serde_json::Value=serde_json::from_str(&output.stdout).expect("public JSON");
    // Original TypeScript chats show --json wraps rich metadata under chat.
    // Keep the real saved-row identity/slug assertions; never flatten or
    // synthesize missing metadata to satisfy this protocol proof.
    let schema: serde_json::Value = serde_json::from_str(include_str!(
        "fixtures/chats-show-json.schema.json"
    )).expect("maintained chats show JSON schema");
    let wrapper = public.as_object().expect("chats show JSON object");
    for field in schema["required"].as_array().expect("wrapper required fields") {
        assert!(wrapper.contains_key(field.as_str().unwrap()), "missing wrapper field");
    }
    let metadata = public["chat"].as_object().expect("rich chat metadata object");
    for field in schema["properties"]["chat"]["required"].as_array().expect("chat required fields") {
        assert!(metadata.contains_key(field.as_str().unwrap()), "missing rich chat field");
    }
    assert_eq!(public["chat"]["id"],id);
    assert_eq!(public["chat"]["slug"],"native-authentic-slug-readback");
    assert_eq!(public["chat"]["title"],"Saved rename fixture");
    assert_eq!(public["chat"]["category"],"general_knowledge");
    assert_eq!(public["messages"],json!([]));
    assert_eq!(public["follow_up_suggestions"],json!([]));
    assert_eq!(public["has_more_before"],false);
    assert!(public.get("id").is_none() && public.get("slug").is_none());
    assert!(public.get("encrypted_slug").is_none());
    assert!(metadata.get("encrypted_slug").is_none());
    let before = client.ciphertext_snapshot()["chats"][&id].clone();
    assert_eq!(before["messages_v"], 0);
    assert!(
        before["encrypted_chat_key"]
            .as_str()
            .is_some_and(|s| !s.is_empty())
    );
    let renamed = stage(
        "rename_saved_chat",
        Some(Workspace::Chats),
        client.mutate(Mutation::Update {
            workspace: Workspace::Chats,
            id: id.clone(),
            fields: json!({"title":"Renamed saved fixture"}),
        }),
    )
    .await
    .expect("rename returned no item");
    assert_eq!(renamed.title, "Renamed saved fixture");
    let accepted = client.ciphertext_snapshot()["chats"][&id].clone();
    for field in ["title_v", "metadata_v"] {
        assert!(accepted[field].as_u64().unwrap() > before[field].as_u64().unwrap_or(0));
    }
    let canonical = stage(
        "read_renamed_chat",
        Some(Workspace::Chats),
        client.open_chat(&id),
    )
    .await;
    assert_eq!(canonical.title, "Renamed saved fixture");
    assert!(canonical.messages.is_empty());
    let after = client.ciphertext_snapshot()["chats"][&id].clone();
    for field in [
        "encrypted_icon",
        "encrypted_category",
        "encrypted_chat_key",
        "messages_v",
    ] {
        assert_eq!(after[field], before[field]);
    }
    for field in ["title_v", "metadata_v", "encrypted_title"] {
        assert_eq!(after[field], accepted[field]);
    }
    let matches = stage(
        "search_renamed_chat",
        Some(Workspace::Chats),
        client.search_chats("ReNaMeD SaVeD FiXtUrE"),
    )
    .await;
    assert!(
        matches
            .iter()
            .any(|row| { row["id"] == id && row["title"] == "Renamed saved fixture" })
    );
    let no_match = format!("NoSuchNativeFixture-{}", uuid::Uuid::new_v4());
    assert!(
        stage(
            "search_no_match",
            Some(Workspace::Chats),
            client.search_chats(&no_match),
        )
        .await
        .is_empty()
    );
    stage(
        "save_existing_chat_draft",
        Some(Workspace::Chats),
        client.save_draft(Some(&id), "Native saved-chat draft fixture"),
    )
    .await;
    let with_draft = client.ciphertext_snapshot()["chats"][&id].clone();
    assert!(
        with_draft["encrypted_draft_md"]
            .as_str()
            .is_some_and(|s| !s.is_empty())
    );
    stage(
        "clear_saved_chat_draft",
        Some(Workspace::Chats),
        client.clear_draft(&id),
    )
    .await;
    let cleared = client.ciphertext_snapshot()["chats"][&id].clone();
    assert!(cleared["draft_v"].as_u64().unwrap() > with_draft["draft_v"].as_u64().unwrap());
    for field in ["encrypted_draft_md", "encrypted_draft_preview"] {
        assert!(cleared[field].is_null() || cleared[field] == "");
    }
    for field in [
        "encrypted_icon",
        "encrypted_category",
        "encrypted_chat_key",
        "encrypted_title",
        "messages_v",
        "title_v",
        "metadata_v",
    ] {
        assert_eq!(cleared[field], with_draft[field]);
    }
    let reopened = stage(
        "reopen_after_draft_clear",
        Some(Workspace::Chats),
        client.open_chat(&id),
    )
    .await;
    assert_eq!(reopened.title, "Renamed saved fixture");
    assert!(reopened.messages.is_empty());
    stage(
        "delete_rename_chat",
        Some(Workspace::Chats),
        client.mutate(Mutation::Delete {
            workspace: Workspace::Chats,
            id,
        }),
    )
    .await;
}

// Diagnostics deliberately contain only static protocol names, workspace labels
// and closed error categories, never credentials, URLs, IDs or server payloads.
fn error_code(error: Error) -> &'static str {
    match error {
        Error::Invalid(_) => "invalid_argument",
        Error::Crypto => "crypto",
        Error::Authentication => "authentication",
        Error::TwoFactorRequired => "two_factor_required",
        Error::SignupRequired => "signup_required",
        Error::Unavailable { .. } => "unavailable",
        Error::Locked => "locked",
        Error::Offline => "offline",
        Error::Forbidden => "forbidden",
        Error::Expired => "expired",
        Error::VerificationRequired => "verification_required",
        Error::Cancelled => "cancelled",
        Error::Io => "io",
        Error::Protocol => "protocol",
        Error::Conflict => "conflict",
    }
}
async fn stage<T>(
    step: &'static str,
    workspace: Option<Workspace>,
    operation: impl std::future::Future<Output = Result<T, Error>>,
) -> T {
    let workspace = workspace.map(Workspace::label).unwrap_or("none");
    eprintln!("native-protocol step={step} workspace={workspace} started");
    let result = operation.await.unwrap_or_else(|error| {
        panic!(
            "native-protocol step={step} workspace={workspace} failed code={}",
            error_code(error)
        )
    });
    eprintln!("native-protocol step={step} workspace={workspace} completed");
    result
}

// Mirrors the existing isolated CI owner-approval fixture. This is not a new
// CLI/SDK device-management surface: only the just-created key and exact new
// device identity can be approved with the disposable owner's current Cookie.
async fn approve_fixture_device(owner: &Client, key_id: &str, device: &str) -> Result<(), Error> {
    let session = owner.session().ok_or(Error::Authentication)?;
    if session.active_team_id.is_some() {
        return Err(Error::Forbidden);
    }
    uuid::Uuid::parse_str(key_id).map_err(|_| Error::Protocol)?;
    let mut cookie = zeroize::Zeroizing::new(String::new());
    for (name, value) in &session.cookies {
        if !cookie.is_empty() {
            cookie.push_str("; ");
        }
        cookie.push_str(name);
        cookie.push('=');
        cookie.push_str(value);
    }
    let http = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(15))
        .user_agent("OpenMatesSDK/0.1 (Rust)")
        .build()
        .map_err(|_| Error::Offline)?;
    for verify in [false, true] {
        let response = http
            .get(format!("{}/v1/settings/api-key-devices", session.api_url))
            .header("Cookie", cookie.as_str())
            .header("Origin", owner.application_url())
            .header("X-OpenMates-SDK", "rust")
            .send()
            .await
            .map_err(|_| Error::Offline)?;
        if !response.status().is_success() {
            return Err(Error::Forbidden);
        }
        let data: serde_json::Value = response.json().await.map_err(|_| Error::Protocol)?;
        let matches = data["devices"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .filter(|row| {
                row["api_key_id"] == key_id
                    && row["access_type"] == "rust"
                    && row["machine_identifier"] == device
            })
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err(Error::Protocol);
        }
        if verify {
            return if matches[0]["approved_at"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
            {
                Ok(())
            } else {
                Err(Error::Forbidden)
            };
        }
        if !matches[0]["approved_at"].is_null() {
            return Err(Error::Conflict);
        }
        let id = uuid::Uuid::parse_str(matches[0]["id"].as_str().ok_or(Error::Protocol)?)
            .map_err(|_| Error::Protocol)?;
        let response = http
            .post(format!(
                "{}/v1/settings/api-key-devices/{id}/approve",
                session.api_url
            ))
            .header("Cookie", cookie.as_str())
            .header("Origin", owner.application_url())
            .header("X-OpenMates-SDK", "rust")
            .json(&json!({}))
            .send()
            .await
            .map_err(|_| Error::Offline)?;
        if !response.status().is_success() {
            return Err(Error::Forbidden);
        }
        let result: serde_json::Value = response.json().await.map_err(|_| Error::Protocol)?;
        if result["success"] != true {
            return Err(Error::Protocol);
        }
    }
    Err(Error::Protocol)
}

async fn api_key_lifecycle(owner: &mut Client, api: &str) {
    let created = stage(
        "create_api_key",
        None,
        owner.account().create_full_access_api_key(
            "Native isolated protocol API key",
            ApiKeyCreateConfirmation::FullAccessUnlimitedNoExpiration,
        ),
    )
    .await;
    let key_id = created.key["id"]
        .as_str()
        .expect("create_api_key missing ID")
        .to_owned();
    let keys = stage(
        "list_api_key_metadata",
        None,
        owner.account().list_api_keys(),
    )
    .await;
    assert!(
        keys.api_keys.iter().any(|key| key.id == key_id
            && key.name == "Native isolated protocol API key"
            && key.full_access),
        "created API key metadata missing"
    );
    let device = uuid::Uuid::new_v4().to_string();
    let options = || SdkOptions {
        api_url: api.into(),
        credentials: SdkCredentials::ApiKey(
            ApiKey::new(&created.api_key).expect("valid newly generated API key"),
        ),
        device_id: device.clone(),
        client_options: ClientOptions {
            app_url: Some(owner.application_url()),
            ..ClientOptions::default()
        },
    };
    let mut sdk = OpenMates::new(options()).expect("isolated API-key SDK options");
    eprintln!("native-protocol step=verify_pending_api_key_device workspace=none started");
    assert!(
        matches!(sdk.sdk_session().await, Err(Error::Forbidden)),
        "new API-key device must require explicit owner approval"
    );
    eprintln!("native-protocol step=verify_pending_api_key_device workspace=none completed");
    stage(
        "owner_approve_exact_fixture_device",
        None,
        approve_fixture_device(owner, &key_id, &device),
    )
    .await;
    stage("admit_approved_api_key_device", None, sdk.sdk_session()).await;
    let task = stage(
        "api_key_create_task",
        Some(Workspace::Tasks),
        sdk.tasks().create(TaskCreate {
            title: "Native API-key fixture task".into(),
            description: "Encrypted isolated API-key task".into(),
            assign: Some("user".into()),
            ..TaskCreate::default()
        }),
    )
    .await;
    let task_id = task["task_id"]
        .as_str()
        .expect("api_key_create_task missing ID");
    let read = stage(
        "api_key_read_task",
        Some(Workspace::Tasks),
        sdk.tasks().show(task_id),
    )
    .await;
    assert!(
        read["title"] == "Native API-key fixture task",
        "API-key task plaintext must decrypt locally"
    );
    let updated = stage(
        "api_key_update_task",
        Some(Workspace::Tasks),
        sdk.tasks().update(
            task_id,
            TaskPatch {
                title: Some("Native API-key fixture task updated".into()),
                ..TaskPatch::default()
            },
        ),
    )
    .await;
    assert!(
        updated["title"] == "Native API-key fixture task updated",
        "API-key task update mismatch"
    );
    stage(
        "api_key_delete_task",
        Some(Workspace::Tasks),
        sdk.tasks().delete(task_id, true),
    )
    .await;
    let project = stage(
        "api_key_create_project",
        Some(Workspace::Projects),
        sdk.projects().create(ProjectCreate {
            name: "Native API-key fixture Project".into(),
            description: "Encrypted isolated API-key Project".into(),
            chat_organization_only: true,
            ..ProjectCreate::default()
        }),
    )
    .await;
    let project_id = project["project_id"]
        .as_str()
        .expect("api_key_create_project missing ID");
    let read = stage(
        "api_key_read_project",
        Some(Workspace::Projects),
        sdk.projects().show(project_id),
    )
    .await;
    assert!(
        read["name"] == "Native API-key fixture Project",
        "API-key Project plaintext must decrypt locally"
    );
    let items = stage(
        "api_key_list_project_items",
        Some(Workspace::Projects),
        sdk.projects().items(project_id),
    )
    .await;
    assert_eq!(
        items,
        json!({"project_id":project_id,"folders":[],"items":[]})
    );
    assert!(matches!(
        sdk.projects()
            .unlink_item(
                project_id,
                ProjectItemType::Chat,
                &uuid::Uuid::new_v4().to_string(),
                true
            )
            .await,
        Err(Error::Unavailable {
            code: "project_item_unlink_unavailable",
            ..
        })
    ));
    let updated = stage(
        "api_key_update_project",
        Some(Workspace::Projects),
        sdk.projects().update(
            project_id,
            ProjectPatch {
                name: Some("Native API-key fixture Project updated".into()),
                ..ProjectPatch::default()
            },
        ),
    )
    .await;
    assert!(
        updated["name"] == "Native API-key fixture Project updated",
        "API-key Project update mismatch"
    );
    stage(
        "api_key_delete_project",
        Some(Workspace::Projects),
        sdk.projects().delete(project_id, true),
    )
    .await;
    // Use a new transport after revocation: an old cached SDK session is not
    // sufficient evidence that the backend rejected the revoked bearer.
    let mut revoked = OpenMates::new(options()).expect("isolated revoked-key SDK options");
    stage(
        "revoke_api_key",
        None,
        owner
            .account()
            .revoke_api_key(&key_id, ApiKeyRevokeConfirmation::Revoke),
    )
    .await;
    eprintln!("native-protocol step=verify_api_key_revocation workspace=none started");
    assert!(
        matches!(revoked.sdk_session().await, Err(Error::Authentication)),
        "revoked API key must return typed HTTP401 authentication failure"
    );
    eprintln!("native-protocol step=verify_api_key_revocation workspace=none completed");
}
#[tokio::test]
#[ignore = "requires an isolated CI disposable account"]
async fn native_protocol_smoke() {
    assert_eq!(
        std::env::var("CI").as_deref(),
        Ok("true"),
        "isolated GitHub CI only"
    );
    let api = std::env::var("RUST_TUI_API_URL").expect("RUST_TUI_API_URL required");
    let url = url::Url::parse(&api).expect("valid isolated API URL");
    assert!(
        url.host_str()
            .is_some_and(|h| matches!(h, "127.0.0.1" | "[::1]")),
        "disposable isolated API must be literal loopback"
    );
    let email = zeroize::Zeroizing::new(
        std::env::var("RUST_TUI_EMAIL").expect("disposable email required"),
    );
    let password = zeroize::Zeroizing::new(
        std::env::var("RUST_TUI_PASSWORD").expect("disposable password required"),
    );
    let otp = std::env::var("RUST_TUI_TOTP_CODE").ok();
    let mut client = Client::new(&api, None).unwrap();
    stage(
        "login_password",
        None,
        client.login_password(&email, &password, otp.as_deref()),
    )
    .await;
    stage("validate_session", None, client.validate_session()).await;
    assert!(client.session().is_some());
    for workspace in Workspace::ALL {
        stage("list_workspace", Some(workspace), client.list(workspace)).await;
    }
    api_key_lifecycle(&mut client, &api).await;
    let draft = stage(
        "save_draft",
        Some(Workspace::Chats),
        client.save_draft(None, "Native Rust protocol fixture draft"),
    )
    .await;
    let chats = stage(
        "list_after_draft",
        Some(Workspace::Chats),
        client.list(Workspace::Chats),
    )
    .await;
    let listed_draft = chats
        .iter()
        .find(|item| item.id == draft)
        .expect("saved draft must be listed");
    assert_eq!(listed_draft.status, "draft");
    assert_eq!(listed_draft.title, "Native Rust protocol fixture draft");
    let opened = stage(
        "open_draft",
        Some(Workspace::Chats),
        client.open_chat(&draft),
    )
    .await;
    assert_eq!(opened.id, draft);
    assert_eq!(opened.title, "Native Rust protocol fixture draft");
    assert!(opened.messages.is_empty());
    let encrypted_snapshot = client.ciphertext_snapshot();
    assert!(
        !encrypted_snapshot
            .to_string()
            .contains("Native Rust protocol fixture draft")
    );
    client
        .restore_ciphertext_snapshot(&encrypted_snapshot)
        .expect("ciphertext draft snapshot must restore");
    let reopened = stage(
        "reopen_draft",
        Some(Workspace::Chats),
        client.open_chat(&draft),
    )
    .await;
    assert_eq!(reopened.id, draft);
    assert_eq!(reopened.title, opened.title);
    assert!(reopened.messages.is_empty());
    stage(
        "delete_draft",
        Some(Workspace::Chats),
        client.mutate(Mutation::Delete {
            workspace: Workspace::Chats,
            id: draft.clone(),
        }),
    )
    .await;
    assert!(
        client
            .cached_chat_items()
            .unwrap()
            .iter()
            .all(|item| item.id != draft)
    );
    assert!(!client.ciphertext_snapshot().to_string().contains(&draft));
    saved_rename_lifecycle(&mut client).await;
    let task=stage("create_task",Some(Workspace::Tasks),client.mutate(Mutation::Create{workspace:Workspace::Tasks,fields:json!({"title":"Native fixture task","description":"Encrypted isolated CI task","priority":2})})).await.expect("create_task returned no item");
    let read = stage(
        "read_task",
        Some(Workspace::Tasks),
        client.detail(Workspace::Tasks, &task.id),
    )
    .await;
    assert_eq!(read.title, "Native fixture task");
    assert_eq!(read.description, "Encrypted isolated CI task");
    let updated = stage(
        "update_task",
        Some(Workspace::Tasks),
        client.mutate(Mutation::Update {
            workspace: Workspace::Tasks,
            id: task.id.clone(),
            fields: json!({"title":"Native fixture task updated","status":"in_progress"}),
        }),
    )
    .await
    .expect("update_task returned no item");
    assert_eq!(updated.status, "in_progress");
    stage(
        "delete_task",
        Some(Workspace::Tasks),
        client.mutate(Mutation::Delete {
            workspace: Workspace::Tasks,
            id: task.id,
        }),
    )
    .await;
    let focus = uuid::Uuid::new_v4().to_string();
    let project=stage("create_project",Some(Workspace::Projects),client.mutate(Mutation::Create{workspace:Workspace::Projects,fields:json!({"title":"Native fixture Project","description":"Encrypted isolated CI Project","write_mode":"always_ask","default_focus_id":focus,"settings":{"default_focus":{"focus_id":focus,"name":"Work on Native fixture Project","instructions":"Use isolated fixture data only.","source":"generated"}}})})).await.expect("create_project returned no item");
    let read = stage(
        "read_project",
        Some(Workspace::Projects),
        client.detail(Workspace::Projects, &project.id),
    )
    .await;
    assert_eq!(read.title, "Native fixture Project");
    let items = stage(
        "list_empty_project_items",
        Some(Workspace::Projects),
        client.projects().items(&project.id),
    )
    .await;
    assert_eq!(
        items,
        json!({"project_id":project.id,"folders":[],"items":[]})
    );
    let missing_target = uuid::Uuid::new_v4().to_string();
    let removed = stage(
        "unlink_absent_project_item",
        Some(Workspace::Projects),
        client
            .projects()
            .unlink_item(&project.id, ProjectItemType::Chat, &missing_target, true),
    )
    .await;
    assert_eq!(
        removed,
        json!({"project_id":project.id,"target_id":missing_target,"deleted":false,"deleted_count":0})
    );
    let updated = stage(
        "update_project",
        Some(Workspace::Projects),
        client.mutate(Mutation::Update {
            workspace: Workspace::Projects,
            id: project.id.clone(),
            fields: json!({"title":"Native fixture Project updated"}),
        }),
    )
    .await
    .expect("update_project returned no item");
    assert_eq!(updated.title, "Native fixture Project updated");
    stage(
        "delete_project",
        Some(Workspace::Projects),
        client.mutate(Mutation::Delete {
            workspace: Workspace::Projects,
            id: project.id,
        }),
    )
    .await;
    let workflow = stage(
        "create_workflow",
        Some(Workspace::Workflows),
        client.mutate(workflow_fixture().expect("valid isolated workflow fixture")),
    )
    .await
    .expect("create_workflow returned no item");
    let read = stage(
        "read_workflow",
        Some(Workspace::Workflows),
        client.detail(Workspace::Workflows, &workflow.id),
    )
    .await;
    assert_eq!(read.title, "Native fixture workflow");
    stage(
        "update_workflow",
        Some(Workspace::Workflows),
        client.mutate(Mutation::Update {
            workspace: Workspace::Workflows,
            id: workflow.id.clone(),
            fields: json!({"title":"Native fixture workflow updated"}),
        }),
    )
    .await;
    stage(
        "delete_workflow",
        Some(Workspace::Workflows),
        client.mutate(Mutation::Delete {
            workspace: Workspace::Workflows,
            id: workflow.id,
        }),
    )
    .await;
    let revoked_session = client.clone_session().unwrap();
    stage("logout", None, client.logout()).await;
    let mut revoked = Client::new(&api, Some(revoked_session)).unwrap();
    eprintln!("native-protocol step=verify_remote_revocation workspace=none started");
    assert!(
        matches!(revoked.validate_session().await, Err(Error::Expired)),
        "Remote logout must revoke the prior session credential"
    );
    eprintln!("native-protocol step=verify_remote_revocation workspace=none completed");
    assert!(client.session().is_none());
    assert!(matches!(
        client.validate_session().await,
        Err(Error::Authentication)
    ));
    println!(
        "Native isolated protocol smoke passed: password/TOTP, cookie refresh, six workspaces, encrypted draft/Task/Project CRUD, workflow CRUD, logout."
    );
}
