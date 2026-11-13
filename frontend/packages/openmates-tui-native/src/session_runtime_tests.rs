//! CLI cache-load policy and the native credential adapter under the core
//! session runtime (`openmates_sdk::shell_session`).
use super::*;
#[test]
fn saved_chat_reads_load_only_their_chat_section() {
    let id = "22222222-2222-4222-8222-222222222222";
    let parse = |args: &[&str]| crate::cli::parse_from(args.iter().copied()).unwrap().invocation.unwrap();
    assert_eq!(command_cache_load(&parse(&["openmates", "chats", "show", id, "--json"])), CacheLoad::Chat(id.into()));
    assert_eq!(command_cache_load(&parse(&["openmates", "chats", "messages", id])), CacheLoad::Chat(id.into()));
    // Short IDs resolve through the full cache, as before.
    assert_eq!(command_cache_load(&parse(&["openmates", "chats", "show", "22222222"])), CacheLoad::Full);
    assert_eq!(command_cache_load(&parse(&["openmates", "chats", "list"])), CacheLoad::Index);
}
#[test]
fn only_canonical_selected_reads_overlap_admission() {
    let id = "22222222-2222-4222-8222-222222222222";
    let parse = |args: &[&str]| crate::cli::parse_from(args.iter().copied()).unwrap().invocation.unwrap();
    let overlapped = |args: &[&str]| overlapped_saved_read_chat(&parse(args)).map(str::to_owned);
    assert_eq!(overlapped(&["openmates", "chats", "show", id, "--json"]), Some(id.into()));
    assert_eq!(overlapped(&["openmates", "chats", "messages", id]), Some(id.into()));
    // Short IDs, API-key commands and other commands keep the ordinary path.
    assert_eq!(overlapped(&["openmates", "chats", "show", "22222222"]), None);
    assert_eq!(overlapped(&["openmates", "chats", "show", id, "--api-key", "synthetic-key"]), None);
    assert_eq!(overlapped(&["openmates", "chats", "list"]), None);
}
#[tokio::test]
async fn cleared_sdk_credentials_remove_durable_session_and_owner_cache() {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    let directory = builder.tempdir().unwrap();
    let store = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
        .await
        .unwrap();
    let session = Session {
        api_url: "https://api.example.test".into(),
        session_id: "synthetic-session".into(),
        cookies: std::collections::BTreeMap::new(),
        ws_token: None,
        master_key: Zeroizing::new([7; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new(&session.api_url.clone(), Some(session)).unwrap();
    let secret = Some(Zeroizing::new("synthetic vault password".to_owned()));
    persist(&mut client, &store, secret.clone()).await.unwrap();
    assert!(directory.path().join("session.json").exists());
    assert!(std::fs::read_dir(directory.path()).unwrap().any(|entry| {
        entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with("cache-")
    }));
    client.take_session();
    persist(&mut client, &store, secret).await.unwrap();
    assert!(store.load(None).await.unwrap().is_none());
    assert!(!directory.path().join("session.json").exists());
    assert!(!std::fs::read_dir(directory.path()).unwrap().any(|entry| {
        entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with("cache-")
    }));
}
