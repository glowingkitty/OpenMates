// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
//! Fixed vectors were produced by the npm CLI's own
//! `remoteCommandPermissions.ts` (`parseRemoteCommandPermissions`,
//! `remoteCommandPresetDigest`) and `JSON.stringify` resource digests under
//! Node 24, so both CLIs authorize byte-identical definitions.
use super::permissions::posix_normalize;
use super::*;
use serde_json::{Value, json};
use std::path::Path;

const FIXTURE: &str = r#"schema_version: 1
file_access:
  private_paths:
    - ./secrets/
presets:
  - id: tests
    label: Run tests
    commands:
      - argv: [cargo, test, "--", "ünïcode"]
        cwd: ./crates/core
        deadline_ms: 60000
        writable_profiles: [target-cache]
        network_profile: registry
        credential_profiles: [registry-token]
      - argv: [cargo, fmt, --check]
  - id: lint
    label: Lint
    commands:
      - argv: [cargo, clippy]
        mode: background
resource_profiles:
  writable:
    - id: target-cache
      purpose: cache
    - id: unused-output
      purpose: output
  network:
    - id: registry
      destinations: [Crates.io, "index.crates.io:443"]
  credentials:
    - id: registry-token
      environment: [CARGO_REGISTRY_TOKEN, _EXTRA]
"#;
const NPM_PARSED: &str = r#"{"schema_version":1,"file_access":{"private_paths":["secrets/"]},"presets":[{"id":"tests","label":"Run tests","commands":[{"argv":["cargo","test","--","ünïcode"],"cwd":"crates/core","mode":"foreground","source_access":"read_only","deadline_ms":60000,"writable_profiles":["target-cache"],"network_profile":"registry","credential_profiles":["registry-token"]},{"argv":["cargo","fmt","--check"],"cwd":".","mode":"foreground","source_access":"read_only","deadline_ms":600000,"writable_profiles":[],"network_profile":null,"credential_profiles":[]}]},{"id":"lint","label":"Lint","commands":[{"argv":["cargo","clippy"],"cwd":".","mode":"background","source_access":"read_only","deadline_ms":600000,"writable_profiles":[],"network_profile":null,"credential_profiles":[]}]}],"resource_profiles":{"writable":[{"id":"target-cache","purpose":"cache"},{"id":"unused-output","purpose":"output"}],"network":[{"id":"registry","destinations":["crates.io","index.crates.io:443"]}],"credentials":[{"id":"registry-token","environment":["CARGO_REGISTRY_TOKEN","_EXTRA"]}]}}"#;
const TESTS_DIGEST: &str = "9cca58614169f58bb7024291ce1e0a1675a73a7f9ff3d92a40db2fd62f5c2198";
const LINT_DIGEST: &str = "b6406fdb0782129cb5c1c106637fe402c0016dd8c9aa7814c805dde61faa1b46";
const PROJECT: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";

fn fixture() -> RemoteCommandPermissions {
    parse_remote_command_permissions(FIXTURE).unwrap()
}
fn project_root() -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join(".openmates")).unwrap();
    std::fs::write(root.path().join(REMOTE_COMMAND_PERMISSIONS_PATH), FIXTURE).unwrap();
    root
}
#[cfg(unix)]
fn mode(path: &Path) -> u32 {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(path).unwrap().permissions().mode() & 0o777
}

#[test]
fn permissions_parse_to_the_npm_normalized_definition() {
    assert_eq!(serde_json::to_string(&fixture()).unwrap(), NPM_PARSED);
}

