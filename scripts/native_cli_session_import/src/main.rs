//! Dev-only test tooling (not product code): signs the personal dev-test
//! account in through the shared Rust core's password login and admits the
//! resulting session into an isolated native CLI state directory, the same
//! store the native `openmates` binary reads. Used by `scripts/*_real_test.py`
//! harnesses because native `login` is browser pairing only.
//!
//! Inputs come only from the environment (never argv, never printed):
//! `OPENMATES_STATE_DIR` (absolute, below /tmp), `OPENMATES_API_URL`,
//! `OPENMATES_APP_URL`, `OPENMATES_TEST_ACCOUNT_EMAIL`,
//! `OPENMATES_TEST_ACCOUNT_PASSWORD`, `OPENMATES_TEST_ACCOUNT_TOTP` (current
//! one-time code computed by the caller). Exit 0 prints `{"ok":true}`.
use openmates::runtime_store::RuntimeStore;
use openmates::sdk::{Client, ClientIdentity, ClientOptions, PasswordLoginOptions};
use std::path::PathBuf;
use std::process::ExitCode;

fn required(name: &str) -> Result<String, String> {
    std::env::var(name)
        .ok()
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("missing_{}", name.to_lowercase()))
}

async fn run() -> Result<(), String> {
    let state = PathBuf::from(required("OPENMATES_STATE_DIR")?);
    // Refuse anything but an isolated temporary state directory.
    if !state.is_absolute() || !state.starts_with("/tmp/") {
        return Err("state_dir_must_be_below_tmp".into());
    }
    let api = required("OPENMATES_API_URL")?;
    let app = required("OPENMATES_APP_URL")?;
    let email = required("OPENMATES_TEST_ACCOUNT_EMAIL")?;
    let password = zeroize::Zeroizing::new(required("OPENMATES_TEST_ACCOUNT_PASSWORD")?);
    let totp = std::env::var("OPENMATES_TEST_ACCOUNT_TOTP")
        .ok()
        .filter(|v| !v.is_empty());
    let mut client = Client::with_options(
        &api,
        None,
        ClientOptions {
            identity: ClientIdentity::Cli,
            app_url: Some(app),
            ..Default::default()
        },
    )
    .map_err(|_| "client_init_failed".to_string())?;
    client
        .login_password_with_options(
            &email,
            &password,
            totp.as_deref(),
            PasswordLoginOptions {
                stay_logged_in: true,
            },
        )
        .await
        .map_err(|_| "password_login_failed".to_string())?;
    let session = client.session().cloned().ok_or("session_missing")?;
    let store = RuntimeStore::new(Some(state), false)
        .await
        .map_err(|_| "state_store_open_failed".to_string())?;
    store
        .begin_session(session.clone())
        .await
        .map_err(|_| "session_admission_failed".to_string())?;
    store
        .save(session, None)
        .await
        .map_err(|_| "session_save_failed".to_string())?;
    Ok(())
}

#[tokio::main]
async fn main() -> ExitCode {
    match run().await {
        Ok(()) => {
            println!("{{\"ok\":true}}");
            ExitCode::SUCCESS
        }
        Err(code) => {
            eprintln!("{{\"ok\":false,\"error\":\"{code}\"}}");
            ExitCode::FAILURE
        }
    }
}
