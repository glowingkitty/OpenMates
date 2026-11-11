//! Behaviour of `FileByteStore`: private modes, symlink refusal, atomic writes,
//! listing, deletion, size ceiling and locks.
use super::*;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::{path::Path, time::Duration};

fn store() -> (tempfile::TempDir, FileByteStore) {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let store = FileByteStore::open(directory.path()).unwrap();
    (directory, store)
}

#[test]
fn put_then_get_roundtrips_with_private_file_mode() {
    let (directory, store) = store();
    store.put("a.json", b"one", Durability::Now).unwrap();
    store
        .put("a.json", b"two", Durability::AfterBarrier)
        .unwrap();
    store.barrier().unwrap();
    assert_eq!(store.get("a.json").unwrap().unwrap(), b"two");
    let mode = std::fs::metadata(directory.path().join("a.json"))
        .unwrap()
        .permissions()
        .mode();
    assert_eq!(mode & 0o777, 0o600);
    assert_eq!(store.get("missing").unwrap(), None);
}

#[test]
fn failed_write_leaves_no_temporary_file() {
    let (directory, store) = store();
    store.put("a.json", b"one", Durability::Now).unwrap();
    let failed = store.put_file_hooked("a.json", b"two", true, || Err(ByteStoreError::Io));
    assert!(failed.is_err());
    let names: Vec<_> = std::fs::read_dir(directory.path())
        .unwrap()
        .map(|entry| entry.unwrap().file_name().into_string().unwrap())
        .collect();
    assert_eq!(names, ["a.json"]);
}

#[test]
fn symlinked_or_nonprivate_records_are_refused() {
    let (directory, store) = store();
    store.put("real.json", b"x", Durability::Now).unwrap();
    symlink(
        directory.path().join("real.json"),
        directory.path().join("link.json"),
    )
    .unwrap();
    assert!(store.get("link.json").is_err());
    assert!(store.put("link.json", b"y", Durability::Now).is_err());
    std::fs::set_permissions(
        directory.path().join("real.json"),
        std::fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    assert_eq!(store.get("real.json"), Err(ByteStoreError::NotPrivate));
}

#[test]
fn open_refuses_relative_unnormalized_and_nonprivate_directories() {
    assert_eq!(
        FileByteStore::open(Path::new("relative")).err(),
        Some(ByteStoreError::RelativePath)
    );
    let (directory, _store) = store();
    assert_eq!(
        FileByteStore::open(&directory.path().join("a").join("..")).err(),
        Some(ByteStoreError::NonNormalizedPath)
    );
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o755)).unwrap();
    assert!(FileByteStore::open(directory.path()).is_err());
}

#[test]
fn open_creates_missing_directories_privately_and_refuses_a_symlinked_leaf() {
    let (directory, _store) = store();
    let nested = directory.path().join("x").join("y");
    FileByteStore::open(&nested).unwrap();
    assert_eq!(
        std::fs::metadata(&nested).unwrap().permissions().mode() & 0o777,
        0o700
    );
    symlink(&nested, directory.path().join("link")).unwrap();
    assert!(FileByteStore::open(&directory.path().join("link")).is_err());
}

#[test]
fn names_with_separators_are_refused_for_writes() {
    let (_directory, store) = store();
    assert!(store.put("../escape", b"x", Durability::Now).is_err());
    assert!(store.put("a/b", b"x", Durability::Now).is_err());
}

#[test]
fn oversized_records_are_refused_on_read_but_can_be_deleted() {
    let (directory, store) = store();
    store.put("big.json", b"x", Durability::Now).unwrap();
    let file = std::fs::OpenOptions::new()
        .write(true)
        .open(directory.path().join("big.json"))
        .unwrap();
    file.set_len(MAX_LOCAL_RECORD_BYTES as u64 + 1).unwrap();
    assert_eq!(store.get("big.json"), Err(ByteStoreError::TooLarge));
    store.delete("big.json").unwrap();
    store.delete("big.json").unwrap();
    assert_eq!(store.get("big.json").unwrap(), None);
}

#[test]
fn list_returns_only_names_with_the_prefix() {
    let (_directory, store) = store();
    for name in ["cache-a-1.json", "cache-a-2.json", "cache-b-1.json"] {
        store.put(name, b"x", Durability::Now).unwrap();
    }
    let mut names = store.list("cache-a-").unwrap();
    names.sort();
    assert_eq!(names, ["cache-a-1.json", "cache-a-2.json"]);
}

#[test]
fn version_changes_when_a_record_is_replaced_even_with_equal_bytes() {
    let (_directory, store) = store();
    assert_eq!(store.version("a.json").unwrap(), None);
    store.put("a.json", b"same", Durability::Now).unwrap();
    let first = store.version("a.json").unwrap().unwrap();
    assert_eq!(first.len(), 4);
    store.put("a.json", b"same", Durability::Now).unwrap();
    assert_ne!(store.version("a.json").unwrap().unwrap(), first);
}

#[test]
fn locks_exclude_other_holders_until_dropped() {
    let (_directory, store) = store();
    let held = store.lock("scope.lock").unwrap();
    assert_eq!(
        store.try_lock("scope.lock").err(),
        Some(ByteStoreError::WouldBlock)
    );
    assert_eq!(
        store
            .lock_timeout("scope.lock", Duration::from_millis(60))
            .err(),
        Some(ByteStoreError::WouldBlock)
    );
    drop(held);
    store.try_lock("scope.lock").unwrap();
}

#[test]
fn sync_requires_an_existing_record() {
    let (_directory, store) = store();
    assert!(store.sync("missing").is_err());
    store.put("a.json", b"x", Durability::Now).unwrap();
    store.sync("a.json").unwrap();
}
