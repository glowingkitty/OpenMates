use super::*;
use std::os::unix::fs::{PermissionsExt, symlink};

fn preferences(path: &Path, enabled: bool) {
    fs::write(
        path,
        json!({"version":1,"enabled":enabled,"documents":false,"projects":[]}).to_string(),
    )
    .unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}

#[test]
fn enhanced_preferences_fail_closed_without_native_model() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("preferences.json");
    assert!(verify_preferences_path(&path).is_ok());
    preferences(&path, false);
    assert!(verify_preferences_path(&path).is_ok());
    preferences(&path, true);
    let error = verify_preferences_path(&path).unwrap_err();
    assert!(error.to_string().contains("enabled but unavailable"));
    fs::write(&path, "not json").unwrap();
    assert!(verify_preferences_path(&path).is_err());
    preferences(&path, false);
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    assert!(verify_preferences_path(&path).is_err());
    fs::remove_file(&path).unwrap();
    let target = directory.path().join("target.json");
    preferences(&target, false);
    symlink(target, &path).unwrap();
    assert!(verify_preferences_path(&path).is_err());
}

#[test]
fn invalid_preferences_never_fall_back_to_disabled() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("preferences.json");
    for invalid in [
        json!({"version":2,"enabled":false,"documents":false,"projects":[]}),
        json!({"version":1,"enabled":"false","documents":false,"projects":[]}),
        json!({"version":1,"enabled":false,"documents":false,"projects":["not-an-id"]}),
    ] {
        fs::write(&path, invalid.to_string()).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        assert!(verify_preferences_path(&path).is_err());
    }
}
