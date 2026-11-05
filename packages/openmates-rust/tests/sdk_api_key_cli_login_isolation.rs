//! The Rust API-key SDK never discovers or sends the CLI login.
//! A child process runs with HOME, XDG dirs and OPENMATES_STATE_DIR pointing at a
//! planted fake CLI login; its API-key request to a loopback server must carry
//! only the bearer component and never the planted cookie. A source guard keeps
//! CLI credential discovery (state dir, session.json, keyrings) out of the SDK
//! crate. Spec: surface.sdk sdk.library.explicit-headless.
use openmates_sdk::{ApiKey, ClientOptions, OpenMates, SdkCredentials, SdkOptions};
use std::io::{Read, Write};
use std::net::TcpListener;

const FAKE_COOKIE: &str = "cli-login-cookie-must-never-leave-the-cli";

// contract-test: direct surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn api_key_sdk_ignores_planted_cli_login() {
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("home");
    for dir in [home.join(".openmates"), root.path().join("state"), root.path().join("xdg-config"), root.path().join("xdg-data")] {
        std::fs::create_dir_all(&dir).unwrap();
        let login = serde_json::json!({"cookies": {"auth_refresh_token": FAKE_COOKIE}, "ws_token": FAKE_COOKIE});
        std::fs::write(dir.join("session.json"), login.to_string()).unwrap();
    }
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "child_sends_only_the_explicit_api_key", "--nocapture"])
        .env("OPENMATES_SDK_LOGIN_ISOLATION_CHILD", "1")
        .env("HOME", &home)
        .env("OPENMATES_STATE_DIR", root.path().join("state"))
        .env("XDG_CONFIG_HOME", root.path().join("xdg-config"))
        .env("XDG_DATA_HOME", root.path().join("xdg-data"))
        .env_remove("OPENMATES_API_KEY")
        .status()
        .unwrap();
    assert!(status.success());
}

// contract-test: direct surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[tokio::test]
async fn child_sends_only_the_explicit_api_key() {
    if std::env::var("OPENMATES_SDK_LOGIN_ISOLATION_CHILD").as_deref() != Ok("1") {
        return;
    }
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = Vec::new();
        let mut buffer = [0u8; 4096];
        while !request.windows(4).any(|w| w == b"\r\n\r\n") {
            let read = stream.read(&mut buffer).unwrap();
            if read == 0 { break; }
            request.extend_from_slice(&buffer[..read]);
        }
        let body = br#"{"id":"account"}"#;
        write!(stream, "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n", body.len()).unwrap();
        stream.write_all(body).unwrap();
        String::from_utf8_lossy(&request).to_ascii_lowercase()
    });
    let client = OpenMates::new(SdkOptions {
        api_url: format!("http://127.0.0.1:{port}"),
        credentials: SdkCredentials::ApiKey(ApiKey::new("sk-api-guardtest").unwrap()),
        device_id: "guard-device".into(),
        client_options: ClientOptions::default(),
    })
    .unwrap();
    client.account_info().await.unwrap();
    let request = server.join().unwrap();
    assert!(request.starts_with("get /v1/sdk/account "));
    assert!(request.contains("authorization: bearer sk-api-guardtest\r\n"));
    assert!(!request.contains("\r\ncookie:"));
    assert!(!request.contains(FAKE_COOKIE));
}

// contract-test: direct surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
#[test]
fn sdk_crate_has_no_cli_credential_discovery() {
    let mut pending = vec![std::path::PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/src"))];
    let forbidden = ["OPENMATES_STATE_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "session.json", "keyring", "dirs::home_dir", "env::var(\"HOME\")", "home_dir()"];
    while let Some(path) = pending.pop() {
        if path.is_dir() {
            pending.extend(std::fs::read_dir(&path).unwrap().map(|e| e.unwrap().path()));
        } else if path.extension().is_some_and(|e| e == "rs") && !path.to_string_lossy().ends_with("_tests.rs") {
            // Doc comments may state the boundary; code may not implement discovery.
            let source = std::fs::read_to_string(&path).unwrap();
            for line in source.lines().filter(|line| !line.trim_start().starts_with("//")) {
                for needle in forbidden {
                    assert!(!line.contains(needle), "{} references CLI credential location {needle}", path.display());
                }
            }
        }
    }
}