#[test]
fn preset_and_resource_digests_match_npm_vectors() {
    let config = fixture();
    assert_eq!(
        remote_command_preset_digest(&config, "tests").unwrap(),
        TESTS_DIGEST
    );
    assert_eq!(
        remote_command_preset_digest(&config, "lint").unwrap(),
        LINT_DIGEST
    );
    assert_eq!(
        remote_command_preset_digest(&config, "missing")
            .unwrap_err()
            .message,
        "Unknown command preset: missing"
    );
    let resources = &config.resource_profiles;
    assert_eq!(
        resource_definition_digest("writable", &resources.writable[0]).unwrap(),
        "5f370fec9a26df759e03a58cc680b609623a9123d3895358d62c8d40dccd6665"
    );
    assert_eq!(
        resource_definition_digest("network", &resources.network[0]).unwrap(),
        "739717e92bb68d394270f2ca8e6712ef329768e7c1b447c264bc5d00c131181d"
    );
    assert_eq!(
        resource_definition_digest("credential", &resources.credentials[0]).unwrap(),
        "6e7d046afe562e49d44cab469f69aa473b4b4bfec78a14443a877c0575b71421"
    );
}

#[test]
fn stable_json_uses_locale_compare_key_order_and_json_escaping() {
    let value = json!({"b":1,"B":2,"a":[{"z":null,"_y":true}],"_x":"\u{2028}\"\n","a-b":1.5,"ab":0,"A":"é","10":1,"9":2});
    assert_eq!(
        stable_json(&value).unwrap(),
        "{\"_x\":\"\u{2028}\\\"\\n\",\"10\":1,\"9\":2,\"a\":[{\"_y\":true,\"z\":null}],\"A\":\"é\",\"a-b\":1.5,\"ab\":0,\"b\":1,\"B\":2}"
    );
}

#[test]
fn invalid_permissions_report_the_npm_messages() {
    let preset = |command: &str| {
        format!("schema_version: 1\npresets:\n  - id: a\n    label: x\n    commands: [{command}]")
    };
    let cases = [
        ("schema_version: 2\npresets: []".to_owned(), "schema_version must be 1"),
        (
            "schema_version: 1\npresets: []\nextra: 1".to_owned(),
            "permissions contains unknown key: extra",
        ),
        (
            "schema_version: 1\npresets:\n  - id: Bad\n    label: x\n    commands: [{argv: [a]}]"
                .to_owned(),
            "presets[0].id is not a valid identifier",
        ),
        (
            preset("{argv: [a], writable_profiles: [nope]}"),
            "Unknown writable profile: nope",
        ),
        (
            preset("{argv: [a], mode: background, source_access: read_write}"),
            "presets[0].commands[0]: background commands must use read_only source access",
        ),
        (
            preset("{argv: [a], cwd: ../up}"),
            "presets[0].commands[0].cwd must be a normalized Project-relative path",
        ),
        (
            preset("{argv: [a], deadline_ms: 50}"),
            "presets[0].commands[0].deadline_ms must be 100-86400000",
        ),
        (
            "schema_version: 1\npresets:\n  - id: a\n    label: x\n    commands: [{argv: [a]}]\n  - id: a\n    label: y\n    commands: [{argv: [b]}]"
                .to_owned(),
            "preset contains duplicate values",
        ),
    ];
    for (document, message) in cases {
        let error = parse_remote_command_permissions(&document).unwrap_err();
        assert_eq!(
            (error.code, error.message.as_str()),
            ("command_failed", message)
        );
    }
    // `Number.isSafeInteger(1.0)` is true in npm.
    assert!(parse_remote_command_permissions("schema_version: 1.0\npresets: []").is_ok());
}

#[test]
fn posix_normalize_matches_node() {
    for (input, expected) in [
        ("", "."),
        ("./", "./"),
        ("a/./b/../c/", "a/c/"),
        ("../a", "../a"),
        ("a/../..", ".."),
        ("/a/../..", "/"),
        ("a//b", "a/b"),
    ] {
        assert_eq!(posix_normalize(input), expected, "{input}");
    }
}

#[test]
fn permissions_load_from_the_source_and_refuse_symlinks() {
    let root = project_root();
    assert_eq!(
        load_remote_command_permissions(root.path()).unwrap(),
        Some(fixture())
    );
    let empty = tempfile::tempdir().unwrap();
    assert_eq!(load_remote_command_permissions(empty.path()).unwrap(), None);
    #[cfg(unix)]
    {
        let linked = tempfile::tempdir().unwrap();
        std::fs::create_dir(linked.path().join(".openmates")).unwrap();
        std::os::unix::fs::symlink(
            root.path().join(REMOTE_COMMAND_PERMISSIONS_PATH),
            linked.path().join(REMOTE_COMMAND_PERMISSIONS_PATH),
        )
        .unwrap();
        assert_eq!(
            load_remote_command_permissions(linked.path())
                .unwrap_err()
                .message,
            ".openmates/permissions.yml must be a regular file"
        );
    }
}

