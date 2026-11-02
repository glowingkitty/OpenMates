//! CI-only cross-process peer. No fake credential backend, API, account or AI.
//! Run only via native-keyring-ci.py inside the admitted isolated GitHub runner.
#![cfg(target_os = "linux")]
use openmates_tui_native::storage::{Session, StorageMode, Store};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fs, os::unix::fs::MetadataExt, path::PathBuf};
use zeroize::Zeroizing;
fn synthetic_session() -> Session {
    Session {
        api_url: "https://native-keyring-fixture.invalid".into(),
        session_id: "synthetic-session-not-an-account".into(),
        cookies: BTreeMap::from([("session".into(), "synthetic-cookie".into())]),
        ws_token: Some("synthetic-websocket-token".into()),
        master_key: Zeroizing::new([37; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: "synthetic-salt".into(),
        email_encryption_key: Some("synthetic-email-key".into()),
        created_at: 1234, paired_session_expires_at: None, active_team_id: None,
    }
}
#[test]
#[ignore = "real packaged provider; isolated GitHub native-keyring-ci harness only"]
fn real_native_keyring_peer() {
    for (key,value) in [("CI","true"),("GITHUB_ACTIONS","true"),
        ("RUNNER_ENVIRONMENT","github-hosted"),("OPENMATES_CI_ISOLATED","1")] {
        assert_eq!(std::env::var(key).as_deref(), Ok(value));
    }
    let path=PathBuf::from(std::env::var_os("OPENMATES_KEYRING_CI_PROFILE").unwrap());
    assert!(path.is_absolute());
    let info=fs::symlink_metadata(&path).unwrap();
    assert!(info.is_dir() && info.mode() & 0o077 == 0);
    assert_eq!(fs::canonicalize(&path).unwrap(),path);
    let action=std::env::var("OPENMATES_KEYRING_CI_ACTION").unwrap();
    let store=Store::new(path.clone()).unwrap(); // Production NativeKeyring + lifetime lock.
    match action.as_str() {
        "save" => {
            store.save_session(&synthetic_session(),None).unwrap();
            assert_eq!(store.storage_mode().unwrap(),Some(StorageMode::OsKeyring));
        },
        "read" => {
            assert_eq!(store.storage_mode().unwrap(),Some(StorageMode::OsKeyring));
            let session=store.load_session(None).unwrap().unwrap();
            assert_eq!(session.session_id,"synthetic-session-not-an-account");
            assert_eq!(*session.master_key, [37;32]);
        },
        "fail-closed" => {
            let before=fs::read(path.join("session.json")).unwrap();
            assert!(store.load_session(None).is_err());
            let mut replacement=synthetic_session();
            replacement.session_id="must-never-replace-existing-entry".into();
            assert!(store.save_session(&replacement,None).is_err());
            assert_eq!(fs::read(path.join("session.json")).unwrap(),before);
            assert_eq!(store.storage_mode().unwrap(),Some(StorageMode::OsKeyring));
        },
        "clear" => {
            store.clear_session().unwrap();
            assert!(store.load_session(None).unwrap().is_none());
            let account=format!("{:x}",Sha256::digest(path.as_os_str().as_encoded_bytes()));
            assert!(matches!(keyring::Entry::new("OpenMates Rust TUI",&account).unwrap()
                .get_secret(), Err(keyring::Error::NoEntry)));
        },
        _ => panic!("unknown CI peer action"),
    }
    assert!(!path.join("credential-key").exists());
}
