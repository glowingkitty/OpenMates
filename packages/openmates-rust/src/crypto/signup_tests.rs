// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use serde_json::Value;

/// Replays the exact byte streams the npm generator injected (see the vector file).
fn streams() -> (impl FnMut(&mut [u8]), impl FnMut(&mut [u8])) {
    let mut k = 0usize;
    let mut n = 0usize;
    (
        move |bytes: &mut [u8]| {
            for byte in bytes {
                *byte = ((k * 37 + 11) & 0xff) as u8;
                k += 1;
            }
        },
        move |bytes: &mut [u8]| {
            for byte in bytes {
                *byte = ((n * 53 + 7) & 0xff) as u8;
                n += 1;
            }
        },
    )
}

#[test]
fn signup_and_recovery_material_match_npm_generated_vectors() {
    let vector: Value = serde_json::from_str(include_str!("signup_vectors.json")).unwrap();
    let expected = &vector["signup"];
    let (mut web, mut nacl) = streams();
    let material = signup_material_with(
        vector["email"].as_str().unwrap(),
        vector["password"].as_str().unwrap(),
        Randomness {
            web: &mut web,
            nacl: &mut nacl,
        },
    )
    .unwrap();
    for (actual, field) in [
        (material.hashed_email.as_str(), "hashedEmail"),
        (material.encrypted_email.as_str(), "encryptedEmail"),
        (
            material.encrypted_email_with_master_key.as_str(),
            "encryptedEmailWithMasterKey",
        ),
        (material.user_email_salt.as_str(), "userEmailSaltB64"),
        (
            material.email_encryption_key.as_str(),
            "emailEncryptionKeyB64",
        ),
        (material.encrypted_master_key.as_str(), "encryptedMasterKey"),
        (material.key_iv.as_str(), "keyIv"),
        (material.salt.as_str(), "saltB64"),
        (material.password_auth_key.as_str(), "passwordAuthKey"),
    ] {
        assert_eq!(actual, expected[field].as_str().unwrap(), "{field}");
    }
    assert_eq!(
        STANDARD.encode(material.master_key.as_ref()),
        expected["masterKeyB64"]
    );
    assert_eq!(material.credential_version, 2);
    // The existing login unwrap opens the signup wrapper with the same password.
    let opened = crate::crypto::unwrap_password_master_key(
        vector["password"].as_str().unwrap(),
        2,
        &material.encrypted_master_key,
        &material.salt,
        &material.key_iv,
    )
    .unwrap();
    assert_eq!(opened.as_ref(), material.master_key.as_ref());

    let recovery =
        recovery_key_material_with(&material.master_key, &material.user_email_salt, &mut web)
            .unwrap();
    let expected = &vector["recovery"];
    assert_eq!(recovery.recovery_key.as_str(), expected["recoveryKey"]);
    assert_eq!(recovery.lookup_hash, expected["lookupHash"]);
    assert_eq!(recovery.wrapped_master_key, expected["wrappedMasterKey"]);
    assert_eq!(recovery.key_iv, expected["keyIv"]);
    assert_eq!(recovery.salt, expected["saltB64"]);
}

#[test]
fn generated_material_is_fresh_and_recovery_keys_cover_every_class() {
    let first = signup_material("a@example.org", "pw").unwrap();
    let second = signup_material("a@example.org", "pw").unwrap();
    assert_ne!(first.master_key.as_ref(), second.master_key.as_ref());
    assert_ne!(first.salt, second.salt);
    assert!(!first.encrypted_email.contains("example"));
    let recovery = recovery_key_material(&first.master_key, &first.user_email_salt).unwrap();
    let key = recovery.recovery_key.as_str();
    assert_eq!(key.len(), 24);
    for set in [
        "ABCDEFGHJKLMNPQRSTUVWXYZ",
        "abcdefghijkmnopqrstuvwxyz",
        "23456789",
        "#-=+_&%$",
    ] {
        assert!(key.chars().any(|c| set.contains(c)), "{set}");
    }
    assert!(signup_material(" ", "pw").is_err());
    assert!(signup_material("a@example.org", "").is_err());
}
