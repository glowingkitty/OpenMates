// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use std::collections::BTreeMap;

fn invocation(path: &str, flags: &[(&str, Value)]) -> Invocation {
    Invocation {
        path: path.split(' ').map(str::to_owned).collect(),
        positionals: vec![],
        flags: flags
            .iter()
            .map(|(k, v)| ((*k).into(), v.clone()))
            .collect::<BTreeMap<_, _>>(),
    }
}
fn private_write(path: &Path, value: &Value) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, value.to_string()).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
}

#[test]
fn disable_turns_off_npm_and_native_opt_ins_and_status_reports_unsupported() {
    let directory = tempfile::tempdir().unwrap();
    let paths = Paths {
        native: directory.path().join("native/privacy-preferences.json"),
        legacy: directory.path().join("legacy/privacy-preferences.json"),
        model_dir: directory.path().join("model/rev"),
    };
    let project = "aaaaaaaa-1111-4111-8111-aabbccddeeff";
    private_write(
        &paths.legacy,
        &json!({"version":1,"enabled":true,"documents":true,"projects":[project]}),
    );
    let status_json = execute_with(
        &invocation("privacy status", &[("json", json!(true))]),
        &paths,
    )
    .ok()
    .unwrap();
    let value: Value = serde_json::from_str(&status_json.stdout).unwrap();
    assert_eq!(
        (
            value["state"].as_str(),
            value["messages"].as_bool(),
            value["installed"].as_bool()
        ),
        (Some("unsupported"), Some(true), Some(false))
    );
    let out = execute_with(
        &invocation("privacy disable", &[("project", json!(project))]),
        &paths,
    )
    .ok()
    .unwrap();
    assert!(
        out.stdout
            .starts_with("Project enhanced scanning disabled.")
    );
    let out = execute_with(&invocation("privacy disable", &[]), &paths)
        .ok()
        .unwrap();
    assert!(
        out.stdout
            .starts_with("Message enhanced scanning disabled.")
    );
    let legacy: Value =
        serde_json::from_str(&std::fs::read_to_string(&paths.legacy).unwrap()).unwrap();
    assert_eq!(
        (legacy["enabled"].clone(), legacy["projects"].clone()),
        (json!(false), json!([]))
    );
    let native: Value =
        serde_json::from_str(&std::fs::read_to_string(&paths.native).unwrap()).unwrap();
    assert_eq!(native["enabled"], false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            std::fs::metadata(&paths.native)
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }
    std::fs::create_dir_all(&paths.model_dir).unwrap();
    std::fs::write(paths.model_dir.join("model.gguf"), b"x").unwrap();
    execute_with(
        &invocation("privacy remove", &[("yes", json!(true))]),
        &paths,
    )
    .ok()
    .unwrap();
    assert!(!paths.model_dir.exists());
    assert!(matches!(
        execute(&invocation("privacy disable", &[("project", json!("short"))])),
        Err(CliError::Invalid(m)) if m == "Use the full Project ID for its local privacy setting."
    ));
}

#[test]
fn bare_privacy_reports_status_like_npm() {
    let directory = tempfile::tempdir().unwrap();
    let paths = Paths {
        native: directory.path().join("native/privacy-preferences.json"),
        legacy: directory.path().join("legacy/privacy-preferences.json"),
        model_dir: directory.path().join("model/rev"),
    };
    assert!(supported(&invocation("privacy", &[])));
    let bare = execute_with(&invocation("privacy", &[]), &paths).ok().unwrap();
    let status = execute_with(&invocation("privacy status", &[]), &paths).ok().unwrap();
    assert_eq!(bare.stdout, status.stdout);
    // Installation and enabling need the packaged offline runtime.
    for command in ["privacy install", "privacy update", "privacy enable"] {
        assert!(!supported(&invocation(command, &[])), "{command}");
    }
}
