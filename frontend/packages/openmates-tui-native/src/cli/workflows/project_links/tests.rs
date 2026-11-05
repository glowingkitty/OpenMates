use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const FLOW: &str = "11111111-1111-4111-8111-111111111111";
const PROJECT: &str = "22222222-2222-4222-8222-222222222222";
const TEAM: &str = "33333333-3333-4333-8333-333333333333";
fn invocation(json: bool) -> Invocation {
    Invocation {
        path: vec!["workflows".into(), "remove-from-project".into()],
        positionals: vec![FLOW.into(), PROJECT.into()],
        flags: BTreeMap::from([("json".into(), json!(json))]),
    }
}
fn client(api: &str) -> Client {
    Client::new(
        api,
        Some(crate::storage::Session {
            api_url: api.into(),
            session_id: "fixture-session".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([1; 32]),
            hashed_email: "fixture-owner".into(),
            user_email_salt: "fixture-salt".into(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
fn project() -> Value {
    json!({"project_id":PROJECT,"encrypted_project_key":openmates_sdk::crypto::encrypt_bytes(&[2;32],&[1;32]).unwrap(),
        "encrypted_name":openmates_sdk::crypto::encrypt_combined("Fixture Project",&[2;32]).unwrap()})
}
async fn request(socket: &mut tokio::net::TcpStream) -> String {
    let mut bytes = vec![];
    let mut part = [0; 4096];
    while !bytes.windows(4).any(|bytes| bytes == b"\r\n\r\n") {
        let count = socket.read(&mut part).await.unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&part[..count]);
        assert!(bytes.len() < 65536);
    }
    String::from_utf8(bytes)
        .unwrap()
        .lines()
        .next()
        .unwrap()
        .into()
}
async fn response(socket: &mut tokio::net::TcpStream, status: &str, value: Value) {
    let body = value.to_string();
    socket.write_all(format!("HTTP/1.1 {status}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.slugs.local-resolution-id-transport
#[tokio::test]
async fn real_native_dispatch_removes_all_matching_links_only_and_repeat_is_zero() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let rows = std::sync::Arc::new(std::sync::Mutex::new(vec![
        (PROJECT.to_owned(), FLOW.to_owned(), "workflow".to_owned()),
        (PROJECT.to_owned(), FLOW.to_owned(), "workflow".to_owned()),
        (
            PROJECT.to_owned(),
            "another-flow".to_owned(),
            "workflow".to_owned(),
        ),
        (
            "another-project".to_owned(),
            FLOW.to_owned(),
            "workflow".to_owned(),
        ),
        (PROJECT.to_owned(), FLOW.to_owned(), "chat".to_owned()),
    ]));
    let remaining = rows.clone();
    let server = tokio::spawn(async move {
        for _ in 0..10 {
            let (mut socket, _) = listener.accept().await.unwrap();
            let line = request(&mut socket).await;
            let parts: Vec<_> = line.split_whitespace().collect();
            let url = url::Url::parse(&format!("http://fixture{}", parts[1])).unwrap();
            let body = match (parts[0], url.path()) {
                ("GET", path) if path == format!("/v1/projects/{PROJECT}") => {
                    json!({"project":project()})
                }
                ("GET", path) if path == format!("/v1/workflows/{FLOW}") => {
                    json!({"workflow":{"id":FLOW,"title":"Fixture Workflow"}})
                }
                ("DELETE", path) if path == format!("/v1/projects/{PROJECT}/items") => {
                    let query: BTreeMap<_, _> = url.query_pairs().into_owned().collect();
                    assert_eq!(
                        query,
                        BTreeMap::from([
                            ("item_type".into(), "workflow".into()),
                            ("target_id".into(), FLOW.into())
                        ])
                    );
                    let count = {
                        let mut rows = rows.lock().unwrap();
                        let before = rows.len();
                        rows.retain(|(project, target, kind)| {
                            project != PROJECT || target != FLOW || kind != "workflow"
                        });
                        before - rows.len()
                    };
                    json!({"deleted":count>0,"deleted_count":count})
                }
                _ => panic!("unexpected fixture route"),
            };
            response(&mut socket, "200 OK", body).await;
        }
    });
    let mut client = client(&api);
    for count in [2, 0] {
        let result = execute_cookie(&invocation(true), &mut client, CancellationToken::new())
            .await
            .ok()
            .unwrap();
        let actual: Value = serde_json::from_str(&result.stdout).unwrap();
        assert_eq!(
            actual,
            json!({"objectType":"workflow","objectId":FLOW,"projectId":PROJECT,"deleted":count>0,"deletedCount":count})
        );
        assert_eq!(result.exit_code, 0);
    }
    server.await.unwrap();
    assert_eq!(remaining.lock().unwrap().len(), 3);
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn explicit_team_is_sent_on_the_first_authorized_project_request() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let line = request(&mut socket).await;
        let target = line.split_whitespace().nth(1).unwrap();
        let url = url::Url::parse(&format!("http://fixture{target}")).unwrap();
        assert_eq!(url.path(), format!("/v1/projects/{PROJECT}"));
        assert_eq!(
            url.query_pairs()
                .find(|(key, _)| key == "team_id")
                .unwrap()
                .1,
            TEAM
        );
        response(
            &mut socket,
            "403 Forbidden",
            json!({"detail":"TEAM_PERMISSION_DENIED"}),
        )
        .await;
    });
    let mut i = invocation(true);
    i.flags.insert("team".into(), json!(TEAM));
    let error = execute_cookie(&i, &mut client(&api), CancellationToken::new())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code(), "forbidden");
    server.await.unwrap();
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn cancelled_removal_and_conflicting_context_never_start_transport() {
    let cancel = CancellationToken::new();
    cancel.cancel();
    let error = execute_cookie(&invocation(true), &mut client("http://127.0.0.1:1"), cancel)
        .await
        .err()
        .unwrap();
    assert_eq!(error.exit_code(), 130);
    let mut i = invocation(true);
    i.flags.insert("personal".into(), json!(true));
    i.flags.insert("team".into(), json!(TEAM));
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
        "invalid_argument"
    );
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[test]
fn legacy_text_and_json_do_not_leak_snake_case_or_accept_malformed_ack() {
    for (deleted, count, text) in [
        (true, 2, "workflow removed from Project"),
        (false, 0, "workflow was not linked to Project"),
    ] {
        let result = render(
            &invocation(false),
            FLOW,
            PROJECT,
            json!({"deleted":deleted,"deleted_count":count}),
        )
        .ok()
        .unwrap();
        assert_eq!(result.stdout.trim(), format!("{text}: {PROJECT}"));
    }
    for ack in [
        json!({"deleted":true}),
        json!({"deleted":false,"deleted_count":2}),
        json!({"deleted":true,"deleted_count":0}),
        json!({"deleted":true,"deleted_count":"2"}),
    ] {
        assert_eq!(
            render(&invocation(true), FLOW, PROJECT, ack)
                .err()
                .unwrap()
                .code(),
            "invalid_server_response"
        );
    }
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[test]
fn retained_selector_first_grammar_routes_to_native_removal() {
    let parsed = crate::cli::parse_from([
        "openmates",
        "workflows",
        FLOW,
        "remove-from-project",
        PROJECT,
        "--personal",
        "--json",
    ])
    .ok()
    .unwrap();
    let invocation = parsed.invocation.unwrap();
    assert_eq!(invocation.command_path(), "workflows remove-from-project");
    assert_eq!(invocation.positionals, vec![FLOW, PROJECT]);
    assert!(super::super::supported(&invocation));
}
