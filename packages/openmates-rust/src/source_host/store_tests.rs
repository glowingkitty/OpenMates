//! `remote-sources.json` compatibility with the npm CLI store and owner-only permissions.
use super::store::{
    StoredRemoteSource, load_remote_sources, npm_state_dir, remote_cache_path, remote_source_type,
    upsert_remote_source,
};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

fn record(state: &Path, id: &str) -> StoredRemoteSource {
    StoredRemoteSource {
        source_id: id.to_owned(),
        project_id: Some("project-1".to_owned()),
        source_type: "local_folder".to_owned(),
        root_path: "/srv/example".to_owned(),
        display_name: "example".to_owned(),
        cache_path: remote_cache_path(state, id).expect("safe id").display().to_string(),
        status: "connected".to_owned(),
        created_at: 1,
        updated_at: 2,
        extra: serde_json::Map::new(),
    }
}

#[test]
fn reads_npm_written_records_and_keeps_unknown_fields() {
    let state = tempfile::tempdir().expect("tempdir");
    std::fs::write(
        state.path().join("remote-sources.json"),
        r#"{"sources":[{"sourceId":"src-1","sourceType":"local_git_repository","rootPath":"/r","displayName":"r","cachePath":"/c","status":"offline","createdAt":5,"updatedAt":6,"futureField":true}]}"#,
    )
    .expect("write");
    let sources = load_remote_sources(state.path()).expect("loads");
    assert_eq!(sources.len(), 1);
    assert_eq!(sources[0].project_id, None);
    assert_eq!(sources[0].extra["futureField"], true);
    let encoded = serde_json::to_value(&sources[0]).expect("encodes");
    assert_eq!(encoded["futureField"], true);
    assert_eq!(encoded["rootPath"], "/r");
    assert!(encoded.get("projectId").is_none());
}

#[test]
fn upsert_replaces_by_id_with_owner_only_files() {
    let state = tempfile::tempdir().expect("tempdir");
    let dir = state.path().join("profile");
    upsert_remote_source(&dir, record(&dir, "a")).expect("upserts");
    upsert_remote_source(&dir, record(&dir, "b")).expect("upserts");
    let mut changed = record(&dir, "a");
    changed.status = "revoked".to_owned();
    upsert_remote_source(&dir, changed).expect("upserts");
    let sources = load_remote_sources(&dir).expect("loads");
    assert_eq!(sources.iter().map(|s| s.source_id.as_str()).collect::<Vec<_>>(), vec!["b", "a"]);
    assert_eq!(sources[1].status, "revoked");
    let mode = |p: &Path| std::fs::metadata(p).expect("stat").permissions().mode() & 0o777;
    assert_eq!(mode(&dir), 0o700);
    assert_eq!(mode(&dir.join("remote-sources.json")), 0o600);
    assert_eq!(mode(&dir.join("remote-cache/a")), 0o700);
    let text = std::fs::read_to_string(dir.join("remote-sources.json")).expect("read");
    assert!(text.ends_with("}\n"));
}

#[test]
fn rejects_invalid_records_and_unsafe_ids() {
    let state = tempfile::tempdir().expect("tempdir");
    std::fs::write(state.path().join("remote-sources.json"), r#"{"sources":[{"sourceId":"x"}]}"#).expect("write");
    assert!(load_remote_sources(state.path()).is_err());
    assert!(remote_cache_path(state.path(), "../escape").is_err());
    assert!(remote_cache_path(state.path(), ".hidden").is_err());
    assert!(load_remote_sources(&state.path().join("missing")).expect("empty").is_empty());
}

#[test]
fn state_dir_follows_npm_resolution() {
    let home = Path::new("/home/u");
    assert_eq!(npm_state_dir(None, None, Some(home)).expect("dir"), home.join(".openmates"));
    assert_eq!(
        npm_state_dir(None, Some("work-2"), Some(home)).expect("dir"),
        home.join(".openmates/profiles/work-2")
    );
    assert_eq!(npm_state_dir(Some("/tmp/s"), Some("x"), None).expect("dir"), Path::new("/tmp/s"));
    assert!(npm_state_dir(Some("relative"), None, Some(home)).is_err());
    assert!(npm_state_dir(None, Some("Bad"), Some(home)).is_err());
}

#[test]
fn git_roots_are_typed_as_repositories() {
    let root = tempfile::tempdir().expect("tempdir");
    assert_eq!(remote_source_type(root.path()), "local_folder");
    std::fs::create_dir(root.path().join(".git")).expect("git");
    assert_eq!(remote_source_type(root.path()), "local_git_repository");
}
