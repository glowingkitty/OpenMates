use super::*;

fn open_blob(blob: &str, key: &[u8; 32]) -> String {
    let bytes = URL_SAFE_NO_PAD.decode(blob).unwrap();
    String::from_utf8(
        crypto::decrypt_aead(&bytes[12..], key, &bytes[..12], &[])
            .unwrap()
            .to_vec(),
    )
    .unwrap()
}

#[test]
fn share_wire_blob_has_canonical_fields_and_optional_password_layer() {
    let id = "11111111-1111-4111-8111-111111111111";
    let key = [42; 32];
    let timestamp = 1234567890;
    let outer = password_key(id, b"openmates-share-v1");
    for password in ["", "secret"] {
        let blob = share_blob(id, &key, 86400, password, timestamp).unwrap();
        let fields: std::collections::BTreeMap<String, String> =
            url::form_urlencoded::parse(open_blob(&blob, &outer).as_bytes())
                .into_owned()
                .collect();
        assert_eq!(fields.len(), 4);
        assert_eq!(fields["duration_seconds"], "86400");
        assert_eq!(fields["generated_at"], timestamp.to_string());
        if password.is_empty() {
            assert_eq!(fields["pwd"], "0");
            assert_eq!(fields["chat_encryption_key"], crypto::encode_key(&key));
        } else {
            assert_eq!(fields["pwd"], "1");
            let salt = format!("openmates-pwd-{id}");
            let inner = password_key(password, salt.as_bytes());
            assert_eq!(
                open_blob(&fields["chat_encryption_key"], &inner),
                crypto::encode_key(&key)
            );
        }
        assert!(!blob.contains(&crypto::encode_key(&key)));
    }
    assert!(validate_share_options(42, "").is_err());
    assert!(validate_share_options(0, "12345678901").is_err());
    assert!(validate_share_options(0, "😀😀😀😀😀😀").is_err());
    assert_eq!(
        share_origin(&url::Url::parse("https://api.dev.openmates.org:443/v1").unwrap()).unwrap(),
        "https://app.dev.openmates.org"
    );
}

#[test]
fn project_download_extracts_actual_toon_source_and_never_the_serialized_envelope() {
    let payload=super::super::toon::decode("type: code\nlanguage: rust\nfilename: main.rs\ncode: \"fn main() {\\n  println!(\\\"hello\\\");\\n}\\n\"\n").unwrap();
    assert_eq!(
        project_file_source(&payload).unwrap(),
        "fn main() {\n  println!(\"hello\");\n}\n"
    );
    assert!(
        project_file_source(&json!({"type":"upload","encrypted_content":"ciphertext"})).is_err()
    );
    assert!(project_file_source(&json!({"code":"bad\u{0000}data"})).is_err());
}

#[cfg(unix)]
#[test]
fn download_creation_and_confirmed_replacement_are_atomic_private_and_no_clobber() {
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("export.md");
    Destination::new(&path, false)
        .unwrap()
        .write(b"private export")
        .unwrap();
    assert_eq!(std::fs::read(&path).unwrap(), b"private export");
    assert_eq!(
        std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
        0o600
    );
    assert!(Destination::new(&path, false).is_err());
    Destination::new(&path, true)
        .unwrap()
        .write(b"updated export")
        .unwrap();
    assert_eq!(std::fs::read(&path).unwrap(), b"updated export");
    assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 1);
    let absent = directory.path().join("new.md");
    let target = Destination::new(&absent, false).unwrap();
    std::fs::write(&absent, b"concurrent file").unwrap();
    assert!(target.write(b"must not replace").is_err());
    assert_eq!(std::fs::read(&absent).unwrap(), b"concurrent file");
}

#[cfg(unix)]
#[test]
fn destination_rejects_symlinks_hardlinks_and_changed_targets() {
    use std::os::unix::fs::symlink;
    let directory = tempfile::tempdir().unwrap();
    let source = directory.path().join("source");
    std::fs::write(&source, b"original").unwrap();
    let linked = directory.path().join("linked");
    symlink(&source, &linked).unwrap();
    assert!(Destination::new(&linked, true).is_err());
    std::fs::remove_file(&linked).unwrap();
    std::fs::hard_link(&source, &linked).unwrap();
    assert!(Destination::new(&linked, true).is_err());
    std::fs::remove_file(&linked).unwrap();
    let parent = directory.path().join("parent-link");
    symlink(directory.path(), &parent).unwrap();
    assert!(Destination::new(&parent.join("export"), false).is_err());
    let target = Destination::new(&source, true).unwrap();
    std::fs::rename(&source, directory.path().join("old")).unwrap();
    std::fs::write(&source, b"replacement").unwrap();
    assert!(target.write(b"must not replace").is_err());
    assert_eq!(std::fs::read(&source).unwrap(), b"replacement");
    let target = Destination::new(&source, true).unwrap();
    std::fs::write(&source, b"concurrent edit with different size").unwrap();
    assert!(target.write(b"must not replace").is_err());
}