#[test]
fn preset_grants_round_trip_privately() {
    let root = project_root();
    let state = tempfile::tempdir().unwrap();
    assert!(list_preset_grants(state.path()).unwrap().is_empty());
    let grant = enable_preset_grant(state.path(), PROJECT, root.path(), "tests").unwrap();
    assert_eq!(
        grant,
        PresetGrant {
            project_id: PROJECT.into(),
            preset_id: "tests".into(),
            definition_digest: TESTS_DIGEST.into(),
            enabled: true,
        }
    );
    let path = state.path().join(PRESET_GRANTS_FILE);
    let stored: Value = serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
    assert_eq!(
        stored,
        json!({"version":1,"grants":[{"project_id":PROJECT,"preset_id":"tests","definition_digest":TESTS_DIGEST,"enabled":true}]})
    );
    assert!(std::fs::read_to_string(&path).unwrap().ends_with("}\n"));
    #[cfg(unix)]
    {
        assert_eq!(mode(&path), 0o600);
        assert_eq!(mode(state.path()), 0o700);
    }
    assert_eq!(list_preset_grants(state.path()).unwrap(), vec![grant]);
    disable_preset_grant(state.path(), PROJECT, "tests").unwrap();
    assert!(list_preset_grants(state.path()).unwrap().is_empty());
    assert_eq!(
        disable_preset_grant(state.path(), "", "tests")
            .unwrap_err()
            .message,
        "invalid project_id"
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert_eq!(
            list_preset_grants(state.path()).unwrap_err().message,
            "Remote command preset grant store is not private"
        );
    }
}

#[test]
fn resource_grants_store_names_only_and_validate_definitions() {
    let root = project_root();
    let state = tempfile::tempdir().unwrap();
    let host = tempfile::tempdir().unwrap();
    let config = fixture();
    enable_network_grant(state.path(), PROJECT, "src-1", &config, "registry").unwrap();
    let mapping = [
        ("_EXTRA".to_owned(), "LOCAL_EXTRA".to_owned()),
        ("CARGO_REGISTRY_TOKEN".to_owned(), "MY_TOKEN".to_owned()),
    ];
    enable_credential_grant(
        state.path(),
        PROJECT,
        "src-1",
        &config,
        "registry-token",
        &mapping,
    )
    .unwrap();
    assert_eq!(
        enable_credential_grant(
            state.path(),
            PROJECT,
            "src-1",
            &config,
            "registry-token",
            &mapping[..1]
        )
        .unwrap_err()
        .message,
        "Credential profile requires mappings for: CARGO_REGISTRY_TOKEN, _EXTRA"
    );
    assert_eq!(
        enable_writable_grant(
            state.path(),
            PROJECT,
            "src-1",
            root.path(),
            &config,
            "target-cache",
            root.path().join("sub").to_str().unwrap()
        )
        .unwrap_err()
        .code,
        "command_failed"
    );
    assert_eq!(
        enable_writable_grant(
            state.path(),
            PROJECT,
            "src-1",
            root.path(),
            &config,
            "target-cache",
            "relative/dir"
        )
        .unwrap_err()
        .message,
        "--host-path must be absolute"
    );
    std::fs::create_dir(root.path().join("inside")).unwrap();
    assert_eq!(
        enable_writable_grant(
            state.path(),
            PROJECT,
            "src-1",
            root.path(),
            &config,
            "target-cache",
            root.path().join("inside").to_str().unwrap()
        )
        .unwrap_err()
        .message,
        "Writable profile cannot overlap the Project source"
    );
    enable_writable_grant(
        state.path(),
        PROJECT,
        "src-1",
        root.path(),
        &config,
        "target-cache",
        host.path().to_str().unwrap(),
    )
    .unwrap();
    let stored = std::fs::read_to_string(state.path().join(RESOURCE_GRANTS_FILE)).unwrap();
    assert!(stored.contains("\"MY_TOKEN\""));
    #[cfg(unix)]
    assert_eq!(mode(&state.path().join(RESOURCE_GRANTS_FILE)), 0o600);
    let listed = list_resource_grants(state.path(), Some(PROJECT), Some("src-1")).unwrap();
    assert_eq!(listed.len(), 3);
    let credential = listed
        .iter()
        .find(|grant| grant["kind"] == "credential")
        .unwrap();
    assert_eq!(
        credential["environment_names"],
        json!(["CARGO_REGISTRY_TOKEN", "_EXTRA"])
    );
    assert!(credential.get("environment_sources").is_none());
    assert!(!serde_json::to_string(&listed).unwrap().contains("MY_TOKEN"));
    assert!(
        list_resource_grants(state.path(), Some(PROJECT), Some("other"))
            .unwrap()
            .is_empty()
    );
    disable_resource_grant(
        state.path(),
        PROJECT,
        "src-1",
        ResourceKind::Network,
        "registry",
    )
    .unwrap();
    let listed = list_resource_grants(state.path(), None, None).unwrap();
    assert_eq!(listed.len(), 2);
    assert!(listed.iter().all(|grant| grant["kind"] != "network"));
    assert_eq!(
        disable_resource_grant(state.path(), PROJECT, "src-1", ResourceKind::Network, "Bad")
            .unwrap_err()
            .message,
        "Invalid remote command resource grant identity"
    );
    assert_eq!(
        ResourceKind::parse("credential"),
        Some(ResourceKind::Credential)
    );
    assert_eq!(ResourceKind::parse("credentials"), None);
}

