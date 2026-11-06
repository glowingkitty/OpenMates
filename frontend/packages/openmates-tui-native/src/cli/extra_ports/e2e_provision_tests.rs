// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,auth.session.isolation
use super::*;
use serde_json::Value;
use std::collections::{BTreeMap, VecDeque};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

struct Script {
    answers: VecDeque<&'static str>,
    env: BTreeMap<&'static str, &'static str>,
}
impl Terminal for Script {
    fn print(&mut self, _: &str) -> Result<(), CliError> {
        Ok(())
    }
    async fn line(&mut self, _: &str) -> Result<String, CliError> {
        Ok(self.answers.pop_front().expect("scripted answer").into())
    }
    async fn secret(&mut self, _: &str) -> Result<Zeroizing<String>, CliError> {
        panic!("no hidden prompt expected");
    }
    fn env(&self, name: &str) -> Option<Zeroizing<String>> {
        self.env.get(name).map(|v| Zeroizing::new((*v).to_owned()))
    }
}
fn terminal(env: &[(&'static str, &'static str)]) -> Script {
    Script {
        answers: VecDeque::new(),
        env: env.iter().copied().collect(),
    }
}
fn invocation(args: &[&str]) -> Invocation {
    let mut full = vec!["openmates", "e2e", "provision-auth-accounts"];
    full.extend_from_slice(args);
    super::super::super::parse_from(full)
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .unwrap()
}
async fn server(responses: Vec<Value>) -> (Client, tokio::task::JoinHandle<Vec<String>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        let mut requests = vec![];
        for body in responses {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = Vec::new();
            loop {
                let mut bytes = [0; 8192];
                let n = socket.read(&mut bytes).await.unwrap();
                assert!(n > 0);
                buf.extend_from_slice(&bytes[..n]);
                if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                    let size = head
                        .lines()
                        .find_map(|l| {
                            l.strip_prefix("content-length:")
                                .and_then(|n| n.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if buf.len() >= end + 4 + size {
                        break;
                    }
                }
            }
            requests.push(String::from_utf8(buf).unwrap());
            let body = body.to_string();
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=e2e; Path=/\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    (Client::new(&api, None).unwrap(), handle)
}
fn flow() -> Vec<Value> {
    vec![
        json!({"success":true}),
        json!({"success":true,"signup_transaction_token":"txn"}),
        json!({"success":true,"user":{"id":"new-user","username":"u"}}),
        json!({"success":true,"secret":"GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ","otpauth_url":"otpauth://totp/x"}),
        json!({"success":true}),
        json!({"success":true}),
        json!({"success":true,"backup_codes":["code-1","code-2"]}),
        json!({"success":true}),
        json!({"success":true}),
    ]
}

#[test]
fn totp_matches_the_rfc_6238_sha1_vector() {
    // RFC 6238 Appendix B: ASCII secret "12345678901234567890", T=59 -> 94287082.
    assert_eq!(
        totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59).ok().unwrap(),
        "287082"
    );
    assert_eq!(
        totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 1111111109)
            .ok()
            .unwrap(),
        "081804"
    );
    assert_eq!(decode_base32("my======"), vec![0x66]);
}

#[test]
fn rollover_window_wait_matches_npm() {
    assert_eq!(safe_window_wait(0), 0);
    assert_eq!(safe_window_wait(27_999), 0);
    assert_eq!(safe_window_wait(28_001), 1_999 + 50);
    assert_eq!(safe_window_wait(29_999), 1 + 50);
}

#[test]
fn production_urls_and_unreserved_slots_are_refused() {
    assert!(guard_api_url("https://api.openmates.org").is_err());
    assert!(guard_api_url("https://api.dev.openmates.org").is_ok());
    assert!(guard_api_url("http://127.0.0.1:8000").is_ok());
    assert_eq!(slot(Some("14")).ok().unwrap(), 14);
    assert_eq!(slot(Some("20.0")).ok().unwrap(), 20);
    assert_eq!(
        slot(Some("13")).err().unwrap().to_string(),
        "Only reserved slots 14-20 are supported."
    );
    assert_eq!(slot(None).err().unwrap().to_string(), "Missing --slot.");
    assert_eq!(
        slot(Some("x")).err().unwrap().to_string(),
        "Invalid --slot: x"
    );
}

#[test]
fn artifact_body_has_the_npm_layout() {
    assert_eq!(
        artifact_body(15, "a@b.c", "pw", "KEY", "x/slot-15.env"),
        "OPENMATES_TEST_ACCOUNT_15_EMAIL=a@b.c\nOPENMATES_TEST_ACCOUNT_15_PASSWORD=pw\nOPENMATES_TEST_ACCOUNT_15_OTP_KEY=KEY\n# Backup codes: x/slot-15.env.backup-codes\n# Recovery key: x/slot-15.env.recovery-key\n"
    );
}

#[tokio::test]
async fn refuses_production_and_password_flags_before_any_request() {
    let (mut client, _server) = server(vec![]).await;
    let args = ["--slot", "15"];
    let result = run(
        &invocation(&args),
        &mut client,
        terminal(&[]),
        "https://api.openmates.org",
        async |_: &mut Client| Ok(()),
    )
    .await;
    assert_eq!(
        result.err().unwrap().to_string(),
        "E2E provisioning refuses production API URLs."
    );
    let result = run(
        &invocation(&["--slot", "15", "--password", "x"]),
        &mut client,
        terminal(&[]),
        "http://127.0.0.1:1",
        async |_: &mut Client| Ok(()),
    )
    .await;
    assert_eq!(
        result.err().unwrap().to_string(),
        "Use generated passwords or OPENMATES_CLI_SIGNUP_PASSWORD, not --password."
    );
    let result = run(
        &invocation(&["--slot", "15"]),
        &mut client,
        terminal(&[]),
        "http://127.0.0.1:1",
        async |_: &mut Client| Ok(()),
    )
    .await;
    assert_eq!(
        result.err().unwrap().to_string(),
        "OPENMATES_CLI_SIGNUP_INVITE_CODE is required for E2E provisioning."
    );
}

#[tokio::test]
async fn provisioning_generates_the_totp_code_and_writes_a_private_artifact() {
    let directory = tempfile::tempdir().unwrap();
    let artifact = directory.path().join("creds/slot-15.env");
    let artifact_text = artifact.to_str().unwrap();
    let (mut client, requests) = server(flow()).await;
    let mut saves = 0;
    let output = run(
        &invocation(&[
            "--slot",
            "15",
            "--artifact",
            artifact_text,
            "--email",
            "e2e@example.org",
            "--json",
        ]),
        &mut client,
        terminal(&[
            ("OPENMATES_CLI_SIGNUP_INVITE_CODE", "INVITE"),
            ("OPENMATES_CLI_SIGNUP_PASSWORD", "fixture-password"),
            ("OPENMATES_CLI_SIGNUP_EMAIL_CODE", "111111"),
        ]),
        "http://127.0.0.1:8000",
        async |_: &mut Client| {
            saves += 1;
            Ok(())
        },
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(saves, 2);
    let value: Value = serde_json::from_str(&output.stdout).unwrap();
    assert_eq!(
        (value["success"].clone(), value["slot"].clone()),
        (json!(true), json!(15))
    );
    assert_eq!(value["email"], "e2e@example.org");
    let body = std::fs::read_to_string(&artifact).unwrap();
    assert!(body.contains("OPENMATES_TEST_ACCOUNT_15_EMAIL=e2e@example.org\n"));
    assert!(body.contains("OPENMATES_TEST_ACCOUNT_15_PASSWORD=fixture-password\n"));
    assert!(body.contains("OPENMATES_TEST_ACCOUNT_15_OTP_KEY=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ\n"));
    assert_eq!(
        std::fs::read_to_string(format!("{artifact_text}.backup-codes")).unwrap(),
        "code-1\ncode-2\n"
    );
    assert!(
        directory
            .path()
            .join("creds/slot-15.env.recovery-key")
            .exists()
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            std::fs::metadata(&artifact).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
    let requests = requests.await.unwrap();
    let code = requests[4]
        .split(r#""code":""#)
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap();
    assert_eq!(code.len(), 6);
    assert!(code.bytes().all(|b| b.is_ascii_digit()));
    assert!(requests[0].contains("INVITE"));
    assert!(!output.stdout.contains("fixture-password") && !output.stdout.contains("GEZDGNBV"));
}
