//! Isolated product evidence for the native public Docs CLI contract.
//! No signup, account credentials, model selection or AI inference is used.
use openmates::client::Client;
use serde_json::Value;
use std::{
    path::Path,
    process::{Command, Output},
};

fn cli(api: &str, state: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_openmates"))
        .args(["--api-url", api, "--state-dir", state.to_str().unwrap()])
        .args(args)
        // Public Docs must not select an account/API key from ambient state.
        .env("OPENMATES_API_KEY", "synthetic-invalid-public-docs-trap")
        .env_remove("OPENMATES_REQUIRE_TRUSTED_ACCOUNT")
        .env_remove("OPENMATES_ACCOUNT_GUARD")
        .stdin(std::process::Stdio::null())
        .output()
        .unwrap()
}
fn first_slug(tree: &Value) -> Option<&str> {
    tree["files"]
        .as_array()
        .into_iter()
        .flatten()
        .find_map(|file| file["slug"].as_str())
        .or_else(|| {
            tree["folders"]
                .as_array()
                .into_iter()
                .flatten()
                .find_map(first_slug)
        })
}
#[tokio::test]
#[ignore = "requires the isolated GitHub CI public documentation backend"]
// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible,cli.surface.semantic-parity
async fn native_public_docs_contract() {
    assert_eq!(
        std::env::var("CI").as_deref(),
        Ok("true"),
        "isolated GitHub CI only"
    );
    let api = std::env::var("RUST_TUI_API_URL").expect("isolated API required");
    let url = url::Url::parse(&api).unwrap();
    assert!(
        url.host_str()
            .is_some_and(|host| matches!(host, "127.0.0.1" | "[::1]")),
        "isolated literal loopback API only"
    );
    let temp = tempfile::tempdir().unwrap();
    let state = temp.path().join("unused-credentials");
    let listed = cli(&api, &state, &["docs", "list", "--json"]);
    assert!(
        listed.status.success(),
        "public docs list failed: {}",
        String::from_utf8_lossy(&listed.stderr)
    );
    let tree: Value = serde_json::from_slice(&listed.stdout).unwrap();
    let slug =
        first_slug(&tree).expect("isolated backend must publish at least one public document");
    let content = Client::new(&api, None)
        .unwrap()
        .get_doc(slug)
        .await
        .unwrap();
    let shown = cli(&api, &state, &["docs", "show", slug, "--json"]);
    assert!(shown.status.success());
    assert_eq!(
        String::from_utf8(shown.stdout).unwrap(),
        format!("{content}\n")
    );
    let query = content
        .split_whitespace()
        .find(|word| word.chars().any(char::is_alphanumeric))
        .expect("nonempty public fixture");
    let query = query.chars().take(100).collect::<String>();
    let search = cli(&api, &state, &["docs", "search", &query, "--json"]);
    assert!(search.status.success());
    assert!(
        serde_json::from_slice::<Value>(&search.stdout)
            .unwrap()
            .is_array()
    );
    let file = temp.path().join("document.md");
    let filename = file.to_str().unwrap();
    let downloaded = cli(
        &api,
        &state,
        &["docs", "download", slug, "--output", filename, "--json"],
    );
    assert!(downloaded.status.success());
    assert_eq!(
        String::from_utf8(downloaded.stdout).unwrap(),
        format!("Saved to {filename}\n")
    );
    assert_eq!(std::fs::read_to_string(&file).unwrap(), content);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            std::fs::metadata(&file).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
    let overwrite = cli(
        &api,
        &state,
        &["docs", "download", slug, "--output", filename],
    );
    assert_eq!(overwrite.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&overwrite.stderr).contains("do not overwrite"));
    assert_eq!(std::fs::read_to_string(&file).unwrap(), content);
    for family in ["docs", "wiki"] {
        let help = cli(&api, &state, &[family, "--json"]);
        assert!(help.status.success());
        assert!(String::from_utf8_lossy(&help.stdout).contains("commands:"));
        assert!(serde_json::from_slice::<Value>(&help.stdout).is_err());
    }
    assert!(
        !state.exists(),
        "public Docs/help must not create credential or profile state"
    );
    let unauthenticated = Command::new(env!("CARGO_BIN_EXE_openmates"))
        .args([
            "--api-url",
            &api,
            "--state-dir",
            state.to_str().unwrap(),
            "--encrypted-vault",
            "wiki",
            "search",
            "Synthetic article",
            "--json",
        ])
        .env_remove("OPENMATES_API_KEY")
        .env_remove("OPENMATES_REQUIRE_TRUSTED_ACCOUNT")
        .env_remove("OPENMATES_ACCOUNT_GUARD")
        .stdin(std::process::Stdio::null())
        .output()
        .unwrap();
    assert_eq!(unauthenticated.status.code(), Some(1));
    let error: Value = serde_json::from_slice(&unauthenticated.stderr).unwrap();
    assert_eq!(error["error"]["code"], "authentication_required");
}
