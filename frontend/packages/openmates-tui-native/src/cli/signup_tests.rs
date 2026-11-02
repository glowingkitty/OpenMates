// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,sdk.encryption.local-only
use super::*;
use std::collections::{BTreeMap, VecDeque};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

/// Scripted terminal: answers in order, records everything shown.
struct Script {
    answers: VecDeque<&'static str>,
    shown: String,
    env: BTreeMap<&'static str, &'static str>,
}
impl Terminal for Script {
    fn print(&mut self, text: &str) -> Result<(), CliError> {
        self.shown.push_str(text);
        Ok(())
    }
    async fn line(&mut self, question: &str) -> Result<String, CliError> {
        self.shown.push_str(question);
        Ok(self.answers.pop_front().expect("scripted answer").into())
    }
    async fn secret(&mut self, question: &str) -> Result<Zeroizing<String>, CliError> {
        self.shown.push_str(question);
        Ok(Zeroizing::new(
            self.answers.pop_front().expect("scripted secret").into(),
        ))
    }
    fn env(&self, name: &str) -> Option<Zeroizing<String>> {
        self.env.get(name).map(|v| Zeroizing::new((*v).to_owned()))
    }
}
fn script(answers: &[&'static str], env: &[(&'static str, &'static str)]) -> Script {
    Script {
        answers: answers.iter().copied().collect(),
        shown: String::new(),
        env: env.iter().copied().collect(),
    }
}
/// Loopback double for the legacy signup routes (never a real account).
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
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=signup; Path=/\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    (Client::new(&api, None).unwrap(), handle)
}
fn invocation(args: &[&str]) -> Invocation {
    super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .unwrap()
}
fn full_flow() -> Vec<Value> {
    vec![
        json!({"success":true}),
        json!({"success":true,"signup_transaction_token":"txn"}),
        json!({"success":true,"user":{"id":"new-user","username":"alice"}}),
        json!({"success":true,"secret":"JBSWY3DPEHPK3PXP","otpauth_url":"otpauth://totp/OpenMates:alice?secret=JBSWY3DPEHPK3PXP"}),
        json!({"success":true}),
        json!({"success":true}),
        json!({"success":true,"backup_codes":["code-1","code-2"]}),
        json!({"success":true}),
        json!({"success":true}),
    ]
}

