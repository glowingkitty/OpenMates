// contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
use super::*;
use serde_json::json;

fn invocation(flags: &[(&str, Value)]) -> Invocation {
    Invocation {
        path: vec!["apps".into(), "code".into(), "run".into()],
        positionals: vec![],
        flags: flags.iter().map(|(k, v)| ((*k).into(), v.clone())).collect(),
    }
}
fn finished(output: &str, exit_code: i64) -> Value {
    json!({"data":{"results":[{"execution_id":"e","status_path":"/v1/code/run/e",
        "final":{"status":"finished","exit_code":exit_code,"output":output}}]}})
}
fn write(root: &Path, rel: &str, body: &str) {
    let path = root.join(rel);
    std::fs::create_dir_all(path.parent().unwrap_or(root)).unwrap_or_default();
    std::fs::write(path, body).unwrap_or_default();
}

#[test]
fn dir_walk_applies_default_ignores_exclude_and_include() {
    let dir = tempfile::tempdir().unwrap_or_else(|_| panic!("tempdir"));
    let root = dir.path();
    write(root, "main.py", "print(1)");
    write(root, "lib/util.py", "x=1");
    write(root, "notes.md", "n");
    write(root, "node_modules/dep/a.js", "x");
    write(root, "secret.env", "x");
    let path = root.to_string_lossy().into_owned();
    let body = build_body(
        &invocation(&[("dir", json!(path)), ("exclude", json!("*.env")), ("entry", json!("lib/util.py"))]),
        false,
    )
    .unwrap_or_else(|_| panic!("body"));
    let files = body["requests"][0]["files"].as_array().cloned().unwrap_or_default();
    let paths: Vec<_> = files.iter().filter_map(|f| f["path"].as_str()).collect();
    assert_eq!(paths, ["lib/util.py", "main.py", "notes.md"]);
    assert_eq!(body["requests"][0]["entry_path"], "lib/util.py");
    let only_py = build_body(&invocation(&[("dir", json!(path)), ("include", json!("*.py"))]), true)
        .unwrap_or_else(|_| panic!("body"));
    assert_eq!(only_py["requests"][0]["files"].as_array().map(Vec::len), Some(2));
    assert_eq!(only_py["allow_e2b_upload"], true);
}

#[test]
fn inline_code_and_flags_build_the_documented_body() {
    let body = build_body(
        &invocation(&[("code", json!("print(1)")), ("language", json!("python")), ("no-internet", json!(true))]),
        false,
    )
    .unwrap_or_else(|_| panic!("body"));
    assert_eq!(body["requests"][0]["entry_path"], "main.py");
    assert_eq!(body["requests"][0]["enable_internet"], false);
    assert!(body.get("allow_e2b_upload").is_none());
    let unsafe_name = build_body(&invocation(&[("code", json!("x")), ("source-filename", json!("../x.py"))]), false);
    assert!(matches!(unsafe_name, Err(CliError::Invalid(m)) if m.contains("Unsafe Code Run path")));
    assert!(matches!(build_body(&invocation(&[]), false), Err(CliError::Invalid(_))));
}

#[test]
fn out_of_scope_flags_are_refused_with_a_typed_error() {
    for flag in ["url", "repo", "chat", "target-embed"] {
        let result = build_body(&invocation(&[("code", json!("x")), (flag, json!("v"))]), false);
        assert!(matches!(result, Err(CliError::Unsupported { .. })), "{flag}");
    }
}

#[tokio::test]
async fn human_output_prints_status_line_output_and_succeeds() {
    let i = invocation(&[("code", json!("print(1)")), ("language", json!("python"))]);
    let out = flow(&i, |_| async { Ok(finished("1\n", 0)) }).await.unwrap_or_else(|_| panic!("run"));
    assert_eq!((out.exit_code, out.stdout.as_str()), (0, "1\n"));
    assert_eq!(out.stderr, "Starting Code Run for main.py (1 file)...\n");
}

#[tokio::test]
async fn failed_run_exits_nonzero_and_json_embeds_final() {
    let i = invocation(&[("code", json!("x")), ("language", json!("python")), ("json", json!(true))]);
    let out = flow(&i, |_| async { Ok(finished("boom", 3)) }).await.unwrap_or_else(|_| panic!("run"));
    assert_eq!(out.exit_code, 1);
    assert_eq!(out.stderr, "Code Run finished with exit code 3.\n");
    let printed: Value = serde_json::from_str(&out.stdout).unwrap_or_default();
    assert_eq!(printed["final"]["exit_code"], 3);
    assert_eq!(printed["execution_id"], "e");
}

