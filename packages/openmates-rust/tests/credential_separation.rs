//! The subprocess changes its own environment; SDK code itself never spawns.
use openmates_sdk::{Client, Error};
use tokio_util::sync::CancellationToken;
#[test]
fn installed_cli_state_is_not_a_sdk_credential_or_policy_source() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::create_dir(directory.path().join(".openmates")).unwrap();
    let preferences =
        serde_json::json!({"version":1,"enabled":true,"documents":true,"projects":[]});
    for path in [
        directory.path().join("privacy-preferences.json"),
        directory.path().join(".openmates/privacy-preferences.json"),
    ] {
        std::fs::write(path, preferences.to_string()).unwrap();
    }
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .arg("--exact")
        .arg("child_has_explicit_sdk_credentials_only")
        .arg("--nocapture")
        .env("OPENMATES_SDK_BOUNDARY_CHILD", "1")
        .env("HOME", directory.path())
        .env("OPENMATES_STATE_DIR", directory.path())
        .env("OPENMATES_PROFILE", "injected-profile")
        .status()
        .unwrap();
    assert!(status.success());
}
#[tokio::test]
async fn child_has_explicit_sdk_credentials_only() {
    if std::env::var("OPENMATES_SDK_BOUNDARY_CHILD").as_deref() != Ok("1") {
        return;
    }
    let mut client = Client::new("https://api.example.org", None).unwrap();
    assert!(client.session().is_none());
    let (tx, _) = tokio::sync::mpsc::channel(1);
    assert!(matches!(
        client
            .send_message(None, "explicit input", tx, CancellationToken::new())
            .await,
        Err(Error::Authentication)
    ));
}