#[tokio::test]
async fn automated_signup_writes_secret_files_and_saves_credentials_twice() {
    let directory = tempfile::tempdir().unwrap();
    let backup = directory.path().join("nested/backup.txt");
    let recovery = directory.path().join("recovery.txt");
    let (mut client, requests) = server(full_flow()).await;
    let args = [
        "openmates",
        "signup",
        "--email",
        "alice@example.org",
        "--username",
        "alice",
        "--invite-code",
        "INVITE",
        "--yes",
        "--backup-codes-output",
        backup.to_str().unwrap(),
        "--recovery-key-output",
        recovery.to_str().unwrap(),
        "--json",
    ];
    let mut terminal = script(
        &[],
        &[
            ("OPENMATES_CLI_SIGNUP_PASSWORD", "correct horse"),
            ("OPENMATES_CLI_SIGNUP_EMAIL_CODE", "111111"),
            ("OPENMATES_CLI_SIGNUP_TOTP_CODE", "222222"),
        ],
    );
    let mut saves = 0;
    let output = run(
        &invocation(&args),
        &mut client,
        &mut terminal,
        async |c: &mut Client| {
            assert!(c.session().is_some());
            saves += 1;
            Ok(())
        },
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(saves, 2);
    let value: Value = serde_json::from_str(&output.stdout).unwrap();
    assert_eq!(value["success"], true);
    assert_eq!(value["user"]["id"], "new-user");
    assert_eq!(value["backup_codes_path"], backup.to_str().unwrap());
    assert_eq!(
        std::fs::read_to_string(&backup).unwrap(),
        "code-1\ncode-2\n"
    );
    let key = std::fs::read_to_string(&recovery).unwrap();
    assert_eq!(key.trim().len(), 24);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            std::fs::metadata(&recovery).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
    assert!(
        terminal
            .shown
            .contains("Manual TOTP secret: JBSWY3DPEHPK3PXP\n")
    );
    assert!(terminal.shown.contains('█'), "QR code is rendered");
    assert!(
        !terminal.shown.contains("code-1"),
        "file output keeps backup codes off the terminal"
    );
    let requests = requests.await.unwrap();
    assert!(requests[1].contains(r#""code":"111111""#));
    assert!(requests[4].contains(r#""code":"222222""#));
    assert!(requests[5].contains(r#""provider":"Authenticator app""#));
    assert!(
        !requests
            .iter()
            .any(|r| r.contains("correct horse") || r.contains(key.trim()))
    );
    // Refuses to overwrite an existing secret file without --force.
    let (mut client, _requests) = server(full_flow()).await;
    let mut terminal = script(
        &[],
        &[
            ("OPENMATES_CLI_SIGNUP_PASSWORD", "pw"),
            ("OPENMATES_CLI_SIGNUP_EMAIL_CODE", "1"),
            ("OPENMATES_CLI_SIGNUP_TOTP_CODE", "2"),
        ],
    );
    let result = run(
        &invocation(&args),
        &mut client,
        &mut terminal,
        async |_: &mut Client| Ok(()),
    )
    .await;
    assert!(
        matches!(result, Err(CliError::Invalid(message)) if message.ends_with("already exists. Use --force to overwrite."))
    );
}

#[tokio::test]
async fn interactive_prompts_show_secrets_and_abort_keeps_the_new_account() {
    let (mut client, requests) = server(full_flow()[..7].to_vec()).await;
    let mut terminal = script(
        &[
            "alice@example.org",
            "alice",
            "pw",
            "pw",
            "111111",
            "222222",
            "n",
        ],
        &[],
    );
    let mut saves = 0;
    let output = run(
        &invocation(&["openmates", "signup"]),
        &mut client,
        &mut terminal,
        async |_: &mut Client| {
            saves += 1;
            Ok(())
        },
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        (output.stdout.as_str(), output.exit_code, saves),
        ("Aborted.\n", 0, 2)
    );
    assert!(
        terminal
            .shown
            .starts_with("Email: Username: Password: Confirm password: Email verification code: ")
    );
    assert!(terminal.shown.contains(
        "Backup codes:\n  code-1\n  code-2\nI stored these backup codes safely. Continue? [y/N] "
    ));
    assert_eq!(
        requests.await.unwrap().len(),
        7,
        "backup codes were never confirmed"
    );
}

#[tokio::test]
async fn passwords_never_come_from_flags_and_rejections_keep_server_messages() {
    let (mut client, _requests) = server(vec![]).await;
    let mut terminal = script(&[], &[]);
    let result = run(
        &invocation(&[
            "openmates",
            "signup",
            "--email",
            "a@example.org",
            "--username",
            "a",
            "--password",
            "x",
        ]),
        &mut client,
        &mut terminal,
        async |_: &mut Client| Ok(()),
    )
    .await;
    assert!(
        matches!(result, Err(CliError::Invalid(m)) if m == "Passwords must be entered through hidden prompts, not command-line flags.")
    );
    let mut terminal = script(&["one", "two"], &[]);
    let result = run(
        &invocation(&[
            "openmates",
            "signup",
            "--email",
            "a@example.org",
            "--username",
            "a",
        ]),
        &mut client,
        &mut terminal,
        async |_: &mut Client| Ok(()),
    )
    .await;
    assert!(matches!(result, Err(CliError::Invalid(m)) if m == "Passwords do not match."));
    let (mut client, _requests) = server(vec![
        json!({"success":false,"message":"Invalid invite code."}),
    ])
    .await;
    let mut terminal = script(&[], &[("OPENMATES_CLI_SIGNUP_PASSWORD", "pw")]);
    let result = run(
        &invocation(&[
            "openmates",
            "signup",
            "--email",
            "a@example.org",
            "--username",
            "a",
        ]),
        &mut client,
        &mut terminal,
        async |_: &mut Client| panic!("no account was created"),
    )
    .await;
    assert!(
        matches!(result, Err(CliError::Contract { code: "command_failed", message }) if message == "Invalid invite code.")
    );
}