#[tokio::test]
async fn consent_required_refuses_with_exit_two_without_a_tty() {
    let i = invocation(&[("code", json!("x")), ("language", json!("python"))]);
    let out = flow(&i, |_| async { Err(Error::Unavailable { code: "e2b_consent_required", reason: "r" }) })
        .await
        .unwrap_or_else(|_| panic!("refusal"));
    assert_eq!(out.exit_code, 2);
    assert!(out.stderr.contains("Nothing was uploaded."));
}

#[tokio::test]
async fn allow_flag_sends_upload_consent_from_the_start() {
    let i = invocation(&[("code", json!("x")), ("allow-e2b-upload", json!(true))]);
    let out = flow(&i, |body| async move {
        assert_eq!(body["allow_e2b_upload"], true);
        Ok(finished("ok", 0))
    })
    .await
    .unwrap_or_else(|_| panic!("run"));
    assert_eq!(out.exit_code, 0);
}

/// One-shot loopback API: answers `routes` in order, one connection each.
async fn api(routes: Vec<(u16, Value)>) -> (String, tokio::task::JoinHandle<Vec<String>>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap_or_else(|_| panic!("bind"));
    let base = format!("http://{}", listener.local_addr().unwrap_or_else(|_| panic!("addr")));
    let task = tokio::spawn(async move {
        let mut lines = vec![];
        for (status, body) in routes {
            let Ok((mut socket, _)) = listener.accept().await else { break };
            let mut bytes = vec![];
            let mut chunk = [0u8; 4096];
            let end = loop {
                let n = socket.read(&mut chunk).await.unwrap_or(0);
                bytes.extend_from_slice(&chunk[..n]);
                if let Some(at) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    break at + 4;
                }
                if n == 0 {
                    break bytes.len();
                }
            };
            let head = String::from_utf8_lossy(&bytes[..end]).into_owned();
            let length = head
                .lines()
                .find_map(|l| {
                    let (k, v) = l.split_once(':')?;
                    k.eq_ignore_ascii_case("content-length").then(|| v.trim().parse::<usize>().unwrap_or(0))
                })
                .unwrap_or(0);
            while bytes.len() < end + length {
                let n = socket.read(&mut chunk).await.unwrap_or(0);
                if n == 0 {
                    break;
                }
                bytes.extend_from_slice(&chunk[..n]);
            }
            lines.push(head.lines().next().unwrap_or("").to_owned());
            let raw = body.to_string();
            let reply = format!(
                "HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{raw}",
                raw.len()
            );
            let _ = socket.write_all(reply.as_bytes()).await;
        }
        lines
    });
    (base, task)
}

fn session_client(base: &str) -> crate::client::Client {
    let session = serde_json::from_value(json!({"api_url":base,"session_id":"synthetic-session","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}))
        .unwrap_or_else(|_| panic!("session"));
    crate::client::Client::new(base, Some(session)).unwrap_or_else(|_| panic!("client"))
}

#[tokio::test]
async fn session_path_posts_the_built_body_and_polls_the_status_path() {
    let accepted = json!({"success":true,"data":{"results":[{"execution_id":"e","status_path":"/v1/code/run/e"}]}});
    let (base, server) = api(vec![(200, accepted), (200, json!({"status":"finished","exit_code":0,"output":"hi\n"}))]).await;
    let mut client = session_client(&base);
    let admission = client.direct_app_skill_admission().unwrap_or_else(|_| panic!("admission"));
    let i = invocation(&[("code", json!("print('hi')")), ("language", json!("python"))]);
    let out = execute_session(&i, &mut client, &admission).await.unwrap_or_else(|_| panic!("run"));
    assert_eq!((out.exit_code, out.stdout.as_str()), (0, "hi\n"));
    let lines = server.await.unwrap_or_default();
    assert!(lines[0].starts_with("POST /v1/apps/code/skills/run "), "{lines:?}");
    assert!(lines[1].starts_with("GET /v1/code/run/e "), "{lines:?}");
}

#[tokio::test]
async fn session_path_consent_refusal_exits_two_without_a_tty() {
    let (base, server) = api(vec![(403, json!({"detail":{"code":"e2b_consent_required"}}))]).await;
    let mut client = session_client(&base);
    let admission = client.direct_app_skill_admission().unwrap_or_else(|_| panic!("admission"));
    let i = invocation(&[("code", json!("x")), ("language", json!("python"))]);
    let out = execute_session(&i, &mut client, &admission).await.unwrap_or_else(|_| panic!("refusal"));
    assert_eq!(out.exit_code, 2);
    assert!(out.stderr.contains("Nothing was uploaded."));
    drop(server.await);
}