fn source(id: &str, project: Option<&str>, root: &str) -> Value {
    let mut value = json!({
        "sourceId": id, "sourceType": "local_folder", "rootPath": root,
        "displayName": id, "cachePath": "/tmp/cache", "status": "connected",
        "createdAt": 1, "updatedAt": 2,
    });
    if let Some(project) = project {
        value["projectId"] = json!(project);
    }
    value
}

#[test]
fn source_store_is_validated_and_selection_needs_exactly_one_match() {
    let state = tempfile::tempdir().unwrap();
    assert!(list_remote_access_sources(state.path()).unwrap().is_empty());
    let path = state.path().join(REMOTE_SOURCES_FILE);
    std::fs::write(
        &path,
        json!({"sources":[source("one", Some(PROJECT), "/a"), source("two", Some(PROJECT), "/b"), source("three", None, "/c")]})
            .to_string(),
    )
    .unwrap();
    let sources = list_remote_access_sources(state.path()).unwrap();
    assert_eq!(sources.len(), 3);
    let required = select_remote_command_source(sources.clone(), PROJECT, None, None).unwrap_err();
    assert_eq!(
        (required.code, required.message.as_str()),
        (
            "source_selection_required",
            "Select one attached local source with --source <source-id> or --path <folder>."
        )
    );
    assert_eq!(
        select_remote_command_source(sources.clone(), PROJECT, Some("two"), None)
            .unwrap()
            .root_path,
        "/b"
    );
    assert_eq!(
        select_remote_command_source(sources.clone(), PROJECT, None, Some("/a"))
            .unwrap()
            .source_id,
        "one"
    );
    assert!(select_remote_command_source(sources, PROJECT, Some("three"), None).is_err());
    let mut broken = source("one", Some(PROJECT), "/a");
    broken["status"] = json!("unknown");
    std::fs::write(&path, json!({"sources":[broken]}).to_string()).unwrap();
    assert_eq!(
        list_remote_access_sources(state.path())
            .unwrap_err()
            .message,
        format!(
            "Failed to read remote source store at {}: Remote source record 0 is invalid",
            path.display()
        )
    );
}
