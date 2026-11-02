use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
async fn bounded<T>(future: impl std::future::Future<Output = T>) -> T {
    tokio::time::timeout(std::time::Duration::from_secs(2), future)
        .await
        .expect("bounded mock operation")
}
async fn suite(future: impl std::future::Future<Output = ()>) {
    tokio::time::timeout(std::time::Duration::from_secs(10), future)
        .await
        .expect("bounded ask suite");
}
struct Peer(tokio::task::JoinHandle<()>);
impl Drop for Peer {
    fn drop(&mut self) {
        self.0.abort();
    }
}
impl Peer {
    async fn join(mut self) {
        bounded(&mut self.0).await.expect("mock peer assertions");
    }
}
const FLOW: &str = "11111111-1111-4111-8111-111111111111";
fn invocation(text: &str) -> Invocation {
    Invocation {
        path: vec!["workflows".into(), "ask".into()],
        positionals: vec![text.into()],
        flags: BTreeMap::from([("json".into(), json!(true))]),
    }
}
fn client(api: &str) -> Client {
    Client::new(
        api,
        Some(crate::storage::Session {
            api_url: api.into(),
            session_id: "fixture".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([1; 32]),
            hashed_email: "fixture-owner".into(),
            user_email_salt: "fixture".into(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.slugs.local-resolution-id-transport
#[test]
fn exact_syntax_preserves_quoted_mentions_action_priority_and_rename() {
    assert_eq!(
        target("pause @workflow:\"Daily status\"!"),
        Some("Daily status".into())
    );
    assert_eq!(
        target("rename @Workflow:'Daily status' to 'Evening status'."),
        Some("Daily status".into())
    );
    assert!(matches!(
        action("delete and disable @workflow:daily"),
        Some(WorkflowAction::Delete)
    ));
    assert!(matches!(
        action("switch off @workflow:daily"),
        Some(WorkflowAction::Disable)
    ));
    assert!(matches!(
        action("resume @workflow:daily"),
        Some(WorkflowAction::Enable)
    ));
    assert_eq!(
        rename("rename @workflow:daily to Evening status."),
        Some("Evening status".into())
    );
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.slugs.local-resolution-id-transport
#[test]
fn selector_resolution_keeps_priority_and_ambiguity_local() {
    let rows = vec![json!({"id":FLOW,"slug":"daily","title":"Daily Status"})];
    for target in [FLOW, "11111111", "daily", "  DAILY   STATUS  "] {
        assert_eq!(lookup(&rows, target).ok().unwrap(), Some(FLOW.into()));
    }
    let mut ambiguous = rows.clone();
    ambiguous.push(json!({"id":"11111111-2222-4222-8222-222222222222","title":"Other"}));
    assert_eq!(
        lookup(&ambiguous, "11111111").err().unwrap().code(),
        "ambiguous_workflow"
    );
    assert!(lookup(&rows, "missing").ok().unwrap().is_none());
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[test]
fn natural_ask_is_not_silently_replaced_with_explicit_create() {
    let mut i = invocation("alert me if it rains");
    let instruction = input(&i).ok().unwrap();
    assert!(
        create_options(&i, &instruction)
            .ok()
            .unwrap()
            .create
            .is_none()
    );
    i.flags
        .insert("description".into(), json!("Explicit description"));
    let create = create_options(&i, &instruction)
        .ok()
        .unwrap()
        .create
        .unwrap();
    assert_eq!(create.title, instruction);
    assert_eq!(create.source.as_deref(), Some("cli_ask"));
    assert!(create.created_by_assistant);
    assert!(!create.enabled);
    assert_eq!(create.graph.version, 1);
    assert_eq!(
        create.graph.trigger_node_id.as_deref(),
        Some("manual-trigger")
    );
    i.flags.insert("text".into(), json!("  text flag wins  "));
    assert_eq!(input(&i).ok().unwrap(), "text flag wins");
}
async fn request(socket: &mut tokio::net::TcpStream) -> (String, Value) {
    let mut bytes = vec![];
    let mut part = [0; 4096];
    let (end, length) = loop {
        let count = bounded(socket.read(&mut part)).await.unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&part[..count]);
        assert!(bytes.len() < 65536);
        if let Some(end) = bytes.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
            let headers = std::str::from_utf8(&bytes[..end]).unwrap();
            let length = headers
                .lines()
                .filter_map(|line| line.split_once(':'))
                .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
                .map(|(_, value)| value.trim().parse::<usize>().unwrap())
                .unwrap_or(0);
            break (end + 4, length);
        }
    };
    while bytes.len() < end + length {
        let count = bounded(socket.read(&mut part)).await.unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&part[..count]);
    }
    let path = std::str::from_utf8(&bytes[..end])
        .unwrap()
        .lines()
        .next()
        .unwrap()
        .to_owned();
    let body = if length == 0 {
        Value::Null
    } else {
        serde_json::from_slice(&bytes[end..end + length]).unwrap()
    };
    (path, body)
}
async fn respond(socket: &mut tokio::net::TcpStream, value: Value) {
    let body = value.to_string();
    bounded(socket.write_all(format!("HTTP/1.1 200 OK\r\ncontent-type: application/json\r\nconnection: close\r\ncontent-length: {}\r\n\r\n{body}",body.len()).as_bytes())).await.unwrap();
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.slugs.local-resolution-id-transport
#[tokio::test]
async fn mock_peer_observes_natural_and_canonical_exact_requests_without_inference() {
    suite(async {
    for mode in [
        "natural",
        "create",
        "exact",
        "update",
        "selection",
        "unlisted",
    ] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let text = match mode {
            "natural" => "alert me if it rains".to_owned(),
            "create" => "create a daily check".into(),
            "exact" => "pause @workflow:daily".into(),
            "update" => "rename @workflow:daily to Evening status.".into(),
            "selection" => "summarize @workflow:daily".into(),
            _ => format!("delete @workflow:{FLOW}"),
        };
        let sent = text.clone();
        let server = Peer(tokio::spawn(async move {
            if !matches!(mode, "natural" | "create") {
                let (mut socket, _) = bounded(listener.accept()).await.unwrap();
                let (line, _) = request(&mut socket).await;
                assert!(line.starts_with("GET /v1/workflows"));
                respond(&mut socket,json!({"workflows":if mode!="unlisted"{vec![json!({"id":FLOW,"title":"Daily","slug":"daily"})]}else{vec![]}})).await;
            }
            let (mut socket, _) = bounded(listener.accept()).await.unwrap();
            let (line, body) = request(&mut socket).await;
            assert_eq!(line, "POST /v1/workflows/ask HTTP/1.1");
            assert_eq!(body["instruction"], sent);
            match mode {
                "exact" => assert_eq!(
                    body["exact_action"],
                    json!({"workflow_id":FLOW,"action":"disable"})
                ),
                "create" => {
                    assert_eq!(body["create"]["title"], sent);
                    assert_eq!(body["create"]["source"], "cli_ask");
                    assert_eq!(body["create"]["created_by_assistant"], true);
                    assert_eq!(body["create"]["graph"]["trigger_node_id"], "manual-trigger");
                    assert!(body["create"]["encrypted_slug"].is_string());
                }
                "update" => {
                    assert_eq!(body["exact_update"]["workflow_id"], FLOW);
                    assert_eq!(body["exact_update"]["patch"]["title"], "Evening status");
                    assert!(body["exact_update"]["patch"].get("encrypted_slug").is_none());
                    assert!(body["exact_update"]["patch"].get("slug").is_none());
                }
                "selection" | "unlisted" => {
                    assert_eq!(body["selected_object_id"], FLOW);
                    assert!(body.get("exact_action").is_none());
                }
                _ => assert_eq!(body, json!({"instruction":sent})),
            };
            respond(
                &mut socket,
                json!({"summary":"Applied synthetic ask","change_set_id":"fixture-change"}),
            )
            .await;
        }));
        let mut command = invocation(&text);
        if mode == "create" {
            command
                .flags
                .insert("description".into(), json!("Explicit fixture description"));
        }
        let result = execute_cookie(&command, &mut client(&api), CancellationToken::new())
            .await
            .ok()
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&result.stdout).unwrap(),
            json!({"summary":"Applied synthetic ask","change_set_id":"fixture-change"})
        );
        server.join().await;
    }

    }).await;
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn cancelled_and_team_asks_do_not_fall_through_to_personal_or_any_chat() {
    suite(async {
        let cancel = CancellationToken::new();
        cancel.cancel();
        assert_eq!(
            execute_cookie(
                &invocation("ask"),
                &mut client("http://127.0.0.1:1"),
                cancel
            )
            .await
            .err()
            .unwrap()
            .exit_code(),
            130
        );
        let mut i = invocation("ask");
        i.flags
            .insert("team".into(), json!("22222222-2222-4222-8222-222222222222"));
        assert_eq!(
            execute_cookie(
                &i,
                &mut client("http://127.0.0.1:1"),
                CancellationToken::new()
            )
            .await
            .err()
            .unwrap()
            .code(),
            "workflow_unavailable"
        );
        let mut i = invocation("ask");
        i.flags.insert("accept-task-proposals".into(), json!(true));
        assert_eq!(
            execute_cookie(
                &i,
                &mut client("http://127.0.0.1:1"),
                CancellationToken::new()
            )
            .await
            .err()
            .unwrap()
            .code(),
            "native_command_unsupported"
        );
    })
    .await;
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn cookie_privacy_gate_and_api_key_only_mode_refuse_before_transport() {
    suite(async {
        let mut cookie = client("http://127.0.0.1:1");
        cookie.set_private_operation_gate(Some(std::sync::Arc::new(|| Err(Error::Forbidden))));
        assert_eq!(
            execute_cookie(&invocation("ask"), &mut cookie, CancellationToken::new())
                .await
                .err()
                .unwrap()
                .code(),
            "forbidden"
        );
        let mut keyed = OpenMates::new(openmates_sdk::SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials: openmates_sdk::SdkCredentials::ApiKey(
                openmates_sdk::ApiKey::new("sk-api-fixture").unwrap(),
            ),
            device_id: "fixture-device".into(),
            client_options: Default::default(),
        })
        .unwrap();
        assert_eq!(
            super::super::execute_sdk_workflows(
                &invocation("ask"),
                &mut keyed,
                CancellationToken::new()
            )
            .await
            .err()
            .unwrap()
            .code(),
            "workflow_ask_requires_cookie_session"
        );
    })
    .await;
}
