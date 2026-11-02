//! CI-only real native executable. A new saved-context library method must not
//! silently enable API-key-only CLI sharing before Cookie/prefix parity exists.
use std::process::{Command, Stdio};
// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.surface.semantic-parity
#[test]
fn native_share_remains_explicitly_unsupported_without_foreign_runtime_or_network() {
    let state = tempfile::tempdir().unwrap();
    let key = format!("sk-api-{}.{}", "b".repeat(32), "s".repeat(32));
    for id in ["33333333", "33333333-3333-4333-8333-333333333333"] {
        let output = Command::new(env!("CARGO_BIN_EXE_openmates"))
            .env_clear()
            .env("PATH", "")
            .env("HOME", state.path())
            .env("XDG_CONFIG_HOME", state.path())
            .env("XDG_DATA_HOME", state.path())
            .env("XDG_CACHE_HOME", state.path())
            .env("OPENMATES_STATE_DIR", state.path())
            .env("LANG", "C.UTF-8")
            .args([
                "--api-url",
                "http://127.0.0.1:9",
                "--api-key",
                &key,
                "embeds",
                "share",
                id,
                "--json",
            ])
            .stdin(Stdio::null())
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(1));
        assert!(output.stdout.is_empty());
        let error: serde_json::Value = serde_json::from_slice(&output.stderr).unwrap();
        assert_eq!(error["error"]["code"], "native_command_unsupported");
        assert!(!String::from_utf8_lossy(&output.stderr).contains("#key="));
        assert!(!String::from_utf8_lossy(&output.stderr).contains(&key));
    }
}
