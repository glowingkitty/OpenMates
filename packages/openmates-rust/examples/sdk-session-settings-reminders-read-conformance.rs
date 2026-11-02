//! Direct Rust library runner: actual per-case assertions and production 61-second waits.
//! Invoked by the fixed gate adapter only in isolated CI.
use openmates_sdk::{Client, Session};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, io::Read, path::PathBuf, process::ExitCode};
#[path = "../tests/support/settings_reminders_fixture.rs"]
mod fixture;
#[tokio::main]
async fn main() -> ExitCode {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.len() != 4 || args[0] != "--fixture" || args[2] != "--capability" || args[3] != "session.settings-reminders-read" {
        eprintln!("usage: settings runner --fixture PATH --capability session.settings-reminders-read");
        return ExitCode::FAILURE;
    }
    let file = match std::fs::File::open(PathBuf::from(&args[1])) {
        Ok(f) => f,
        Err(_) => return ExitCode::FAILURE,
    };
    let mut bytes = Vec::new();
    if file.take(1024 * 1024 + 1).read_to_end(&mut bytes).is_err() || bytes.len() > 1024 * 1024 {
        return ExitCode::FAILURE;
    }
    let input: Value = match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(_) => return ExitCode::FAILURE,
    };
    assert_eq!(input["capability"], "session.settings-reminders-read");
    assert_eq!(
        input["retry"],
        serde_json::json!({"only_status":429,"max_retries":1,"delay_ms":61000})
    );
    assert_eq!(input["cases"].as_array().expect("fixture cases").len(), 28);
    let mut results = Vec::new();
    for case in input["cases"].as_array().expect("fixture cases") {
        let (origin, peer, control) = fixture::controlled_peer(case).await;
        let session = case["session"].as_bool().unwrap().then(|| Session {
            api_url: origin.clone(),
            session_id: "synthetic-settings-session".into(),
            cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture".into())]),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([0; 32]),
            hashed_email: "synthetic".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 0,
            paired_session_expires_at: None,
            active_team_id: Some("00000000-0000-4000-8000-000000000001".into()),
        });
        let mut client = Client::new(&origin, session).unwrap();
        let cancel = tokio_util::sync::CancellationToken::new();
        client.set_operation_cancel(cancel.clone());
        let started = std::time::Instant::now();
        let mut account = client.account();
        let cancellation = async move {
            if let Some(control) = control {
                control.ready.await.expect("actual response gate");
                cancel.cancel();
                control.release.send(()).expect("release actual response");
            }
        };
        let (result, ()) = tokio::join!(account.reminders_ordered(), cancellation);
        drop(account);
        if !case["expected"]["wait_ms"].as_array().unwrap().is_empty() {
            assert!(started.elapsed() >= std::time::Duration::from_millis(61_000));
        }
        let expected = &case["expected"];
        match result {
            Ok(value) => {
                assert_eq!(expected["ok"], true);
                assert_eq!(value.value(), &expected["value"]);
                if let Some(keys)=expected.get("root_keys") {
                    assert_eq!(serde_json::json!(value.root_keys()),*keys);
                    assert_eq!(serde_json::to_string(&value).unwrap(),expected["serialized_json"].as_str().unwrap());
                }
            }
            Err(error) => {
                assert_eq!(expected["ok"], false);
                assert_eq!(
                    match error.core_error() {
                        openmates_sdk::Error::Unavailable {code:"settings_json_unsupported",reason} => {
                            assert_eq!(reason,"SETTINGS_RESPONSE_EXCEEDS_SUPPORTED_JSON_LIMITS_OR_REPRESENTATION");
                            "Unavailable".to_owned()
                        }
                        other => format!("{other:?}"),
                    },
                    expected["error"].as_str().unwrap()
                );
                assert_eq!(
                    serde_json::json!(error.http_status()),
                    expected["http_status"]
                );
                if let Some(message) = expected.get("message") {
                    assert_eq!(error.to_string(),message.as_str().unwrap());
                }
                if let Some(status) = error.http_status() {
                    assert_eq!(
                        error.to_string(),
                        format!("Settings GET failed with HTTP {status}")
                    );
                }
            }
        }
        assert_eq!(
            peer.await.unwrap() as u64,
            expected["requests"].as_u64().unwrap()
        );
        if case["action"] == "cancel_body" {
            assert_eq!(client.session().unwrap().cookies.get("auth_refresh_token").map(String::as_str),Some("rotated"));
        }
        // Emit a result only after every actual Core/peer assertion above passed.
        results.push(serde_json::json!({"id":case["id"],"status":"passed"}));
    }
    println!(
        "{}",
        serde_json::json!({"capability":"session.settings-reminders-read","language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(&bytes)),"results":results})
    );
    ExitCode::SUCCESS
}
