//! Runner-local real native binary package identity and version compatibility.
//! Empty PATH and private state preserve the source-install probe boundary.
use serde_json::Value;
use std::{path::Path, process::{Command, Stdio}};

fn version(state: &Path, args: &[&str]) -> Vec<u8> {
    let output = Command::new(env!("CARGO_BIN_EXE_openmates"))
        .args(args)
        .current_dir(state.join("work"))
        .env_clear()
        .env("PATH", state.join("empty-path"))
        .env("HOME", state.join("state"))
        .env("LANG", "C.UTF-8")
        .env("XDG_CONFIG_HOME", state.join("state"))
        .env("XDG_DATA_HOME", state.join("state"))
        .env("XDG_CACHE_HOME", state.join("state"))
        .env("OPENMATES_STATE_DIR", state.join("state"))
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    output.stdout
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.surface.semantic-parity
#[test]
fn actual_native_version_flag_identifies_package_and_preserves_public_version_details() {
    let temporary = tempfile::tempdir().unwrap();
    let state = temporary.path();
    for directory in ["work", "empty-path", "state"] {
        std::fs::create_dir(state.join(directory)).unwrap();
    }
    let identity = format!("OpenMates CLI {} (Rust)\n", env!("CARGO_PKG_VERSION"));
    for flag in ["--version", "-version"] {
        assert_eq!(version(state, &[flag]), identity.as_bytes());
    }
    assert_eq!(
        version(state, &["version"]),
        format!("{identity}Native update availability check is not implemented yet.\n").as_bytes()
    );
    let global: Value = serde_json::from_slice(&version(state, &["--version", "--json"])).unwrap();
    let command: Value = serde_json::from_slice(&version(state, &["version", "--json"])).unwrap();
    assert_eq!(global, command);
    assert_eq!(global["command"], "version");
    assert_eq!(global["current_version"], env!("CARGO_PKG_VERSION"));
    assert_eq!(global["implementation"], "rust");
    assert!(global["check_error"].is_string());
    for field in ["latest_version", "update_available", "upgrade_command"] {
        assert!(global.as_object().unwrap().contains_key(field));
        assert!(global[field].is_null());
    }
}
